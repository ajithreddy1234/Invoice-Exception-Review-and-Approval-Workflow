"""Evidence-backed human review. No unchecked override or automatic acceptance."""
from datetime import datetime,timezone
from typing import Annotated
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
from threading import BoundedSemaphore
from uuid import UUID,uuid4

from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb
from .auth import Actor,current_actor,require_admin
from .extraction import ExtractionError,InvoiceCandidate,DocumentText
from .adjudication import review_evidence
from .invoice_api import Reason,owned
from .processing import PIPELINE_VERSION,audit,reference_and_ledger,save_validation,transition
from .rules import evaluate

router=APIRouter()
preview_slots=BoundedSemaphore(1)


class LineMapping(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    invoice_line: int=Field(ge=0,le=99)
    po_line_code: str=Field(min_length=1,max_length=100)


class Correction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    base_revision_id: UUID
    candidate: InvoiceCandidate
    reason: str=Field(min_length=5,max_length=2000)
    selected_po: str|None=Field(default=None,max_length=100)
    review_reference_id: UUID|None=None
    line_mappings: list[LineMapping]=Field(default_factory=list,max_length=100)
    verified_ocr_fields: list[Annotated[str,Field(min_length=1,max_length=100)]]=Field(default_factory=list,max_length=710)


def source_row(request,sid,actor):
    row=request.app.state.db.read_one("SELECT * FROM app.submissions WHERE id=%s AND (%s='admin' OR uploaded_by=%s)",(sid,actor.role,actor.id))
    if not row:raise HTTPException(404,'SUBMISSION_NOT_FOUND')
    if row['document_deleted_at'] or row['document_expires_at']<=datetime.now(timezone.utc):
        raise HTTPException(410,'SOURCE_DOCUMENT_EXPIRED')
    return row


def source_bytes(request,row):
    try:data=request.app.state.storage.download(row['storage_key'])
    except Exception:raise HTTPException(503,'SOURCE_DOCUMENT_UNAVAILABLE') from None
    if sha256(data).hexdigest()!=row['file_sha256']:raise HTTPException(409,'SOURCE_HASH_MISMATCH')
    return data


@router.get('/api/submissions/{sid}/pages/{page}')
def preview(sid: UUID,page: int,request: Request,actor: Actor=Depends(current_actor)):
    if not 1<=page<=3:raise HTTPException(404,'PAGE_NOT_FOUND')
    row=source_row(request,sid,actor)
    if row['mime_type']!='application/pdf' and page!=1:raise HTTPException(404,'PAGE_NOT_FOUND')
    if row['page_count'] and page>row['page_count']:raise HTTPException(404,'PAGE_NOT_FOUND')
    data=source_bytes(request,row)
    if not preview_slots.acquire(timeout=2):raise HTTPException(429,'PREVIEW_BUSY_TRY_AGAIN')
    try:
        rendered=subprocess.run([sys.executable,'-m','app.preview_worker',row['mime_type'],str(page)],
            input=data,capture_output=True,timeout=20,cwd=Path(__file__).resolve().parents[1])
        if rendered.returncode or not rendered.stdout.startswith(b'\x89PNG'):raise ValueError
    except Exception:raise HTTPException(422,'PREVIEW_UNAVAILABLE_OPEN_ORIGINAL') from None
    finally:preview_slots.release()
    return Response(rendered.stdout,media_type='image/png',headers={'Cache-Control':'private, no-store'})


@router.post('/api/admin/submissions/{sid}/request-document')
def request_document(sid: UUID,body: Reason,request: Request,actor: Actor=Depends(require_admin)):
    if len(body.reason.strip())<5:raise HTTPException(422,'REASON_REQUIRED')
    with request.app.state.db.transaction() as c:
        row=owned(c,sid,actor,True)
        if row['status'] not in ('needs_review','reference_hold'):raise HTTPException(409,'INVOICE_NOT_REVIEWABLE')
        c.execute("INSERT INTO app.review_actions(submission_id,actor_id,action,reason,before_revision_id) VALUES(%s,%s,'request_document',%s,%s)",(sid,actor.id,body.reason.strip(),row['current_revision_id']))
        audit(c,sid,'review.document_requested',actor.id,details={'reason':body.reason.strip(),'delivery':'in_app_only'})
    return {'status':'document_requested','delivery':'in_app_only'}


@router.post('/api/admin/submissions/{sid}/correct')
def correct(sid: UUID,body: Correction,request: Request,actor: Actor=Depends(require_admin)):
    if len(body.reason.strip())<5:raise HTTPException(422,'REASON_REQUIRED')
    if request.app.state.pipeline is None:raise HTTPException(503,'PROCESSING_NOT_CONFIGURED')
    row=source_row(request,sid,actor)
    if row['status'] not in ('needs_review','reference_hold'):raise HTTPException(409,'INVOICE_NOT_REVIEWABLE')
    if row['current_revision_id']!=body.base_revision_id:raise HTTPException(409,'REVISION_CHANGED_RELOAD')
    # Only server-read bytes/text can substantiate a correction. No browser text
    # layer, procurement amount or invented quote can stand in for source evidence.
    try:document=request.app.state.pipeline.reader(source_bytes(request,row),row['mime_type'])
    except ExtractionError:raise HTTPException(422,'READABLE_SOURCE_REQUIRED') from None
    _,issues=review_evidence(body.candidate,document,body.verified_ocr_fields)
    if len(set(body.verified_ocr_fields)) != len(body.verified_ocr_fields):
        raise HTTPException(422,'DUPLICATE_OCR_VERIFICATION')
    unsupported=[i.model_dump() for i in issues if i.code not in ('MISSING_CRITICAL_FIELD','EXTRACTION_UNCERTAIN')]
    if unsupported:raise HTTPException(422,{'code':'CORRECTION_SOURCE_NOT_SUPPORTED','issues':unsupported})
    with request.app.state.db.transaction() as c:
        ref,ledger=reference_and_ledger(c,body.candidate,row['file_sha256'])
    if not ref or not ref['fresh']:raise HTTPException(409,'REFERENCE_STALE_OR_MISSING')
    baseline=evaluate(body.candidate,document,ref,ledger)
    if body.selected_po and (body.candidate.po_reference.value or len(baseline.po_candidates)<2 or body.selected_po not in {p['po_code'] for p in baseline.po_candidates}):
        raise HTTPException(422,'SELECT_ONLY_AN_EXACT_AMBIGUOUS_PO_CANDIDATE')
    mappings={row.invoice_line:row.po_line_code for row in body.line_mappings}
    if len(mappings)!=len(body.line_mappings):raise HTTPException(422,'DUPLICATE_LINE_MAPPING')
    context=evaluate(body.candidate,document,ref,ledger,selected_po=body.selected_po)
    if mappings:
        if body.review_reference_id is None:raise HTTPException(422,'REVIEW_REFERENCE_REQUIRED')
        if str(body.review_reference_id)!=str(ref['id']):raise HTTPException(409,'REVIEW_REFERENCE_CHANGED_RELOAD')
        checks={c['code']:c['status'] for c in context.checks}
        if any(checks[code]!='pass' for code in ('vendor_match','po_match','currency')):
            raise HTTPException(422,'MATCH_VENDOR_PO_AND_CURRENCY_BEFORE_LINE_MAPPING')
        allowed={line['line_code'] for line in ref['lines'] if line['po_code']==context.po_code}
        if any(index>=len(body.candidate.line_items) or code not in allowed for index,code in mappings.items()):
            raise HTTPException(422,'INVALID_PO_LINE_MAPPING')
    decision=evaluate(body.candidate,document,ref,ledger,selected_po=body.selected_po,
                      line_mappings=mappings,verified_ocr_fields=body.verified_ocr_fields)
    with request.app.state.db.transaction() as c:
        c.execute('SELECT app.lock_processing_context(%s,%s,%s)',(sid,decision.po_code,actor.id))
        current=owned(c,sid,actor,True)
        role=c.execute("SELECT role FROM app.profiles WHERE user_id=%s AND enabled",(actor.id,)).fetchone()
        if not role or role['role']!='admin':raise HTTPException(403,'ADMIN_REQUIRED')
        if current['current_revision_id']!=body.base_revision_id:raise HTTPException(409,'REVISION_CHANGED_RELOAD')
        if current['status'] not in ('needs_review','reference_hold'):raise HTTPException(409,'INVOICE_NOT_REVIEWABLE')
        if current['document_deleted_at'] or current['document_expires_at']<=datetime.now(timezone.utc):raise HTTPException(410,'SOURCE_DOCUMENT_EXPIRED')
        if c.execute("SELECT id FROM app.processing_runs WHERE submission_id=%s AND state IN ('queued','running')",(sid,)).fetchone():raise HTTPException(409,'PROCESSING_IN_PROGRESS')
        latest,ledger=reference_and_ledger(c,body.candidate,current['file_sha256'])
        if not latest or latest['id']!=ref['id'] or not latest['fresh']:raise HTTPException(409,'REFERENCE_CHANGED_REVALIDATE')
        decision=evaluate(body.candidate,document,latest,ledger,selected_po=body.selected_po,
                          line_mappings=mappings,verified_ocr_fields=body.verified_ocr_fields)
        decision.revision['evidence']['review_context'].update({'actor_id':str(actor.id),
            'reason':body.reason.strip(),'source_sha256':current['file_sha256'],
            'base_revision_id':str(body.base_revision_id),'reference_version_id':str(latest['id']),
            'selected_po':body.selected_po})
        run_id=uuid4()
        c.execute("INSERT INTO app.processing_runs(id,submission_id,pipeline_version,state,stage,started_at,finished_at) VALUES(%s,%s,%s,'completed','admin_revalidated',now(),now())",(run_id,sid,PIPELINE_VERSION))
        revision_id,validation_id=save_validation(c,sid,run_id,body.candidate,document,latest,decision,actor_id=actor.id,reason=body.reason.strip())
        if current['status']=='reference_hold':transition(c,sid,actor.id,'needs_review',body.reason)
        c.execute("INSERT INTO app.review_actions(submission_id,actor_id,action,reason,before_revision_id,after_revision_id,validation_id,details) VALUES(%s,%s,'correct_fields',%s,%s,%s,%s,%s)",
          (sid,actor.id,body.reason.strip(),body.base_revision_id,revision_id,validation_id,Jsonb({'selected_po':body.selected_po,'source_sha256':current['file_sha256'],
              'review_context':decision.revision['evidence']['review_context']})))
        if body.selected_po:
            c.execute("INSERT INTO app.review_actions(submission_id,actor_id,action,reason,before_revision_id,after_revision_id,validation_id,details) VALUES(%s,%s,'select_po',%s,%s,%s,%s,%s)",
              (sid,actor.id,body.reason.strip(),body.base_revision_id,revision_id,validation_id,Jsonb({'po_code':body.selected_po,'candidates':baseline.po_candidates})))
        audit(c,sid,'review.revalidated',actor.id,run_id,details={'reason':body.reason.strip(),'before_revision_id':str(body.base_revision_id),'revision_id':str(revision_id),'validation_id':str(validation_id),'verdict':decision.verdict,'selected_po':body.selected_po,
            'manual_line_mappings':len(mappings),'verified_ocr_fields':body.verified_ocr_fields})
    return {'status':'needs_review','revision_id':str(revision_id),'validation_id':str(validation_id),
            'verdict':decision.verdict,'acceptance_mode':'admin_required' if decision.verdict=='eligible' else 'not_allowed'}


@router.get('/api/admin/submissions/{sid}/review-options')
def review_options(sid: UUID,request: Request,actor: Actor=Depends(require_admin)):
    row=source_row(request,sid,actor)
    if row['status'] not in ('needs_review','reference_hold') or not row['current_revision_id']:
        raise HTTPException(409,'INVOICE_NOT_REVIEWABLE')
    revision=request.app.state.db.read_one('SELECT evidence FROM app.invoice_revisions WHERE id=%s',(row['current_revision_id'],))
    candidate=InvoiceCandidate.model_validate(revision['evidence']['candidate'])
    document=DocumentText.model_validate(revision['evidence']['document'])
    with request.app.state.db.transaction() as c:
        ref,ledger=reference_and_ledger(c,candidate,row['file_sha256'])
    if not ref or not ref['fresh']:raise HTTPException(409,'REFERENCE_STALE_OR_MISSING')
    decision=evaluate(candidate,document,ref,ledger)
    checks={c['code']:c['status'] for c in decision.checks}
    pos=[]
    if checks['vendor_match']=='pass':
        for item in decision.po_candidates:
            po=next(p for p in ref['pos'] if p['po_code']==item['po_code'])
            # An explicit PO can exist while belonging to a different vendor.
            selected=evaluate(candidate,document,ref,ledger,selected_po=None if candidate.po_reference.value else po['po_code'])
            valid={c['code']:c['status'] for c in selected.checks}
            if valid['po_match']=='pass' and valid['currency']=='pass':
                pos.append({'po_code':po['po_code'],'lines':[line for line in ref['lines'] if line['po_code']==po['po_code']]})
    raw,_=review_evidence(candidate,document)
    fields={i.field for i in raw if i.code=='LOW_OCR_CONFIDENCE'}-{i.field for i in raw if i.code!='LOW_OCR_CONFIDENCE'}
    return {'revision_id':row['current_revision_id'],'reference_version_id':ref['id'],
            'pos':pos,'ocr_fields':sorted(fields),
            'prior_review_context':revision['evidence'].get('review_context',{})}

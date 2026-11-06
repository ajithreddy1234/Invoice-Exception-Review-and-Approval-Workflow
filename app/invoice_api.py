from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from .auth import Actor, current_actor, require_admin
from .extraction import MAX_BYTES
from .processing import PIPELINE_VERSION, audit, transition
from .decision_view import explain_decision, recorded_timing

router = APIRouter()


def owned(c, sid, actor, lock=False):
    row = c.execute('SELECT * FROM app.submissions WHERE id=%s' + (' FOR UPDATE' if lock else ''),(sid,)).fetchone()
    if not row or (row['uploaded_by'] != actor.id and actor.role != 'admin'):
        raise HTTPException(404,'SUBMISSION_NOT_FOUND')
    return row


def require_pipeline(request):
    if request.app.state.pipeline is None:
        raise HTTPException(503,'PROCESSING_NOT_CONFIGURED')


def require_capacity(c, actor_id, limits, exclude=None):
    """Caller holds the intake advisory lock before reserving new pending work."""
    pending=c.execute('''SELECT count(*) AS total,
        count(*) FILTER(WHERE s.uploaded_by=%s) AS owned FROM app.submissions s
        WHERE s.id IS DISTINCT FROM %s::uuid
        AND s.document_deleted_at IS NULL AND s.document_expires_at>now()
        AND (s.status IN ('received','processing') OR EXISTS(SELECT 1 FROM app.processing_runs r
             WHERE r.submission_id=s.id AND r.state IN ('queued','running')))''',(actor_id,exclude)).fetchone()
    if pending['owned']>=limits.max_pending_per_user:
        raise HTTPException(429,'USER_PENDING_LIMIT_REACHED',headers={'Retry-After':'30'})
    if pending['total']>=limits.max_pending_total:
        raise HTTPException(429,'WORKSPACE_PENDING_LIMIT_REACHED',headers={'Retry-After':'30'})


@router.post('/api/submissions',status_code=202)
def upload(request: Request, file: UploadFile = File(...), request_key: UUID = Form(...), actor: Actor = Depends(current_actor)):
    require_pipeline(request)
    data = file.file.read(MAX_BYTES+1)
    file.file.close()
    if not data or len(data)>MAX_BYTES:
        raise HTTPException(413 if data else 422,'DOCUMENT_TOO_LARGE' if data else 'EMPTY_DOCUMENT')
    mime = (file.content_type or '').split(';')[0].lower()
    signatures = {'application/pdf':b'%PDF-','image/png':b'\x89PNG\r\n\x1a\n','image/jpeg':b'\xff\xd8\xff'}
    if mime not in signatures or not data.startswith(signatures[mime]):
        raise HTTPException(422,'UNSUPPORTED_OR_INVALID_FILE')
    digest = sha256(data).hexdigest()
    sid=uuid4();ext={'application/pdf':'pdf','image/jpeg':'jpg','image/png':'png'}[mime]
    key=f'{actor.id}/{sid}/{digest}.{ext}'
    filename=(file.filename or 'invoice').replace('\\','/').rsplit('/',1)[-1][:180]
    with request.app.state.db.transaction() as c:
        # Serialize only the short count/reservation transaction, never storage
        # I/O. This also enforces capacity across processes/restarts.
        c.execute('SELECT pg_advisory_xact_lock(1095975233,1)')
        row=c.execute('SELECT * FROM app.submissions WHERE uploaded_by=%s AND request_key=%s',(actor.id,request_key)).fetchone()
        if row:
            if row['file_sha256']!=digest:
                raise HTTPException(409,'IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_FILE')
            if row['status']!='received':
                return {'id':str(row['id']),'status':row['status'],'idempotent_replay':True}
        else:
            require_capacity(c,actor.id,request.app.state.settings)
            row=c.execute('''INSERT INTO app.submissions(id,uploaded_by,request_key,original_filename,mime_type,file_sha256,byte_size,storage_key)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (sid,actor.id,request_key,filename,mime,digest,len(data),key)).fetchone()
            audit(c,row['id'],'submission.received',actor.id,details={'byte_size':len(data),'mime_type':mime})
    try:
        request.app.state.storage.upload(row['storage_key'],data,mime)
    except Exception:
        # Keep received row: replaying the same request safely resumes an uncertain write.
        raise HTTPException(503,{'code':'SOURCE_UPLOAD_UNAVAILABLE','submission_id':str(row['id']),'retry_same_request_key':True}) from None
    with request.app.state.db.transaction() as c:
        s=owned(c,row['id'],actor,True)
        if s['status']!='received':
            return {'id':str(s['id']),'status':s['status'],'idempotent_replay':True}
        run=c.execute('''INSERT INTO app.processing_runs(submission_id,pipeline_version) VALUES(%s,%s)
            ON CONFLICT(submission_id) WHERE state IN ('queued','running') DO NOTHING RETURNING id''',(s['id'],PIPELINE_VERSION)).fetchone()
        if not run:
            run=c.execute("SELECT id FROM app.processing_runs WHERE submission_id=%s AND state IN ('queued','running')",(s['id'],)).fetchone()
        audit(c,s['id'],'source.stored',actor.id,run=run['id'])
    return {'id':str(row['id']),'status':'received','run_id':str(run['id'])}


DETAIL_SQL = """
SELECT to_jsonb(s)-'storage_key' AS submission,
 (SELECT to_jsonb(r)-'lease_token'-'lease_until' FROM app.processing_runs r
  WHERE r.submission_id=s.id ORDER BY r.created_at DESC LIMIT 1) AS run,
 (SELECT to_jsonb(r) FROM app.invoice_revisions r WHERE r.id=s.current_revision_id) AS revision,
 (SELECT to_jsonb(v) FROM app.validation_results v WHERE v.submission_id=s.id
  ORDER BY v.created_at DESC LIMIT 1) AS validation,
 (SELECT to_jsonb(a) FROM app.acceptances a WHERE a.submission_id=s.id) AS acceptance,
 (SELECT jsonb_build_object('id',r.id,'imported_at',r.imported_at,'valid_until',r.valid_until,'fresh',r.valid_until>now(),
  'is_active',EXISTS(SELECT 1 FROM app.runtime_state t WHERE t.singleton AND t.active_reference_version_id=r.id))
  FROM app.validation_results v JOIN app.reference_versions r ON r.id=v.reference_version_id
  WHERE v.submission_id=s.id ORDER BY v.created_at DESC LIMIT 1) AS reference,
 (SELECT jsonb_build_object('reference_version_id',v.reference_version_id,'currency',r.currency,'po_currency',p.currency,
  'billing_mode',p.billing_mode,'authorized_gross_minor',p.authorized_gross_minor,
  'auto_accept_enabled',r.auto_accept_enabled,'arithmetic_tolerance_minor',r.arithmetic_tolerance_minor,
  'price_tolerance_bps',r.price_tolerance_bps)
  FROM app.validation_results v JOIN app.reference_pos p
  ON p.reference_version_id=v.reference_version_id AND p.po_code=v.po_code
  JOIN app.invoice_revisions ir ON ir.id=v.revision_id
  JOIN app.reference_rules r ON r.reference_version_id=p.reference_version_id AND r.currency=ir.currency
  WHERE v.submission_id=s.id ORDER BY v.created_at DESC LIMIT 1) AS policy,
 (SELECT jsonb_build_object('submission_id',a.submission_id,'acceptance_id',a.id,'invoice_number',a.invoice_number)
  FROM app.acceptances a JOIN app.submissions original ON original.id=a.submission_id
  WHERE s.status='blocked_duplicate' AND (a.document_sha256=s.file_sha256 OR EXISTS
    (SELECT 1 FROM app.invoice_revisions r WHERE r.id=s.current_revision_id
     AND app.invoice_key(r.invoice_number)=a.normalized_invoice_number
     AND EXISTS(SELECT 1 FROM app.validation_results v JOIN app.reference_pos p
       ON p.reference_version_id=v.reference_version_id AND p.po_code=v.po_code
       WHERE v.submission_id=s.id AND p.vendor_code=a.vendor_code)))
  AND (original.uploaded_by=s.uploaded_by OR %s='admin') LIMIT 1) AS duplicate_record,
 coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM app.audit_events e
  WHERE e.run_id=(SELECT r.id FROM app.processing_runs r WHERE r.submission_id=s.id ORDER BY r.created_at DESC LIMIT 1)
  AND e.event_type='processing.stage'),'[]') AS stage_events,
 coalesce((SELECT jsonb_agg(jsonb_build_object('id',r.id,'revision_no',r.revision_no,'kind',r.kind,
  'reason',r.correction_reason,'created_at',r.created_at) ORDER BY r.revision_no DESC)
  FROM app.invoice_revisions r WHERE r.submission_id=s.id),'[]') AS revisions,
 coalesce((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.created_at DESC) FROM app.review_actions r
  WHERE r.submission_id=s.id),'[]') AS reviews,
 (SELECT jsonb_build_object('status',e.status,'attempt_count',e.attempt_count,'last_error',e.last_error,
  'published_at',e.published_at,'sheet_range',e.sheet_range)
  FROM app.export_tasks e JOIN app.acceptances a ON a.id=e.acceptance_id WHERE a.submission_id=s.id) AS publication,
 coalesce((SELECT jsonb_agg(to_jsonb(e)-'id' ORDER BY e.id) FROM
  (SELECT id,run_id,event_type,stage,details,created_at FROM app.audit_events WHERE submission_id=s.id ORDER BY id DESC LIMIT 100) e),'[]') AS audit,
 (SELECT count(*) FROM app.audit_events WHERE submission_id=s.id) AS audit_event_count
FROM app.submissions s WHERE s.id=%s AND (%s='admin' OR s.uploaded_by=%s)
"""


@router.get('/api/submissions/{sid}')
def detail(sid: UUID,request: Request,actor: Actor = Depends(current_actor)):
    result=request.app.state.db.read_one(DETAIL_SQL,(actor.role,sid,actor.role,actor.id))
    if not result:
        raise HTTPException(404,'SUBMISSION_NOT_FOUND')
    result['decision']=explain_decision(result)
    result['timing']=recorded_timing(result.get('run'),result.pop('stage_events',[]))
    return result


@router.get('/api/submissions/{sid}/revisions/{rid}')
def revision_detail(sid: UUID,rid: UUID,request: Request,actor: Actor=Depends(current_actor)):
    # Both IDs are scoped before returning any historical source or reviewer data.
    result=request.app.state.db.read_one('''SELECT to_jsonb(r) AS revision,
      (SELECT jsonb_build_object('id',p.id,'revision_no',p.revision_no,'candidate',p.evidence->'candidate')
       FROM app.invoice_revisions p WHERE p.submission_id=r.submission_id AND p.revision_no<r.revision_no
       ORDER BY p.revision_no DESC LIMIT 1) AS previous_revision,
      (SELECT to_jsonb(v) FROM app.validation_results v WHERE v.revision_id=r.id ORDER BY v.created_at DESC LIMIT 1) AS validation,
      (SELECT jsonb_build_object('id',p.user_id,'display_name',p.display_name) FROM app.profiles p WHERE p.user_id=r.created_by) AS reviewer
      FROM app.invoice_revisions r JOIN app.submissions s ON s.id=r.submission_id
      WHERE r.id=%s AND s.id=%s AND (%s='admin' OR s.uploaded_by=%s)''',(rid,sid,actor.role,actor.id))
    if not result:raise HTTPException(404,'REVISION_NOT_FOUND')
    return result


@router.get('/api/submissions/{sid}/document')
def document(sid: UUID,request: Request,actor: Actor = Depends(current_actor)):
    with request.app.state.db.transaction() as c:
        s=owned(c,sid,actor)
    if s['document_deleted_at'] or s['document_expires_at']<=datetime.now(timezone.utc):
        raise HTTPException(410,'SOURCE_DOCUMENT_EXPIRED')
    try:
        data=request.app.state.storage.download(s['storage_key'])
    except Exception:
        raise HTTPException(503,'SOURCE_DOCUMENT_UNAVAILABLE') from None
    if sha256(data).hexdigest()!=s['file_sha256']:
        raise HTTPException(409,'SOURCE_HASH_MISMATCH')
    return Response(content=data,media_type=s['mime_type'],headers={'Content-Disposition':'inline; filename="invoice.'+{'application/pdf':'pdf','image/jpeg':'jpg','image/png':'png'}[s['mime_type']]+'"'})


@router.post('/api/submissions/{sid}/retry',status_code=202)
def retry(sid: UUID,request: Request,actor: Actor = Depends(current_actor)):
    require_pipeline(request)
    with request.app.state.db.transaction() as c:
        c.execute('SELECT pg_advisory_xact_lock(1095975233,1)')
        s=owned(c,sid,actor,True)
        if s['status'] not in ('processing_failed','reference_hold','needs_review','received'):
            raise HTTPException(409,'SUBMISSION_CANNOT_BE_REPROCESSED')
        if s['document_deleted_at'] or s['document_expires_at']<=datetime.now(timezone.utc):
            raise HTTPException(410,'SOURCE_DOCUMENT_EXPIRED')
        active=c.execute("SELECT id FROM app.processing_runs WHERE submission_id=%s AND state IN ('queued','running')",(sid,)).fetchone()
        if active:
            return {'id':str(sid),'run_id':str(active['id']),'status':s['status'],'idempotent_replay':True}
        if s['status']!='received':
            require_capacity(c,actor.id,request.app.state.settings,exclude=sid)
        r=c.execute('INSERT INTO app.processing_runs(submission_id,pipeline_version) VALUES(%s,%s) RETURNING id',(sid,PIPELINE_VERSION)).fetchone()
        audit(c,sid,'processing.retry_requested',actor.id,run=r['id'])
    return {'id':str(sid),'run_id':str(r['id']),'status':s['status']}


class Reason(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    reason: str = Field(min_length=5,max_length=1000)


@router.post('/api/admin/submissions/{sid}/reject')
def reject(sid: UUID,body: Reason,request: Request,actor: Actor = Depends(require_admin)):
    with request.app.state.db.transaction() as c:
        s=owned(c,sid,actor,True)
        if s['status']!='needs_review':
            raise HTTPException(409,'ONLY_REVIEWABLE_INVOICES_CAN_BE_REJECTED')
        transition(c,sid,actor.id,'rejected',body.reason)
        c.execute("INSERT INTO app.review_actions(submission_id,actor_id,action,reason,before_revision_id) VALUES(%s,%s,'reject',%s,%s)",(sid,actor.id,body.reason,s['current_revision_id']))
    return {'id':str(sid),'status':'rejected'}


@router.post('/api/admin/submissions/{sid}/accept')
def accept(sid: UUID,body: Reason,request: Request,actor: Actor = Depends(require_admin)):
    with request.app.state.db.transaction() as c:
        s=owned(c,sid,actor)
        v=c.execute('SELECT * FROM app.validation_results WHERE submission_id=%s AND revision_id=%s ORDER BY created_at DESC LIMIT 1',(sid,s['current_revision_id'])).fetchone()
        if not v or v['verdict']!='eligible':
            raise HTTPException(409,'UNRESOLVED_CHECKS_REQUIRE_EVIDENCED_REVALIDATION')
        try:
            with c.transaction():
                a=c.execute("SELECT app.accept_invoice(%s,%s,'admin',%s) AS id",(v['id'],actor.id,body.reason)).fetchone()
        except Exception:
            raise HTTPException(409,'ACCEPTANCE_RECHECK_FAILED_REVALIDATE') from None
        c.execute("INSERT INTO app.review_actions(submission_id,actor_id,action,reason,validation_id) VALUES(%s,%s,'authorize_acceptance',%s,%s)",(sid,actor.id,body.reason,v['id']))
        publication=c.execute('SELECT status FROM app.export_tasks WHERE acceptance_id=%s',(a['id'],)).fetchone()
    return {'id':str(sid),'status':'accepted','acceptance_id':str(a['id']),'publication_status':publication['status'] if publication else 'pending'}


@router.post('/api/admin/publication/retry')
def retry_publication(request: Request,actor: Actor = Depends(require_admin)):
    with request.app.state.db.transaction() as c:
        rows=c.execute("UPDATE app.export_tasks SET attempt_count=0,available_at=now(),status='pending' WHERE status IN ('failed','reconciliation_required') RETURNING id").fetchall()
        audit(c,None,'publication.retry_requested',actor.id,details={'count':len(rows)})
    return {'retry_count':len(rows)}


class UploadLimit:
    """Bound the multipart body before Starlette spools an unlimited upload."""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method']!='POST':
            return await self.app(scope,receive,send)
        limit=MAX_BYTES+262144
        total=0
        async def bounded():
            nonlocal total
            event=await receive();total+=len(event.get('body',b''))
            if total>limit:raise HTTPException(status_code=413,detail='REQUEST_TOO_LARGE')
            return event
        await self.app(scope,bounded,send)

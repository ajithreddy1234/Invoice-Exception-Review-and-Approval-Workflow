"""Durable leases and atomic decisions. Network/LLM/OCR never holds a DB lock."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from .extraction import DocumentText, ExtractionError, GeminiExtractor, EXTRACTION_PROMPT_VERSION
from .publication import PublicationConflict, SheetsPublisher
from .rules import evaluate

PIPELINE_VERSION = 'invoice-v0.4.1'


def audit(conn, sid, event, actor=None, run=None, stage=None, details=None):
    conn.execute('''INSERT INTO app.audit_events(submission_id,run_id,actor_id,event_type,stage,details)
        VALUES(%s,%s,%s,%s,%s,%s)''', (sid, run, actor, event, stage, Jsonb(details or {})))


def transition(conn, sid, actor, state, reason=None):
    return conn.execute('SELECT app.transition_submission(%s,%s,%s,%s)', (sid, actor, state, reason)).fetchone()


def isolated_document(data, mime):
    try:
        p = subprocess.run([sys.executable, '-m', 'app.document_worker', mime], input=data,
                           capture_output=True, timeout=100, cwd=Path(__file__).resolve().parents[1])
        output = json.loads(p.stdout)
        if p.returncode or 'error_code' in output:
            raise ExtractionError(output.get('error_code', 'DOCUMENT_READ_FAILED'))
        return DocumentText.model_validate(output)
    except subprocess.TimeoutExpired:
        raise ExtractionError('DOCUMENT_READ_TIMEOUT') from None
    except (ValueError, OSError):
        raise ExtractionError('DOCUMENT_READ_FAILED') from None


def reference_and_ledger(conn, candidate, file_hash):
    header = conn.execute('''SELECT v.*,v.valid_until>now() AS fresh FROM app.runtime_state s
      JOIN app.reference_versions v ON v.id=s.active_reference_version_id WHERE s.singleton''').fetchone()
    if not header:
        return None, None
    ref = {'id': str(header['id']), 'fresh': header['fresh']}
    for key, table in [('vendors','reference_vendors'),('pos','reference_pos'),('lines','reference_lines'),('rules','reference_rules')]:
        ref[key] = conn.execute(f'SELECT * FROM app.{table} WHERE reference_version_id=%s', (header['id'],)).fetchall()
    amounts = conn.execute('SELECT po_code,sum(amount_minor) AS used FROM app.acceptances GROUP BY po_code').fetchall()
    quantities = conn.execute('''SELECT a.po_code,l.line_code,sum(l.quantity) AS used FROM app.acceptances a
      JOIN app.validation_lines l ON l.validation_id=a.validation_id GROUP BY a.po_code,l.line_code''').fetchall()
    vendor_name = ' '.join((candidate.vendor_name.value or '').casefold().split())
    vendor_codes = []
    for v in ref['vendors']:
        if vendor_name in {' '.join(x.casefold().split()) for x in [v['legal_name'], *v['aliases']]}:
            vendor_codes.append(v['vendor_code'])
    duplicate = conn.execute('''SELECT EXISTS(SELECT 1 FROM app.acceptances WHERE document_sha256=%s
      OR (vendor_code=ANY(%s) AND normalized_invoice_number=app.invoice_key(%s))) AS duplicate''',
      (file_hash, vendor_codes, candidate.invoice_number.value)).fetchone()['duplicate']
    return ref, {'accepted_amounts': {r['po_code']: int(r['used']) for r in amounts},
                 'accepted_quantities': {(r['po_code'],r['line_code']): r['used'] for r in quantities},
                 'duplicate': duplicate}


def save_validation(c, submission_id, run_id, candidate, document, reference, decision,
                    *, actor_id=None, reason=None, extractor_metadata=None):
    """Append an immutable revision and frozen validation; caller owns locks."""
    revision = dict(decision.revision)
    revision['evidence'] = {**revision.get('evidence',{}), 'candidate':candidate.model_dump(mode='json'),
                            'document':document.model_dump(mode='json')}
    if extractor_metadata is not None:
        revision['evidence']['extractor'] = extractor_metadata
    revision_id=uuid4();validation_id=uuid4()
    number=c.execute('SELECT coalesce(max(revision_no),0)+1 AS n FROM app.invoice_revisions WHERE submission_id=%s',(submission_id,)).fetchone()['n']
    columns=['invoice_number','invoice_date','vendor_name','po_reference','currency','subtotal_net_minor','tax_minor','total_gross_minor','tax_presentation','line_items','evidence','unresolved_critical_fields']
    values=[Jsonb(revision[k]) if k in ('line_items','evidence','unresolved_critical_fields') else revision[k] for k in columns]
    c.execute(f"INSERT INTO app.invoice_revisions(id,submission_id,revision_no,kind,created_by,correction_reason,{','.join(columns)}) VALUES(%s,%s,%s,%s,%s,%s,{','.join(['%s']*len(columns))})",
      (revision_id,submission_id,number,'admin_correction' if actor_id else 'extraction',actor_id,reason,*values))
    c.execute('UPDATE app.submissions SET current_revision_id=%s,page_count=%s,updated_at=now() WHERE id=%s',(revision_id,len(document.pages),submission_id))
    c.execute('UPDATE app.processing_runs SET revision_id=%s WHERE id=%s',(revision_id,run_id))
    c.execute('''INSERT INTO app.validation_results(id,run_id,submission_id,revision_id,reference_version_id,
      po_code,verdict,acceptance_mode,engine_version,checks,po_candidates,summary)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
      (validation_id,run_id,submission_id,revision_id,reference['id'],decision.po_code,decision.verdict,
       'admin_required' if actor_id and decision.verdict=='eligible' else decision.acceptance_mode,
       PIPELINE_VERSION,Jsonb(decision.checks),Jsonb(decision.po_candidates),
       'All nine checks pass. Explicit administrator acceptance is required after correction.' if actor_id and decision.verdict=='eligible' else decision.summary))
    for line in decision.allocations:
        c.execute('''INSERT INTO app.validation_lines(validation_id,reference_version_id,po_code,line_code,quantity,net_minor,tax_minor,gross_minor)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',(validation_id,reference['id'],decision.po_code,line['line_code'],line['quantity'],line['net_minor'],line['tax_minor'],line['gross_minor']))
    c.execute('UPDATE app.validation_results SET completed_at=now() WHERE id=%s',(validation_id,))
    return revision_id,validation_id


class Pipeline:
    def __init__(self, db, settings, storage, extractor=None, reader=None, publisher_factory=None):
        self.db, self.settings, self.storage = db, settings, storage
        self.extractor = extractor or GeminiExtractor(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
        self.reader = reader or isolated_document
        self.publisher_factory = publisher_factory or (lambda sheet: SheetsPublisher(sheet, settings.google_application_credentials))

    def recover_intake(self):
        # Upload committed before a crash can be resumed without an in-memory queue.
        with self.db.transaction() as c:
            rows = c.execute('''SELECT s.* FROM app.submissions s WHERE s.status='received'
                AND s.created_at<now()-interval '30 seconds'
                AND NOT EXISTS(SELECT 1 FROM app.processing_runs r WHERE r.submission_id=s.id)
                ORDER BY s.created_at LIMIT 5''').fetchall()
        for s in rows:
            try:
                data=self.storage.download(s['storage_key'])
                if sha256(data).hexdigest()!=s['file_sha256']:
                    continue
            except Exception:
                # A failed upload must remain resumable with its original request key.
                continue
            with self.db.transaction() as c:
                current=c.execute('SELECT status,document_deleted_at,document_expires_at>now() AS live FROM app.submissions WHERE id=%s FOR UPDATE',(s['id'],)).fetchone()
                if current['status']!='received' or not current['live'] or current['document_deleted_at']:
                    continue
                run=c.execute('''INSERT INTO app.processing_runs(submission_id,pipeline_version) VALUES(%s,%s)
                    ON CONFLICT(submission_id) WHERE state IN ('queued','running') DO NOTHING RETURNING id''',(s['id'],PIPELINE_VERSION)).fetchone()
                if run:
                    audit(c,s['id'],'source.stored',run=run['id'],details={'recovered':True})

    def claim(self):
        token = uuid4()
        with self.db.transaction() as c:
            return c.execute('''WITH next AS (SELECT r.id FROM app.processing_runs r
                JOIN app.submissions s ON s.id=r.submission_id JOIN app.profiles p ON p.user_id=s.uploaded_by
                WHERE p.enabled AND (r.state='queued' OR (r.state='running' AND r.lease_until<now()))
                ORDER BY r.created_at LIMIT 1 FOR UPDATE OF r SKIP LOCKED)
                UPDATE app.processing_runs r SET state='running',lease_token=%s,lease_until=now()+interval '5 minutes',
                attempt_count=r.attempt_count+1,started_at=coalesce(started_at,now()) FROM next
                WHERE r.id=next.id RETURNING r.*''', (token,)).fetchone()

    def fence(self, c, run):
        return c.execute('''SELECT * FROM app.processing_runs WHERE id=%s AND lease_token=%s
            AND state='running' AND lease_until>now() FOR UPDATE''', (run['id'],run['lease_token'])).fetchone()

    def stage(self, run, stage):
        with self.db.transaction() as c:
            if not self.fence(c, run):
                raise RuntimeError('LEASE_LOST')
            c.execute('UPDATE app.processing_runs SET stage=%s,lease_until=now()+interval \'5 minutes\' WHERE id=%s', (stage,run['id']))
            audit(c,run['submission_id'],'processing.stage',run=run['id'],stage=stage)

    def fail(self, run, code, state='processing_failed'):
        with self.db.transaction() as c:
            if not self.fence(c, run):
                return
            s = c.execute('SELECT * FROM app.submissions WHERE id=%s', (run['submission_id'],)).fetchone()
            accepted = c.execute('SELECT id FROM app.acceptances WHERE submission_id=%s', (s['id'],)).fetchone()
            if accepted:
                c.execute("UPDATE app.processing_runs SET state='completed',stage='accepted',finished_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s", (run['id'],))
                return
            if s['status'] == 'received':
                transition(c,s['id'],s['uploaded_by'],'processing')
            if s['status'] in ('received','processing'):
                transition(c,s['id'],s['uploaded_by'],state,code)
            c.execute("UPDATE app.processing_runs SET state='failed',stage='failed',error_code=%s,finished_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s", (code,run['id']))
            audit(c,s['id'],'processing.failed',run=run['id'],details={'code':code})

    def process_once(self):
        run = self.claim()
        if not run:
            return False
        try:
            with self.db.transaction() as c:
                if not self.fence(c,run):
                    return True
                s = c.execute('SELECT * FROM app.submissions WHERE id=%s', (run['submission_id'],)).fetchone()
                accepted = c.execute('SELECT id FROM app.acceptances WHERE submission_id=%s', (s['id'],)).fetchone()
                if accepted:
                    c.execute("UPDATE app.processing_runs SET state='completed',stage='accepted',finished_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s", (run['id'],))
                    return True
                if s['status'] in ('rejected','blocked_duplicate','expired'):
                    c.execute("UPDATE app.processing_runs SET state='failed',stage='stopped',error_code='SUBMISSION_NOT_PROCESSABLE',lease_token=NULL,lease_until=NULL WHERE id=%s",(run['id'],))
                    return True
                if s['status'] != 'processing':
                    transition(c,s['id'],s['uploaded_by'],'processing')
                # Early exact-byte duplicate protection saves OCR/model calls.
                duplicate = c.execute('SELECT id FROM app.acceptances WHERE document_sha256=%s', (s['file_sha256'],)).fetchone()
                if duplicate:
                    transition(c,s['id'],s['uploaded_by'],'blocked_duplicate','Previously accepted file bytes')
                    c.execute("UPDATE app.processing_runs SET state='completed',stage='blocked_duplicate',finished_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s",(run['id'],))
                    audit(c,s['id'],'invoice.duplicate_blocked',run=run['id'],details={'acceptance_id':str(duplicate['id'])})
                    return True
            if run['attempt_count'] > 3:
                self.fail(run,'RECOVERY_ATTEMPTS_EXHAUSTED')
                return True
            self.stage(run,'reading_document')
            data = self.storage.download(s['storage_key'])
            if sha256(data).hexdigest() != s['file_sha256']:
                raise ExtractionError('SOURCE_HASH_MISMATCH')
            document = self.reader(data,s['mime_type'])
            self.stage(run,'extracting_fields')
            candidate = self.extractor.extract(document)
            self.stage(run,'validating')
            with self.db.transaction() as c:
                ref, ledger = reference_and_ledger(c,candidate,s['file_sha256'])
            if ref is None or not ref['fresh']:
                self.fail(run,'REFERENCE_STALE_OR_MISSING','reference_hold')
                return True
            decision = evaluate(candidate,document,ref,ledger)
            with self.db.transaction() as c:
                if not self.fence(c,run):
                    return True
                # Same pointer -> stable PO -> submission order as the SQL commit
                # function, including before changing current_revision_id.
                c.execute('SELECT app.lock_processing_context(%s,%s,%s)',(s['id'],decision.po_code,s['uploaded_by']))
                current=c.execute('SELECT * FROM app.submissions WHERE id=%s FOR UPDATE',(s['id'],)).fetchone()
                existing=c.execute('SELECT id FROM app.acceptances WHERE submission_id=%s',(s['id'],)).fetchone()
                if existing or current['status'] in ('rejected','blocked_duplicate','expired'):
                    c.execute("UPDATE app.processing_runs SET state='completed',stage=%s,finished_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s",(current['status'],run['id']))
                    return True
                revision_id, validation_id = save_validation(c,s['id'],run['id'],candidate,document,ref,decision,
                    extractor_metadata={'model_id':self.settings.gemini_model,
                                        'prompt_version':EXTRACTION_PROMPT_VERSION})
                state = 'needs_review'
                if decision.verdict == 'eligible' and decision.acceptance_mode == 'automatic':
                    try:
                        with c.transaction():
                            c.execute('SELECT app.accept_invoice(%s,%s)',(validation_id,s['uploaded_by'])).fetchone()
                        state = 'accepted'
                    except psycopg.Error as e:
                        code = (e.diag.message_primary or 'ACCEPTANCE_RECHECK_FAILED')
                        known = {'DUPLICATE_ACCEPTANCE','INSUFFICIENT_PO_BALANCE','INSUFFICIENT_LINE_QUANTITY','REFERENCE_CHANGED_REVALIDATE','REFERENCE_STALE_OR_MISSING'}
                        if code not in known:
                            raise
                        state = 'blocked_duplicate' if code == 'DUPLICATE_ACCEPTANCE' else 'needs_review'
                        audit(c,s['id'],'acceptance.recheck_held',run=run['id'],details={'code':code})
                elif decision.verdict == 'blocked' and ledger['duplicate']:
                    state = 'blocked_duplicate'
                if state != 'accepted':
                    transition(c,s['id'],s['uploaded_by'],state,decision.summary)
                c.execute("UPDATE app.processing_runs SET state='completed',stage=%s,finished_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s",(state,run['id']))
                audit(c,s['id'],'validation.completed',run=run['id'],details={'validation_id':str(validation_id),'state':state})
        except ExtractionError as e:
            self.fail(run,e.code)
        except Exception:
            self.fail(run,'PROCESSING_UNAVAILABLE')
        return True

    def publish_once(self):
        token = uuid4()
        with self.db.transaction() as c:
            task = c.execute('''WITH next AS (SELECT id FROM app.export_tasks WHERE
                ((status IN ('pending','failed') AND available_at<=now() AND attempt_count<5)
                  OR (status='publishing' AND lease_until<now())) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                UPDATE app.export_tasks t SET status='publishing',attempt_count=t.attempt_count+1,
                lease_token=%s,lease_until=now()+interval '5 minutes' FROM next WHERE t.id=next.id RETURNING t.*''',(token,)).fetchone()
            if not task:
                return False
            acceptance = c.execute('''SELECT a.*,v.source_spreadsheet_id FROM app.acceptances a
                JOIN app.reference_versions v ON v.id=a.reference_version_id WHERE a.id=%s''',(task['acceptance_id'],)).fetchone()
            acceptance['sheet_row'] = task['sheet_row']
        try:
            sheet_range = self.publisher_factory(acceptance['source_spreadsheet_id']).publish(acceptance)
            with self.db.transaction() as c:
                updated = c.execute("""UPDATE app.export_tasks SET status='published',sheet_range=%s,published_at=now(),
                    lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=%s AND lease_token=%s RETURNING id""",(sheet_range,task['id'],token)).fetchone()
                if updated:
                    audit(c,acceptance['submission_id'],'spreadsheet.published',details={'acceptance_id':str(acceptance['id']),'sheet_row':task['sheet_row']})
        except Exception as e:
            conflict = isinstance(e,PublicationConflict)
            with self.db.transaction() as c:
                c.execute('''UPDATE app.export_tasks SET status=%s,last_error=%s,available_at=now()+interval '60 seconds',
                    lease_token=NULL,lease_until=NULL WHERE id=%s AND lease_token=%s''',
                    ('reconciliation_required' if conflict else 'failed','SHEET_ROW_CONFLICT' if conflict else 'SHEETS_UNAVAILABLE',task['id'],token))
        return True

    def expire_documents(self):
        with self.db.transaction() as c:
            rows = c.execute('''SELECT s.* FROM app.submissions s WHERE document_expires_at<=now()
                AND document_deleted_at IS NULL AND storage_key IS NOT NULL
                AND NOT EXISTS(SELECT 1 FROM app.processing_runs r WHERE r.submission_id=s.id AND r.state='running' AND r.lease_until>now()) LIMIT 10''').fetchall()
        for s in rows:
            self.storage.delete(s['storage_key'])
            with self.db.transaction() as c:
                c.execute('UPDATE app.submissions SET document_deleted_at=now(),updated_at=now() WHERE id=%s',(s['id'],))
                if s['status'] in ('received','processing','needs_review','reference_hold','processing_failed'):
                    transition(c,s['id'],s['uploaded_by'],'expired','Original retention period ended')
                    c.execute("UPDATE app.processing_runs SET state='failed',stage='expired',error_code='SOURCE_DOCUMENT_EXPIRED',finished_at=now() WHERE submission_id=%s AND state='queued'",(s['id'],))
                audit(c,s['id'],'source.expired')


class Workers:
    def __init__(self,pipeline):
        self.pipeline=pipeline
        self.stop_event=threading.Event()
        self.threads=[]
        self.errors={'processing':None,'publication':None}

    def start(self):
        for name in ('processing','publication'):
            t=threading.Thread(target=self.loop,args=(name,),daemon=True,name='invoice-'+name)
            t.start();self.threads.append(t)

    def loop(self,name):
        ticks=0
        while not self.stop_event.is_set():
            try:
                if name=='processing':
                    if ticks%60==0:
                        self.pipeline.recover_intake();self.pipeline.expire_documents()
                    busy=self.pipeline.process_once()
                else:
                    busy=self.pipeline.publish_once()
                self.errors[name]=None
            except Exception:
                self.errors[name]='WORKER_DEPENDENCY_UNAVAILABLE';busy=False
            ticks+=1
            self.stop_event.wait(0.1 if busy else 2)

    def stop(self):
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=1)

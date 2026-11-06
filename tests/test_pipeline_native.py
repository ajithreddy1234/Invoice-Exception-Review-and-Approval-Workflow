"""Real-Postgres pipeline/API tests, with explicitly simulated external services.

Only scripts/native-api.mjs enables the destructive fixture. Source evidence is
read from actual generated PDFs (including real OCR for the blurred scan). The
extractor is deterministic test data, never a substitute production Gemini path.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from contextlib import contextmanager
import csv
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import os
from pathlib import Path
from threading import Barrier, Event
import time
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pytest

from app.auth import COOKIE
from app.config import Settings
from app.db import Database
from app.extraction import MAX_BYTES, CandidateField, CandidateLine, InvoiceCandidate, Source, read_document
from app.main import create_app
from app.processing import Pipeline
from app.procurement import import_reference, parse_reference
from app.rules import CHECK_CODES, evaluate

URL = os.getenv('INVOICE_TEST_DATABASE_URL')
ISOLATED = os.getenv('INVOICE_TEST_ISOLATED') == '1'
pytestmark = pytest.mark.skipif(not URL or not ISOLATED,
                               reason='Use scripts/native-api.mjs: disposable local Postgres only')
ADMIN = UUID('11111111-1111-4111-8111-111111111111')
USER = UUID('22222222-2222-4222-8222-222222222222')
OTHER = UUID('33333333-3333-4333-8333-333333333333')
ORIGIN = 'http://127.0.0.1:8000'
FIXTURES = Path(__file__).resolve().parent / 'fixtures/pdfs'


def field(value, quote=None):
    return CandidateField(value=value, source=Source(page=1,quote=quote or value) if value else None)


def money(value):
    return field(str(value),f'{Decimal(value):,.2f}') if value is not None else field(None)


def candidate(number='INV-1001',po='PO-FULL',description='Office support package',
              quantity='10',total='10000.00'):
    line=CandidateLine(description=field(description),quantity=field(quantity),unit=field('hour'),
        unit_price=money('1000.00'),net_amount=money(total),tax_amount=field(None),gross_amount=field(None))
    return InvoiceCandidate(vendor_name=field('Acme Services Pvt Ltd'),invoice_number=field(number),
        invoice_date=field('2026-10-31'),po_reference=field(po),currency=field('INR'),
        subtotal_net=money(total),tax_amount=money('0.00'),
        total_gross=field(total,'TOTAL PAYABLE\nINR '+f'{Decimal(total):,.2f}'),
        tax_presentation='none',line_items=[line],uncertainties=[])


def sample():
    directory=Path(__file__).resolve().parent/'reference_data'
    return parse_reference({p.stem:list(csv.reader(p.open())) for p in directory.glob('*.csv')})


class MemoryStorage:
    def __init__(self):self.objects={};self.uploads=[];self.downloads=[]
    def upload(self,key,data,mime):
        self.uploads.append(key)
        if key in self.objects and self.objects[key] != data:raise AssertionError('object overwritten')
        self.objects[key]=data
    def download(self,key):self.downloads.append(key);return self.objects[key]
    def delete(self,key):self.objects.pop(key,None)


class TestExtractor:
    __test__=False
    def __init__(self):self.candidate=candidate();self.documents=[]
    def extract(self,document):
        self.documents.append(document)
        return self.candidate.model_copy(deep=True)


class FixedPublisher:
    def __init__(self):self.rows={};self.calls=[];self.writes=0;self.timeout_once=False
    def publish(self,acceptance):
        row=acceptance['sheet_row'];key=str(acceptance['id']);self.calls.append((row,key))
        assert isinstance(row,int) and row>=2
        if row in self.rows:assert self.rows[row]==key
        else:self.rows[row]=key;self.writes+=1
        if self.timeout_once:self.timeout_once=False;raise TimeoutError('simulated committed PUT timeout')
        return f"'AcceptedInvoices'!A{row}:K{row}"


class NativeAuth:
    def user_id(self,token):
        ids={'user':USER,'other':OTHER,'admin':ADMIN}
        if token not in ids:raise HTTPException(401,'SESSION_EXPIRED')
        return ids[token]


@pytest.fixture
def system():
    assert ISOLATED and urlsplit(URL).hostname in ('127.0.0.1','localhost'), 'Refusing destructive cloud test'
    owner=psycopg.connect(URL,row_factory=dict_row)
    owner.execute('''TRUNCATE app.acceptances,app.export_tasks,app.validation_lines,app.validation_results,
        app.processing_runs,app.invoice_revisions,app.review_actions,app.submissions,app.audit_events
        RESTART IDENTITY CASCADE''')
    owner.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING',(OTHER,))
    owner.execute("INSERT INTO app.profiles(user_id,display_name,role) VALUES(%s,'Other tenant','user') ON CONFLICT DO NOTHING",(OTHER,))
    owner.commit()
    db=Database(URL)
    with db.transaction() as conn:version=import_reference(conn,sample(),'native-pipeline-sheet',str(ADMIN))
    config=Settings(_env_file=None,app_origin=ORIGIN,cookie_secure=False,database_url=URL,
        supabase_url='',supabase_publishable_key='',google_application_credentials='',google_spreadsheet_id='',
        gemini_api_key='',gemini_model='',auto_import_on_startup=False,worker_enabled=False)
    storage=MemoryStorage();extractor=TestExtractor();publisher=FixedPublisher();reads=[]
    def reader(data,mime):reads.append(sha256(data).hexdigest());return read_document(data,mime)
    pipeline=Pipeline(db,config,storage,extractor=extractor,reader=reader,publisher_factory=lambda _:publisher)
    app=create_app(config,db=db,auth=NativeAuth(),storage=storage,pipeline=pipeline)
    with TestClient(app) as client:
        client.cookies.set(COOKIE,'user')
        yield {'db':db,'owner':owner,'client':client,'pipeline':pipeline,'extractor':extractor,
               'storage':storage,'publisher':publisher,'reads':reads,'version':version}
    db.close()
    owner.close()


def upload(system,filename='happy_full.pdf',request_key=None,data=None,display_name=None):
    if data is None:data=(FIXTURES/filename).read_bytes()
    response=system['client'].post('/api/submissions',headers={'Origin':ORIGIN},
        data={'request_key':str(request_key or uuid4())},files={'file':(display_name or filename,data,'application/pdf')})
    assert response.status_code==202,response.text
    return UUID(response.json()['id']),response


def state(system,sid):
    response=system['client'].get(f'/api/submissions/{sid}')
    assert response.status_code==200,response.text
    return response.json()


def scalar(system,sql,params=None):
    with system['db'].transaction() as conn:return next(iter(conn.execute(sql,params).fetchone().values()))


def test_recorded_decision_timing_policy_and_historical_reference(system):
    sid,_=upload(system);system['pipeline'].process_once();data=state(system,sid)
    assert data['decision']['commitment']=='recorded' and data['decision']['report']=='pending'
    assert data['policy']['arithmetic_tolerance_minor']==100
    assert data['policy']['reference_version_id']==str(system['version'])
    stages=data['timing']['stages']
    assert [r['stage'] for r in stages]==['reading_document','extracting_fields','validating']
    assert all(r['seconds'] is not None and r['seconds']>=0 for r in stages)
    assert data['timing']['queue_seconds']>=0 and data['timing']['processing_seconds']>=0
    tabs={p.stem:list(csv.reader(p.open())) for p in (Path(__file__).parent/'reference_data').glob('*.csv')}
    tabs['Rules'][1][2]='0.00'
    with system['db'].transaction() as c:import_reference(c,parse_reference(tabs),'new-policy-version',str(ADMIN))
    after=state(system,sid)
    assert after['reference']['is_active'] is False
    assert after['policy']['arithmetic_tolerance_minor']==100  # not today's rule
    assert after['decision']['reason_code']=='ACCEPTED'  # history is not undone


def test_duplicate_link_is_ownership_scoped_and_never_commits_twice(system):
    sid,_=upload(system);system['pipeline'].process_once()
    original_rid=state(system,sid)['revision']['id']
    duplicate,_=upload(system);system['pipeline'].process_once();data=state(system,duplicate)
    assert data['duplicate_record']['submission_id']==str(sid)
    assert data['decision']['reason_code']=='DUPLICATE' and data['timing']['stages']==[]
    system['client'].cookies.set(COOKIE,'other')
    other,_=upload(system);system['pipeline'].process_once();data=state(system,other)
    assert data['duplicate_record'] is None and data['decision']['commitment']=='not_recorded'
    assert system['client'].get(f'/api/submissions/{sid}/revisions/{original_rid}').status_code==404
    system['client'].cookies.set(COOKIE,'admin')
    assert state(system,other)['duplicate_record']['submission_id']==str(sid)
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1


def test_revision_readback_cannot_cross_invoice_or_uploader(system):
    sid,_=upload(system);system['pipeline'].process_once();data=state(system,sid);rid=data['revision']['id']
    endpoint=f'/api/submissions/{sid}/revisions/{rid}'
    record=system['client'].get(endpoint);assert record.status_code==200
    assert record.json()['previous_revision'] is None and record.json()['validation']['id']==data['validation']['id']
    another,_=upload(system)
    assert system['client'].get(f'/api/submissions/{another}/revisions/{rid}').status_code==404
    system['client'].cookies.set(COOKIE,'other');assert system['client'].get(endpoint).status_code==404
    system['client'].cookies.set(COOKIE,'admin');assert system['client'].get(endpoint).status_code==200


def test_workspace_metrics_are_database_aggregates_and_role_scoped(system):
    sid,_=upload(system);system['pipeline'].process_once()
    owner=system['owner']
    owner.execute("UPDATE app.processing_runs SET started_at='2026-11-01T10:00:00Z',finished_at='2026-11-01T10:00:10Z' WHERE submission_id=%s",(sid,))
    for vendor,seconds,status in [('Beta Consulting Pvt Ltd',90,'needs_review'),('Acme Services Pvt Ltd',1,'rejected')]:
        item=uuid4()
        owner.execute('''INSERT INTO app.submissions(id,uploaded_by,request_key,original_filename,mime_type,file_sha256,byte_size,status)
          VALUES(%s,%s,%s,'historical.pdf','application/pdf',%s,10,%s)''',(item,USER,uuid4(),sha256(str(item).encode()).hexdigest(),status))
        revision=owner.execute('''INSERT INTO app.invoice_revisions(submission_id,revision_no,kind,vendor_name,currency)
          VALUES(%s,1,'extraction',%s,'INR') RETURNING id''',(item,vendor)).fetchone()['id']
        owner.execute('UPDATE app.submissions SET current_revision_id=%s WHERE id=%s',(revision,item))
        owner.execute('''INSERT INTO app.processing_runs(submission_id,pipeline_version,state,stage,started_at,finished_at)
          VALUES(%s,'historical','completed','needs_review','2026-11-01T10:00:00Z','2026-11-01T10:00:00Z'::timestamptz+%s*interval '1 second')''',(item,seconds))
    owner.commit()
    w=system['client'].get('/api/workspace').json();groups=w['company_totals']
    assert sum(x['outcome_count'] for x in groups)==3 and sum(x['straight_through_count'] for x in groups)==1
    assert next(x for x in w['timing_groups'] if x['all_vendors'])['median_seconds']==10
    assert next(x for x in w['timing_groups'] if not x['all_vendors'] and x['vendor_code']=='V-ACME')['median_seconds']==5.5
    assert sum(x['rejected_count'] for x in groups)==1
    system['client'].cookies.set(COOKIE,'other');other=system['client'].get('/api/workspace').json()
    assert other['total_count']==0 and other['timing_groups']==[]
    system['client'].cookies.set(COOKIE,'admin');assert system['client'].get('/api/workspace').json()['total_count']==3


def test_user_requested_recovery_is_not_counted_as_straight_through(system):
    from app.extraction import ExtractionError
    sid,_=upload(system)
    with patch.object(system['extractor'],'extract',side_effect=ExtractionError('EXTRACTION_PROVIDER_BUSY')):
        system['pipeline'].process_once()
    assert state(system,sid)['submission']['status']=='processing_failed'
    assert system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN}).status_code==202
    system['pipeline'].process_once();assert state(system,sid)['acceptance']['method']=='automatic'
    groups=system['client'].get('/api/workspace').json()['company_totals']
    assert sum(x['straight_through_count'] for x in groups)==0


def test_upload_request_idempotence_and_reused_key_conflict(system):
    key=uuid4();sid,_=upload(system,request_key=key)
    same,_=upload(system,request_key=key)
    assert same==sid
    assert scalar(system,'SELECT count(*) FROM app.submissions')==1
    assert scalar(system,'SELECT count(*) FROM app.processing_runs')==1
    assert len(system['storage'].objects)==1
    response=system['client'].post('/api/submissions',headers={'Origin':ORIGIN},
        data={'request_key':str(key)},files={'file':('different.pdf',(FIXTURES/'split_6000.pdf').read_bytes(),'application/pdf')})
    assert response.status_code==409
    assert response.json()['detail']=='IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_FILE'


def test_offline_packs_import_without_reset_and_track_commitments_independently(system):
    from tools.demo_packs import catalog,ASSETS
    packs=catalog();directory=FIXTURES.parent.parent/'reference_data'
    raw={p.stem:list(csv.reader(p.open())) for p in directory.glob('*.csv')}
    for pack in packs:
        for name,records in pack['reference_rows'].items():
            raw[name]+=[[row[key] for key in raw[name][0]] for row in records]
    with system['db'].transaction() as conn:
        import_reference(conn,parse_reference(raw),'native-demo-packs',str(ADMIN))
    assert scalar(system,"SELECT count(*) FROM app.reference_pos WHERE reference_version_id=(SELECT active_reference_version_id FROM app.runtime_state WHERE singleton) AND po_code LIKE 'PO-DEMO-%%'")==sum(len(p['reference_rows']['PurchaseOrders']) for p in packs)
    b=next(p for p in packs if p['pack']=='B');entry=b['fixtures'][0]
    system['extractor'].candidate=candidate(number=entry['invoice_number'],po=entry['po_code'],description=b['reference_rows']['POLines'][0]['description'])
    sid,_=upload(system,data=(ASSETS/'B'/entry['file']).read_bytes())
    system['pipeline'].process_once();assert state(system,sid)['submission']['status']=='accepted'
    assert scalar(system,"SELECT sum(amount_minor) FROM app.acceptances WHERE po_code LIKE 'PO-DEMO-B-%%'")==1000000
    assert scalar(system,"SELECT count(*) FROM app.acceptances WHERE po_code LIKE 'PO-DEMO-C-%%'")==0
    again,_=upload(system,data=(ASSETS/'B'/b['fixtures'][1]['file']).read_bytes())
    system['pipeline'].process_once();assert state(system,again)['submission']['status']=='blocked_duplicate'
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1


def test_demo_ambiguous_candidates_are_isolated_to_the_selected_pack(system):
    from tools.demo_packs import catalog,ASSETS
    directory=FIXTURES.parent.parent/'reference_data'
    raw={p.stem:list(csv.reader(p.open())) for p in directory.glob('*.csv')}
    for p in catalog():
        for name,records in p['reference_rows'].items():raw[name]+=[[row[key] for key in raw[name][0]] for row in records]
    with system['db'].transaction() as conn:import_reference(conn,parse_reference(raw),'native-demo-packs',str(ADMIN))
    p=next(p for p in catalog() if p['pack']=='C');entry=p['fixtures'][5]
    system['extractor'].candidate=candidate(number=entry['invoice_number'],po=None,
        description=p['reference_rows']['POLines'][3]['description'],quantity='5',total='5000.00')
    sid,_=upload(system,data=(ASSETS/'C'/entry['file']).read_bytes());system['pipeline'].process_once()
    result=state(system,sid)
    assert result['submission']['status']=='needs_review'
    assert {row['po_code'] for row in result['validation']['po_candidates']}=={'PO-DEMO-C-AMBIG-A','PO-DEMO-C-AMBIG-B'}
    assert scalar(system,'SELECT count(*) FROM app.submissions')==1


def test_happy_path_atomically_records_ledger_and_outbox(system):
    sid,_=upload(system)
    assert system['pipeline'].process_once() is True
    result=state(system,sid)
    assert result['submission']['status']=='accepted',result
    assert result['run']['state']=='completed'
    assert result['acceptance']['amount_minor']==1000000
    assert result['publication']['status']=='pending'
    evidence=result['revision']['evidence']
    assert evidence['issues']==[]
    assert evidence['derived_allocation']['net_minor']==1000000
    assert evidence['derived_allocation']['gross_minor']==1000000
    assert 'never an inferred payable' in evidence['derived_allocation']['basis']
    assert [check['code'] for check in result['validation']['checks']]==list(CHECK_CODES)
    assert all(check['status']=='pass' for check in result['validation']['checks'])
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1
    assert 'storage_key' not in result['submission'] and 'lease_token' not in result['run']
    assert system['pipeline'].process_once() is False


def test_exact_file_duplicate_skips_extraction_and_reexport_identity_blocks(system):
    first,_=upload(system);system['pipeline'].process_once()
    duplicate,_=upload(system,display_name='unrelated-name.pdf');system['pipeline'].process_once()
    assert state(system,first)['submission']['status']=='accepted'
    assert state(system,duplicate)['submission']['status']=='blocked_duplicate'
    assert len(system['extractor'].documents)==1 and len(system['reads'])==1
    reexport,_=upload(system,'duplicate_reexported.pdf');system['pipeline'].process_once()
    assert state(system,reexport)['submission']['status']=='blocked_duplicate'
    assert len(system['extractor'].documents)==2
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1


def test_partial_six_hours_then_four_point_five_is_held(system):
    system['extractor'].candidate=candidate('INV-PART-01','PO-PARTIAL','Consulting services','6','6000.00')
    first,_=upload(system,'split_6000.pdf');system['pipeline'].process_once()
    assert state(system,first)['submission']['status']=='accepted'
    system['extractor'].candidate=candidate('INV-PART-03','PO-PARTIAL','Consulting services','4.5','4500.00')
    second,_=upload(system,'split_4500.pdf');system['pipeline'].process_once()
    held=state(system,second)
    assert held['submission']['status']=='needs_review',held
    assert next(check for check in held['validation']['checks'] if check['code']=='po_balance')['status']=='review'
    assert scalar(system,'SELECT sum(amount_minor) FROM app.acceptances')==600000
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1


def test_blurred_pdf_real_ocr_missing_payable_goes_to_review(system):
    value=candidate('INV-SCAN-01');value.total_gross=field(None)
    system['extractor'].candidate=value
    sid,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    result=state(system,sid)
    assert result['submission']['status']=='needs_review',result
    assert 'total_gross' in result['revision']['unresolved_critical_fields']
    assert system['extractor'].documents[0].pages[0].method=='ocr'
    assert result['acceptance'] is None and result['publication'] is None
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==0


def test_expired_processing_lease_recovered_and_old_worker_fenced(system):
    sid,_=upload(system);abandoned=system['pipeline'].claim()
    assert abandoned['attempt_count']==1
    system['owner'].execute("UPDATE app.processing_runs SET lease_until=now()-interval '1 minute' WHERE id=%s",(abandoned['id'],));system['owner'].commit()
    system['pipeline'].process_once()
    result=state(system,sid)
    assert result['submission']['status']=='accepted' and result['run']['attempt_count']==2
    with pytest.raises(RuntimeError,match='LEASE_LOST'):system['pipeline'].stage(abandoned,'stale-worker-stage')
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1


def test_defensive_recovery_after_acceptance_does_not_extract_or_accept_twice(system):
    sid,_=upload(system);system['pipeline'].process_once()
    before=state(system,sid)['acceptance']['id']
    # Defensive recovery for an anomalous/inherited post-commit running run;
    # ordinary acceptance and run completion already share one transaction.
    system['owner'].execute("UPDATE app.processing_runs SET state='running',lease_token=%s,lease_until=now()-interval '1 minute' WHERE submission_id=%s",(uuid4(),sid));system['owner'].commit()
    assert system['pipeline'].process_once() is True
    after=state(system,sid)
    assert after['acceptance']['id']==before and after['run']['state']=='completed'
    assert len(system['extractor'].documents)==1
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1


def test_publication_timeout_retries_reserved_row_without_double_commit(system):
    sid,_=upload(system);system['pipeline'].process_once()
    system['publisher'].timeout_once=True
    assert system['pipeline'].publish_once() is True
    result=state(system,sid)
    assert result['submission']['status']=='accepted' and result['publication']['status']=='failed'
    assert system['publisher'].writes==1
    system['owner'].execute("UPDATE app.export_tasks SET available_at=now() WHERE status='failed'");system['owner'].commit()
    system['pipeline'].publish_once()
    result=state(system,sid)
    assert result['publication']['status']=='published'
    assert len(system['publisher'].rows)==1 and system['publisher'].writes==1
    assert system['publisher'].calls[0]==system['publisher'].calls[1]
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1


def test_two_native_connections_only_one_worker_claims_run(system):
    sid,_=upload(system);barrier=Barrier(2)
    def claim():barrier.wait(timeout=5);return system['pipeline'].claim()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:claim(),range(2)))
    assert sum(result is not None for result in results)==1
    assert scalar(system,'SELECT attempt_count FROM app.processing_runs WHERE submission_id=%s',(sid,))==1


def test_reference_changes_after_rules_acceptance_recheck_holds(system):
    sid,_=upload(system)
    def changed(candidate,document,reference,ledger):
        decision=evaluate(candidate,document,reference,ledger)
        assert decision.verdict=='eligible'
        with system['db'].transaction() as conn:import_reference(conn,sample(),'native-pipeline-sheet',str(ADMIN))
        return decision
    with patch('app.processing.evaluate',side_effect=changed):system['pipeline'].process_once()
    result=state(system,sid)
    assert result['submission']['status']=='needs_review',result
    assert result['acceptance'] is None
    assert any(event['event_type']=='acceptance.recheck_held' and event['details']['code']=='REFERENCE_CHANGED_REVALIDATE'
               for event in result['audit'])
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==0


def test_tenant_ownership_returns_404_and_admin_can_read_source(system):
    sid,_=upload(system);client=system['client']
    client.cookies.set(COOKIE,'other')
    for suffix in ('','/document'):
        assert client.get(f'/api/submissions/{sid}{suffix}').status_code==404
    assert client.post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN}).status_code==404
    assert client.get('/api/submissions').json()['items']==[]
    client.cookies.set(COOKIE,'admin')
    assert client.get(f'/api/submissions/{sid}').status_code==200
    response=client.get(f'/api/submissions/{sid}/document')
    assert response.status_code==200 and response.content==(FIXTURES/'happy_full.pdf').read_bytes()
    client.cookies.clear()
    assert client.get(f'/api/submissions/{sid}/document').status_code==401


def test_two_eligible_six_thousand_invoices_race_atomic_balance_recheck(system):
    source_bytes=[(FIXTURES/name).read_bytes() for name in ('race_a_6000.pdf','race_b_6000.pdf')]
    documents={sha256(data).hexdigest():read_document(data,'application/pdf') for data in source_bytes}
    system['pipeline'].reader=lambda data,mime:documents[sha256(data).hexdigest()].model_copy(deep=True)
    class RaceExtractor:
        def extract(self,document):
            text=document.pages[0].text
            number='INV-RACE-01' if 'INV-RACE-01' in text else 'INV-RACE-02'
            assert number in text
            return candidate(number,'PO-RACE','Load-test consulting services','6','6000.00')
    system['pipeline'].extractor=RaceExtractor()
    first,_=upload(system,'race_a_6000.pdf');second,_=upload(system,'race_b_6000.pdf')
    barrier=Barrier(2)
    def simultaneous(candidate,document,reference,ledger):
        decision=evaluate(candidate,document,reference,ledger)
        assert decision.verdict=='eligible',decision.checks
        barrier.wait(timeout=10)
        return decision
    with patch('app.processing.evaluate',side_effect=simultaneous):
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert all(pool.map(lambda _:system['pipeline'].process_once(),range(2)))
    results=[state(system,sid) for sid in (first,second)]
    assert sorted(result['submission']['status'] for result in results)==['accepted','needs_review'],results
    assert scalar(system,'SELECT sum(amount_minor) FROM app.acceptances')==600000
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1
    held=next(result for result in results if result['submission']['status']=='needs_review')
    assert any(event['event_type']=='acceptance.recheck_held' for event in held['audit'])


def test_missing_source_after_failed_intake_can_resume_same_upload_key(system):
    key=uuid4();data=(FIXTURES/'happy_full.pdf').read_bytes()
    with patch.object(system['storage'],'upload',side_effect=TimeoutError('simulated write never committed')):
        response=system['client'].post('/api/submissions',headers={'Origin':ORIGIN},
            data={'request_key':str(key)},files={'file':('original.pdf',data,'application/pdf')})
    assert response.status_code==503,response.text
    sid=UUID(response.json()['detail']['submission_id'])
    system['owner'].execute("UPDATE app.submissions SET created_at=now()-interval '1 minute' WHERE id=%s",(sid,))
    system['owner'].commit()
    system['pipeline'].recover_intake();system['pipeline'].process_once()
    # The user must be able to recover a never-stored original after the intake
    # sweeper ran, by sending exactly the same request key and original bytes.
    replay,_=upload(system,request_key=key,data=data)
    assert replay==sid
    system['pipeline'].process_once()
    result=state(system,sid)
    assert result['submission']['status']=='accepted',result
    assert scalar(system,'SELECT count(*) FROM app.submissions')==1
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1


def test_ordered_lock_helper_preserves_direct_mutation_denial(system):
    sid,_=upload(system)
    with system['db'].transaction() as conn:
        conn.execute('SELECT app.lock_processing_context(%s,%s,%s)',(sid,'PO-FULL',USER))
        for statement in ("UPDATE app.runtime_state SET active_reference_version_id=NULL WHERE false",
                          "UPDATE app.po_accounts SET vendor_code=vendor_code WHERE false",
                          "UPDATE app.submissions SET status='accepted' WHERE false"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():conn.execute(statement)
        with pytest.raises(psycopg.Error,match='SUBMISSION_NOT_FOUND_OR_FORBIDDEN'):
            with conn.transaction():
                conn.execute('SELECT app.lock_processing_context(%s,%s,%s)',(sid,'PO-FULL',OTHER))


def test_admin_accept_vs_reprocessing_uses_same_lock_order_without_deadlock(system):
    original=sample()
    no_auto=replace(original,rules=tuple(replace(rule,auto_accept_enabled=False) for rule in original.rules))
    with system['db'].transaction() as conn:import_reference(conn,no_auto,'native-pipeline-sheet',str(ADMIN))
    sid,_=upload(system);system['pipeline'].process_once()
    before=state(system,sid)
    assert before['submission']['status']=='needs_review' and before['validation']['verdict']=='eligible'
    response=system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN})
    assert response.status_code==202,response.text
    # Hold the PO in a third owner connection, so admin SQL and the worker's
    # final transaction overlap as real lock waiters on separate connections.
    owner=system['owner']
    owner.execute("SELECT po_code FROM app.po_accounts WHERE po_code='PO-FULL' FOR UPDATE")
    evaluated=Event();resume=Event();pool=ThreadPoolExecutor(max_workers=2)
    admin_client=TestClient(system['client'].app);admin_client.cookies.set(COOKIE,'admin')
    def paused(candidate,document,reference,ledger):
        result=evaluate(candidate,document,reference,ledger);evaluated.set()
        assert resume.wait(timeout=5),'test did not release evaluated worker'
        return result
    def waiting_count():
        owner.execute('SELECT pg_stat_clear_snapshot()')
        return owner.execute("""SELECT count(*) AS n FROM pg_stat_activity WHERE
            datname=current_database() AND wait_event_type='Lock' AND
            (query LIKE '%app.accept_invoice%' OR query LIKE '%app.lock_processing_context%')""").fetchone()['n']
    def wait_for(count):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            if waiting_count()>=count:return
            time.sleep(.02)
        pytest.fail(f'Expected {count} independent native lock waiters')
    try:
        with patch('app.processing.evaluate',side_effect=paused):
            worker=pool.submit(system['pipeline'].process_once)
            assert evaluated.wait(timeout=4),'worker did not reach evaluation'
            admin=pool.submit(lambda:admin_client.post(f'/api/admin/submissions/{sid}/accept',
                headers={'Origin':ORIGIN},json={'reason':'Reviewed original source and authorized invoice'}))
            wait_for(1)
            resume.set();wait_for(2)
            owner.commit()
            accepted=admin.result(timeout=5)
            assert accepted.status_code==200,accepted.text
            assert worker.result(timeout=5) is True
    finally:
        resume.set();owner.rollback();pool.shutdown(wait=True);admin_client.close()
    result=state(system,sid)
    assert result['submission']['status']=='accepted',result
    assert result['submission']['current_revision_id']==before['submission']['current_revision_id']
    assert result['run']['state']=='completed'
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1
    assert scalar(system,'SELECT count(*) FROM app.validation_results')==1
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1


def test_oversized_native_upload_is_413_before_storage_or_ledger(system):
    data=b'%PDF-'+b'x'*(MAX_BYTES-4)
    assert len(data)==MAX_BYTES+1
    response=system['client'].post('/api/submissions',headers={'Origin':ORIGIN},
        data={'request_key':str(uuid4())},files={'file':('too-large.pdf',data,'application/pdf')})
    assert response.status_code==413,response.text
    assert not system['storage'].uploads
    assert scalar(system,'SELECT count(*) FROM app.submissions')==0


def test_bad_file_signature_is_422_before_storage_or_ledger(system):
    response=system['client'].post('/api/submissions',headers={'Origin':ORIGIN},
        data={'request_key':str(uuid4())},files={'file':('invoice.pdf',b'<html>not a PDF</html>','application/pdf')})
    assert response.status_code==422,response.text
    assert response.json()['detail']=='UNSUPPORTED_OR_INVALID_FILE'
    assert not system['storage'].uploads
    assert scalar(system,'SELECT count(*) FROM app.submissions')==0


def test_upload_requires_origin_even_with_valid_authenticated_cookie(system):
    response=system['client'].post('/api/submissions',data={'request_key':str(uuid4())},
        files={'file':('invoice.pdf',(FIXTURES/'happy_full.pdf').read_bytes(),'application/pdf')})
    assert response.status_code==403,response.text
    assert response.json()['detail']=='ORIGIN_REJECTED'
    assert not system['storage'].uploads
    assert scalar(system,'SELECT count(*) FROM app.submissions')==0


def test_streaming_multipart_total_body_cap_is_413(system):
    # Direct ASGI receives real 64KiB chunks; TestClient/httpx can coalesce a
    # generator before ASGI, which would not prove bounded streaming behavior.
    boundary='native-body-cap'
    prefix=(f'--{boundary}\r\nContent-Disposition: form-data; name="request_key"\r\n\r\n{uuid4()}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
            'Content-Type: application/pdf\r\n\r\n').encode()
    def chunks():
        yield prefix+b'%PDF-'
        remaining=MAX_BYTES+262144+1024
        chunk=b'x'*65536
        while remaining:
            size=min(len(chunk),remaining);yield chunk[:size];remaining-=size
        yield f'\r\n--{boundary}--\r\n'.encode()
    source=iter(chunks());messages=[];received=0
    scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
        'method':'POST','scheme':'http','path':'/api/submissions','raw_path':b'/api/submissions',
        'query_string':b'','root_path':'','client':('127.0.0.1',12345),'server':('testserver',80),
        'headers':[(b'host',b'testserver'),(b'origin',ORIGIN.encode()),
                   (b'cookie',(COOKIE+'=user').encode()),
                   (b'content-type',f'multipart/form-data; boundary={boundary}'.encode())]}
    async def receive():
        nonlocal received
        try:
            chunk=next(source);received+=len(chunk)
            return {'type':'http.request','body':chunk,'more_body':True}
        except StopIteration:return {'type':'http.request','body':b'','more_body':False}
    async def send(message):messages.append(message)
    asyncio.run(system['client'].app(scope,receive,send))
    starts=[message for message in messages if message['type']=='http.response.start']
    body=b''.join(message.get('body',b'') for message in messages if message['type']=='http.response.body')
    assert len(starts)==1 and starts[0]['status']==413,(starts,body)
    assert received<=MAX_BYTES+262144+65536
    assert not system['storage'].uploads
    assert scalar(system,'SELECT count(*) FROM app.submissions')==0


def test_repeated_admin_accept_returns_actual_published_outbox_status(system):
    sid,_=upload(system);system['pipeline'].process_once();system['pipeline'].publish_once()
    before=state(system,sid)
    assert before['publication']['status']=='published'
    system['client'].cookies.set(COOKIE,'admin')
    response=system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},
        json={'reason':'Reviewer repeats a previously completed acceptance'})
    assert response.status_code==200,response.text
    assert response.json()['acceptance_id']==before['acceptance']['id']
    assert response.json()['publication_status']=='published'
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1


def test_retention_removes_sources_without_changing_ledger_or_accepting_expired_work(system):
    accepted,_=upload(system);system['pipeline'].process_once()
    pending,_=upload(system,'split_6000.pdf')
    system['extractor'].candidate=candidate('INV-PART-01','PO-PARTIAL','Consulting services','6','6000.00')
    with system['db'].transaction() as conn:
        keys=conn.execute('SELECT id,storage_key,file_sha256 FROM app.submissions').fetchall()
    assert len(system['storage'].objects)==2
    system['owner'].execute("UPDATE app.submissions SET document_expires_at=now()-interval '1 minute'")
    system['owner'].commit()
    assert system['client'].get(f'/api/submissions/{pending}/document').status_code==410
    system['pipeline'].expire_documents()
    assert not system['storage'].objects
    assert scalar(system,'SELECT count(*) FROM app.submissions WHERE document_deleted_at IS NOT NULL')==2
    assert system['pipeline'].process_once() is False
    assert state(system,pending)['submission']['status']=='expired'
    assert state(system,pending)['run']['error_code']=='SOURCE_DOCUMENT_EXPIRED'
    assert state(system,accepted)['submission']['status']=='accepted'
    assert state(system,pending)['acceptance'] is None
    assert scalar(system,'SELECT sum(amount_minor) FROM app.acceptances')==1000000
    assert scalar(system,'SELECT count(*) FROM app.export_tasks')==1
    for original in keys:
        result=state(system,original['id'])
        assert result['submission']['file_sha256']==original['file_sha256']
        assert system['client'].get(f"/api/submissions/{original['id']}/document").status_code==410


def test_reused_connection_rolls_back_local_role_and_rechecks_changed_grants(system):
    """Connection reuse must never retain elevated/local state or cache safe grants."""
    from app.db import DatabaseUnavailable
    from psycopg.pq import TransactionStatus
    db=system['db'];owner=system['owner']
    with pytest.raises(RuntimeError,match='rollback probe'):
        with db.transaction() as conn:
            assert conn.execute('SELECT current_user AS role').fetchone()['role']=='service_role'
            raise RuntimeError('rollback probe')
    with db._connections().connection() as conn:
        assert conn.info.transaction_status==TransactionStatus.IDLE
        assert conn.execute('SELECT current_user AS role').fetchone()['role']=='postgres'
    owner.execute('GRANT UPDATE(status) ON app.submissions TO service_role');owner.commit()
    try:
        with pytest.raises(DatabaseUnavailable,match='UNSAFE_DATABASE_GRANTS'):
            with db.transaction():pytest.fail('unsafe reused connection reached application SQL')
    finally:
        owner.execute('REVOKE UPDATE(status) ON app.submissions FROM service_role');owner.commit()
    assert db.permission_gate()['forged_status_update']=='denied'


def test_read_batch_is_read_only_rolls_back_errors_and_rechecks_grants(system):
    from app.db import DatabaseUnavailable
    db=system['db'];owner=system['owner']
    assert db.read_one('SELECT current_user AS role')[ 'role']=='service_role'
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        db.read_one("DELETE FROM app.audit_events WHERE false RETURNING id")
    with pytest.raises(psycopg.Error):db.read_one('SELECT missing_column_from_read_batch')
    assert db.read_one('SELECT 42 AS value')['value']==42
    owner.execute('GRANT UPDATE(status) ON app.submissions TO service_role');owner.commit()
    try:
        with pytest.raises(DatabaseUnavailable,match='UNSAFE_DATABASE_GRANTS'):db.read_one('SELECT 1')
    finally:
        owner.execute('REVOKE UPDATE(status) ON app.submissions FROM service_role');owner.commit()
    assert db.read_one('SELECT current_user AS role')['role']=='service_role'


def test_workspace_groups_accepted_review_and_duplicates_without_double_counting(system):
    sid,_=upload(system);system['pipeline'].process_once()
    upload(system,'duplicate_same_renamed.pdf');system['pipeline'].process_once()
    upload(system,'scan_blurred_total.pdf');value=candidate('INV-SCAN-01');value.total_gross=field(None);system['extractor'].candidate=value;system['pipeline'].process_once()
    system['client'].cookies.set(COOKIE,'admin')
    response=system['client'].get('/api/workspace');assert response.status_code==200,response.text
    w=response.json();assert w['scope']=='company' and w['actor']['role']=='admin'
    assert w['total_count']==3 and len(w['items'])==3 and len(w['po_balances'])==8
    assert len(w['vendors'])==3  # includes zero-invoice and unapproved Sheet vendors
    totals=[r for r in w['company_totals'] if r['vendor_code']=='V-ACME' and r['currency']=='INR']
    assert sum(r['accepted_minor'] for r in totals)==1000000
    assert sum(r['review_count'] for r in totals)==1 and sum(r['unreadable_amount_count'] for r in totals)==1
    assert sum(r['accepted_count'] for r in totals)==1
    assert w['status_totals']['blocked_duplicate']==1
    po=next(p for p in w['po_balances'] if p['po_code']=='PO-FULL')
    assert po['accepted_minor']==1000000 and po['remaining_minor']==0
    accepted=next(r for r in w['items'] if r['id']==str(sid))
    assert accepted['invoice_number']=='INV-1001' and accepted['vendor_name']=='Acme Services Pvt Ltd'
    assert all('storage_key' not in r and 'evidence' not in r for r in w['items'])


def test_workspace_ownership_current_role_and_disabled_user_are_enforced(system):
    upload(system);system['pipeline'].process_once()
    client=system['client'];client.cookies.set(COOKIE,'other')
    w=client.get('/api/workspace').json()
    assert w['scope']=='your_invoices' and w['total_count']==0
    assert not w['items'] and not w['company_totals'] and not w['po_balances']
    client.cookies.set(COOKIE,'admin');assert client.get('/api/workspace').json()['total_count']==1
    owner=system['owner'];owner.execute("UPDATE app.profiles SET role='user' WHERE user_id=%s",(ADMIN,));owner.commit()
    try:
        w=client.get('/api/workspace').json();assert w['scope']=='your_invoices' and w['total_count']==0 and not w['po_balances']
    finally:
        owner.execute("UPDATE app.profiles SET role='admin' WHERE user_id=%s",(ADMIN,));owner.commit()
    owner.execute('UPDATE app.profiles SET enabled=false WHERE user_id=%s',(OTHER,));owner.commit()
    try:
        client.cookies.set(COOKIE,'other');assert client.get('/api/workspace').status_code==403
    finally:
        owner.execute('UPDATE app.profiles SET enabled=true WHERE user_id=%s',(OTHER,));owner.commit()
    client.cookies.clear();assert client.get('/api/workspace').status_code==401


def test_workspace_aggregates_cover_records_beyond_the_list_limit(system):
    # No financial rows invented: these are valid unprocessed intake records.
    owner=system['owner']
    owner.execute("""INSERT INTO app.submissions(uploaded_by,request_key,original_filename,mime_type,file_sha256,byte_size)
      SELECT %s,gen_random_uuid(),'list-pagination-probe-'||n||'.pdf','application/pdf',repeat('a',64),20
      FROM generate_series(1,205) n""",(USER,));owner.commit()
    w=system['client'].get('/api/workspace').json()
    assert w['total_count']==205 and len(w['items'])==200 and w['status_totals']['received']==205
    assert sum(r['invoice_count'] for r in w['company_totals'])==205
    assert all(r['vendor_code'] is None and r['accepted_minor']==0 for r in w['company_totals'])


def correction_payload(system,sid,value=None,selected_po=None):
    result=state(system,sid)
    return {'base_revision_id':result['revision']['id'],'candidate':(value or candidate()).model_dump(mode='json'),
            'reason':'Verified each corrected field against the original invoice page', 'selected_po':selected_po}


def test_admin_correction_revalidates_without_model_or_automatic_acceptance(system):
    wrong=candidate();wrong.invoice_date=field('2026-10-30');system['extractor'].candidate=wrong
    sid,_=upload(system);system['pipeline'].process_once();before=state(system,sid)
    assert before['submission']['status']=='needs_review'
    calls=len(system['extractor'].documents);system['client'].cookies.set(COOKIE,'admin')
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=correction_payload(system,sid))
    assert response.status_code==200,response.text
    assert response.json()['verdict']=='eligible' and response.json()['acceptance_mode']=='admin_required'
    result=state(system,sid);assert result['submission']['status']=='needs_review' and result['acceptance'] is None
    assert result['revision']['kind']=='admin_correction' and result['revision']['created_by']==str(ADMIN)
    assert 'Explicit administrator acceptance' in result['validation']['summary']
    assert result['revision']['id']!=before['revision']['id']
    assert len(result['revisions'])==2 and all(c['status']=='pass' for c in result['validation']['checks'])
    assert len(system['extractor'].documents)==calls
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==0
    response=system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},json={'reason':'Reviewed corrected source and authorize this invoice'})
    assert response.status_code==200,response.text
    assert state(system,sid)['acceptance']['method']=='admin'
    # A final accepted invoice can never be rewritten by a correction request.
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=correction_payload(system,sid)).status_code==409


def test_correction_cannot_invent_a_blurred_total_and_document_request_is_in_app(system):
    value=candidate('INV-SCAN-01');value.total_gross=field(None);system['extractor'].candidate=value
    sid,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once();before=state(system,sid)
    system['client'].cookies.set(COOKIE,'admin')
    forged=candidate('INV-SCAN-01')
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=correction_payload(system,sid,forged))
    assert response.status_code==422 and response.json()['detail']['code']=='CORRECTION_SOURCE_NOT_SUPPORTED'
    assert state(system,sid)['revision']['id']==before['revision']['id']
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==0
    response=system['client'].post(f'/api/admin/submissions/{sid}/request-document',headers={'Origin':ORIGIN},json={'reason':'Please upload a clearer invoice with a readable total'})
    assert response.status_code==200 and response.json()['delivery']=='in_app_only'
    assert state(system,sid)['reviews'][0]['action']=='request_document'


def test_correction_rejects_users_stale_revision_and_expired_original(system):
    wrong=candidate();wrong.invoice_date=field('2026-10-30');system['extractor'].candidate=wrong
    sid,_=upload(system);system['pipeline'].process_once();body=correction_payload(system,sid)
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==403
    system['client'].cookies.set(COOKIE,'admin')
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==200
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==409
    system['owner'].execute("UPDATE app.submissions SET document_expires_at=now()-interval '1 second' WHERE id=%s",(sid,));system['owner'].commit()
    body=correction_payload(system,sid)
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==410


def test_ambiguous_po_requires_reasoned_selection_from_exact_candidates(system):
    value=candidate('INV-AMB-01',po=None,description='Website design milestones',quantity='5',total='5000.00')
    system['extractor'].candidate=value;sid,_=upload(system,'ambiguous_no_po.pdf');system['pipeline'].process_once()
    assert state(system,sid)['validation']['po_code'] is None
    system['client'].cookies.set(COOKIE,'admin')
    invalid=correction_payload(system,sid,value,'PO-BETA')
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=invalid).status_code==422
    body=correction_payload(system,sid,value,'PO-AMBIG-A')
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body)
    assert response.status_code==200,response.text
    result=state(system,sid)
    assert result['validation']['po_code']=='PO-AMBIG-A' and result['validation']['verdict']=='eligible'
    assert result['revision']['po_reference'] is None  # never fabricate a printed reference
    assert {r['action'] for r in result['reviews']}=={'select_po','correct_fields'}
    assert system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},json={'reason':'Verified candidate PO against the procurement context'}).status_code==200


def test_private_preview_handles_pdf_images_ownership_and_retention(system):
    client=system['client']
    for filename in ['happy_full.pdf','scan_clean.pdf']:
        sid,_=upload(system,filename);r=client.get(f'/api/submissions/{sid}/pages/1')
        assert r.status_code==200 and r.headers['content-type']=='image/png' and r.content.startswith(b'\x89PNG'),r.text[:100] if r.status_code!=200 else ''
        assert client.get(f'/api/submissions/{sid}/pages/4').status_code==404
        client.cookies.set(COOKIE,'other');assert client.get(f'/api/submissions/{sid}/pages/1').status_code==404
        client.cookies.set(COOKIE,'user')
    image=(FIXTURES.parent/'images/clean_invoice.png').read_bytes()
    key=str(uuid4());response=client.post('/api/submissions',headers={'Origin':ORIGIN},files={'file':('invoice.png',image,'image/png')},data={'request_key':key})
    assert response.status_code==202;sid=response.json()['id']
    assert client.get(f'/api/submissions/{sid}/pages/1').status_code==200
    system['owner'].execute("UPDATE app.submissions SET document_expires_at=now()-interval '1 second' WHERE id=%s",(sid,));system['owner'].commit()
    assert client.get(f'/api/submissions/{sid}/pages/1').status_code==410


def cached_review(system):
    system['pipeline'].settings.gemini_model='native-test-model'
    value=candidate('INV-SCAN-01');value.total_gross=field(None)
    system['extractor'].candidate=value
    sid,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    assert state(system,sid)['submission']['status']=='needs_review'
    return sid


def test_saved_extraction_skips_provider_but_reruns_checks_and_keeps_blurred_total_unknown(system):
    sid=cached_review(system)
    before=state(system,sid);assert before['revision']['evidence']['extractor']['origin']=='provider'
    retry=system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN});assert retry.status_code==202
    system['extractor'].extract=lambda _:pytest.fail('cache hit must not invoke external extraction')
    system['pipeline'].reader=lambda *_:pytest.fail('cache hit must not rerun OCR')
    system['pipeline'].process_once();after=state(system,sid)
    assert after['submission']['status']=='needs_review' and after['acceptance'] is None
    assert after['revision']['evidence']['extractor']['origin']=='cache'
    assert after['revision']['evidence']['extractor']['source_revision_id']==before['revision']['id']
    assert after['revision']['evidence']['candidate']['total_gross']['value'] is None
    assert after['validation']['id']!=before['validation']['id'] and len(after['validation']['checks'])==9
    assert any(a['event_type']=='extraction.reused' for a in after['audit'])
    assert len(system['reads'])==1 and len(system['extractor'].documents)==1


def test_cached_candidate_is_checked_against_new_vendor_reference(system):
    sid=cached_review(system);before=state(system,sid)
    directory=Path(__file__).resolve().parent/'reference_data'
    raw={p.stem:list(csv.reader(p.open())) for p in directory.glob('*.csv')}
    approved=raw['Vendors'][0].index('approved')
    for row in raw['Vendors'][1:]:
        if row[0]=='V-ACME':row[approved]='FALSE'
    with system['db'].transaction() as conn:new_version=import_reference(conn,parse_reference(raw),'new-vendor-state',str(ADMIN))
    system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN})
    system['pipeline'].process_once();after=state(system,sid)
    assert after['revision']['evidence']['extractor']['origin']=='cache'
    assert after['validation']['reference_version_id']==str(new_version)
    assert next(c for c in before['validation']['checks'] if c['code']=='vendor_match')['status']=='pass'
    assert next(c for c in after['validation']['checks'] if c['code']=='vendor_match')['status']!='pass'
    assert after['acceptance'] is None


def test_cache_is_scoped_to_uploader_and_model_version(system):
    cached_review(system)
    system['client'].cookies.set(COOKIE,'other')
    upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    assert len(system['extractor'].documents)==2
    system['client'].cookies.set(COOKIE,'user')
    system['pipeline'].settings.gemini_model='changed-native-model'
    sid,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    assert state(system,sid)['revision']['evidence']['extractor']['origin']=='provider'
    assert len(system['extractor'].documents)==3


def test_cached_extraction_cannot_bypass_source_hash_or_stale_reference(system):
    sid=cached_review(system)
    # Simulate a stale read without altering the frozen reference header.
    from app.processing import reference_and_ledger
    def stale(*args):
        ref,ledger=reference_and_ledger(*args);ref['fresh']=False;return ref,ledger
    system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN})
    with patch('app.processing.reference_and_ledger',side_effect=stale):
        system['pipeline'].process_once()
    after=state(system,sid)
    assert after['submission']['status']=='reference_hold' and after['acceptance'] is None
    assert len(system['extractor'].documents)==1
    # A stored object must still match its file hash before looking up a cache.
    system['storage'].objects[next(iter(system['storage'].objects))]=b'%PDF-corrupted'
    system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN})
    system['pipeline'].process_once();after=state(system,sid)
    assert after['run']['error_code']=='SOURCE_HASH_MISMATCH'
    assert after['acceptance'] is None


@pytest.mark.parametrize('module,name,new_value',[
    ('app.extraction_cache','READER_VERSION','changed-reader'),
    ('app.extraction_cache','EXTRACTION_PROMPT_VERSION','changed-prompt'),
    ('app.processing','PIPELINE_VERSION','changed-pipeline'),
])
def test_cache_version_changes_force_new_extraction(system,module,name,new_value):
    cached_review(system)
    with patch(f'{module}.{name}',new_value):
        sid,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    assert state(system,sid)['revision']['evidence']['extractor']['origin']=='provider'
    assert len(system['extractor'].documents)==2


def test_expired_original_cache_is_not_refreshed_by_copying_a_revision(system):
    # Disposable local DB only: seed an old creation timestamp at INSERT, rather
    # than disabling immutability or mutating an existing evidence row.
    system['owner'].execute("ALTER TABLE app.invoice_revisions ALTER COLUMN created_at SET DEFAULT (now()-interval '8 days')");system['owner'].commit()
    try:sid=cached_review(system)
    finally:
        system['owner'].execute('ALTER TABLE app.invoice_revisions ALTER COLUMN created_at SET DEFAULT now()');system['owner'].commit()
    system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN});system['pipeline'].process_once()
    assert state(system,sid)['revision']['evidence']['extractor']['origin']=='provider'
    assert len(system['extractor'].documents)==2
    system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN});system['pipeline'].process_once()
    assert state(system,sid)['revision']['evidence']['extractor']['origin']=='cache'
    assert len(system['extractor'].documents)==2


def test_original_download_rejects_corruption_without_mutating_acceptance(system):
    sid,_=upload(system);system['pipeline'].process_once()
    assert state(system,sid)['acceptance']
    key=next(iter(system['storage'].objects));system['storage'].objects[key]=b'%PDF-corrupted'
    response=system['client'].get(f'/api/submissions/{sid}/document')
    assert response.status_code==409 and response.json()['detail']=='SOURCE_HASH_MISMATCH'
    assert state(system,sid)['submission']['status']=='accepted'
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1


def test_po_as_invoice_identity_cannot_bypass_duplicate_protection_on_reexport(system):
    import io
    from pypdf import PdfReader,PdfWriter
    value=candidate('INV-PART-02','PO-PARTIAL','Consulting services','4','4000.00')
    system['extractor'].candidate=value
    sid,_=upload(system,'split_4000.pdf');system['pipeline'].process_once()
    assert state(system,sid)['submission']['status']=='accepted'
    writer=PdfWriter();writer.clone_document_from_reader(PdfReader(FIXTURES/'split_4000.pdf'));writer.add_metadata({'/Producer':'Another PDF exporter'})
    output=io.BytesIO();writer.write(output)
    value.invoice_number=field('PO-PARTIAL');system['extractor'].candidate=value
    other,_=upload(system,data=output.getvalue(),display_name='reexport.pdf');system['pipeline'].process_once()
    result=state(system,other)
    assert result['submission']['status']=='needs_review' and result['acceptance'] is None
    assert next(c for c in result['validation']['checks'] if c['code']=='source_evidence')['status']=='review'
    assert scalar(system,'SELECT sum(amount_minor) FROM app.acceptances')==400000


def test_pending_upload_limit_is_atomic_and_idempotent_replays_remain_available(system):
    system['pipeline'].settings.max_pending_per_user=1
    key=uuid4();sid,_=upload(system,request_key=key)
    replay,_=upload(system,request_key=key);assert replay==sid
    response=system['client'].post('/api/submissions',headers={'Origin':ORIGIN},data={'request_key':str(uuid4())},
        files={'file':('another.pdf',(FIXTURES/'split_4000.pdf').read_bytes(),'application/pdf')})
    assert response.status_code==429 and response.json()['detail']=='USER_PENDING_LIMIT_REACHED'
    assert response.headers['retry-after']=='30'
    assert scalar(system,'SELECT count(*) FROM app.submissions')==1
    system['pipeline'].process_once()
    upload(system,'split_4000.pdf')  # completed work frees the reservation


def test_concurrent_actors_cannot_exceed_global_pending_capacity(system):
    system['pipeline'].settings.max_pending_total=1
    barrier=Barrier(2)
    def send(token):
        client=TestClient(system['client'].app);client.cookies.set(COOKIE,token)
        barrier.wait(timeout=3)
        try:return client.post('/api/submissions',headers={'Origin':ORIGIN},data={'request_key':str(uuid4())},
            files={'file':('invoice.pdf',(FIXTURES/'happy_full.pdf').read_bytes(),'application/pdf')}).status_code
        finally:client.close()
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(send,['user','other']))
    assert sorted(codes)==[202,429]
    assert scalar(system,'SELECT count(*) FROM app.submissions')==1
    assert scalar(system,'SELECT count(*) FROM app.processing_runs')==1


def test_reprocessing_cannot_bypass_pending_capacity_but_active_retry_is_idempotent(system):
    system['pipeline'].settings.max_pending_per_user=1
    system['extractor'].candidate=candidate('INV-SCAN-01');system['extractor'].candidate.total_gross=field(None)
    review,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    assert state(system,review)['submission']['status']=='needs_review'
    upload(system,'happy_full.pdf')
    response=system['client'].post(f'/api/submissions/{review}/retry',headers={'Origin':ORIGIN})
    assert response.status_code==429
    system['pipeline'].process_once()
    first=system['client'].post(f'/api/submissions/{review}/retry',headers={'Origin':ORIGIN})
    second=system['client'].post(f'/api/submissions/{review}/retry',headers={'Origin':ORIGIN})
    assert first.status_code==202 and second.status_code==202 and first.json()['run_id']==second.json()['run_id']


def test_expired_queued_work_does_not_call_storage_reader_or_provider(system):
    sid,_=upload(system)
    system['owner'].execute("UPDATE app.submissions SET document_expires_at=now()-interval '1 second' WHERE id=%s",(sid,));system['owner'].commit()
    system['pipeline'].process_once();result=state(system,sid)
    assert result['submission']['status']=='expired' and result['run']['error_code']=='SOURCE_DOCUMENT_EXPIRED'
    assert not system['extractor'].documents and not system['reads'] and not system['storage'].downloads


def test_register_search_and_keyset_pages_reach_history_beyond_workspace_limit(system):
    import uuid
    rows=[]
    # A tied timestamp exercises the UUID tiebreaker. Only disposable local DB.
    for i in range(225):
        identifier=uuid.uuid4();rows.append((identifier,USER,uuid.uuid4(),f'historic-{i:03}.pdf',f'{i:064x}',datetime(2026,1,1,tzinfo=timezone.utc)))
    with system['owner'].cursor() as c:
        c.executemany("""INSERT INTO app.submissions(id,uploaded_by,request_key,original_filename,mime_type,file_sha256,byte_size,status,created_at)
            VALUES(%s,%s,%s,%s,'application/pdf',%s,100,'processing_failed',%s)""",rows)
    system['owner'].commit()
    w=system['client'].get('/api/workspace').json();assert len(w['items'])==200 and w['total_count']==225
    seen=[];cursor=None
    while True:
        response=system['client'].get('/api/invoices',params={'limit':40,**({'cursor':cursor} if cursor else {})})
        assert response.status_code==200,response.text
        body=response.json();assert body['total_count']==225
        seen += [x['id'] for x in body['items']]
        cursor=body['next_cursor']
        if not cursor:break
    assert len(seen)==225 and len(set(seen))==225
    old_name=next(row[3] for row in rows if str(row[0]) not in {x['id'] for x in w['items']})
    found=system['client'].get('/api/invoices',params={'search':old_name}).json()
    assert found['total_count']==1 and found['items'][0]['original_filename']==old_name
    system['client'].cookies.set(COOKIE,'other')
    other=system['client'].get('/api/invoices').json();assert other['items']==[] and other['total_count']==0
    system['client'].cookies.set(COOKIE,'admin')
    assert system['client'].get('/api/invoices').json()['total_count']==225


def test_register_filters_input_validation_and_disabled_access(system):
    accepted,_=upload(system);system['pipeline'].process_once()
    system['extractor'].candidate=candidate('INV-SCAN-01');system['extractor'].candidate.total_gross=field(None)
    review,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once()
    def find(**params):
        response=system['client'].get('/api/invoices',params=params)
        assert response.status_code==200,response.text
        return response.json()
    assert [x['id'] for x in find(status='accepted',vendor='V-ACME')['items']]==[str(accepted)]
    assert [x['id'] for x in find(status='review_queue')['items']]==[str(review)]
    assert find(vendor='V-UNKNOWN')['total_count']==0
    assert find(search='INV-1001')['total_count']==1
    assert find(search='%')['total_count']==0  # literal search, not a SQL wildcard
    first=find(limit=1);assert first['next_cursor']
    newer,_=upload(system,'split_4000.pdf')
    second=find(limit=1,cursor=first['next_cursor'])
    assert len(second['items'])==1 and second['items'][0]['id']==str(accepted)
    assert second['items'][0]['id']!=str(newer)  # new inserts do not displace an older page
    for params in ({'limit':0},{'limit':101},{'cursor':'%%%bad'},{'status':'made_up'},{'search':'x'*201}):
        assert system['client'].get('/api/invoices',params=params).status_code==422
    system['owner'].execute('UPDATE app.profiles SET enabled=false WHERE user_id=%s',(USER,));system['owner'].commit()
    try:assert system['client'].get('/api/invoices').status_code==403
    finally:
        system['owner'].execute('UPDATE app.profiles SET enabled=true WHERE user_id=%s',(USER,));system['owner'].commit()


def mapped_case(system,number='INV-ADMIN-01',quantity='6',description='Consulting support hours'):
    from tools.generate_fixtures import Invoice,make_pdf,read_rows
    value=candidate(number,'PO-PARTIAL',description,quantity,str(Decimal(quantity)*1000))
    system['extractor'].candidate=value
    doc=Invoice(number=number,po='PO-PARTIAL',description=description,quantity=quantity,
                net=str(Decimal(quantity)*1000),total=str(Decimal(quantity)*1000))
    data=make_pdf(doc,{v['vendor_code']:v for v in read_rows('Vendors.csv')})
    sid,_=upload(system,data=data,display_name=number+'.pdf');system['pipeline'].process_once()
    assert state(system,sid)['submission']['status']=='needs_review'
    return sid,value


def mapping_payload(system,sid,value):
    options=system['client'].get(f'/api/admin/submissions/{sid}/review-options')
    assert options.status_code==200,options.text
    body=correction_payload(system,sid,value)
    body.update(review_reference_id=options.json()['reference_version_id'],line_mappings=[{'invoice_line':0,'po_line_code':'SERVICE'}])
    return body,options.json()


def test_admin_line_mapping_preserves_source_and_needs_explicit_acceptance(system):
    sid,value=mapped_case(system);before=state(system,sid);calls=len(system['extractor'].documents)
    assert system['client'].get(f'/api/admin/submissions/{sid}/review-options').status_code==403
    system['client'].cookies.set(COOKIE,'admin');body,options=mapping_payload(system,sid,value)
    assert options['pos'][0]['po_code']=='PO-PARTIAL'
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body)
    assert response.status_code==200,response.text
    result=state(system,sid);assert result['validation']['verdict']=='eligible' and result['acceptance'] is None
    assert result['validation']['acceptance_mode']=='admin_required'
    assert result['revision']['evidence']['candidate']==value.model_dump(mode='json')
    history=system['client'].get(f"/api/submissions/{sid}/revisions/{result['revision']['id']}")
    assert history.status_code==200
    assert history.json()['previous_revision']['id']==before['revision']['id']
    assert history.json()['previous_revision']['candidate']==value.model_dump(mode='json')
    assert history.json()['reviewer']['id']==str(ADMIN)
    assert history.json()['validation']['verdict']=='eligible'
    ctx=result['revision']['evidence']['review_context']
    assert ctx['actor_id']==str(ADMIN) and ctx['base_revision_id']==before['revision']['id']
    assert ctx['source_sha256']==result['submission']['file_sha256']
    assert ctx['line_mappings'][0]['source_description']=='Consulting support hours'
    assert ctx['line_mappings'][0]['po_description']=='Consulting services'
    assert result['reviews'][0]['details']['review_context']==ctx
    assert len(system['extractor'].documents)==calls
    with pytest.raises(psycopg.errors.RaiseException,match='ADMIN_REQUIRED'):
        with system['db'].transaction() as c:c.execute('SELECT app.accept_invoice(%s,%s)',(result['validation']['id'],USER))
    response=system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},json={'reason':'Reviewed printed services and authorized line allocation'})
    assert response.status_code==200,response.text
    assert state(system,sid)['acceptance']['method']=='admin'
    assert scalar(system,'SELECT sum(amount_minor) FROM app.acceptances')==600000
    assert system['pipeline'].publish_once()
    assert state(system,sid)['publication']['status']=='published'


def test_manual_resolution_permissions_do_not_carry_into_reprocessing(system):
    sid,value=mapped_case(system);system['client'].cookies.set(COOKIE,'admin')
    body,_=mapping_payload(system,sid,value)
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==200
    assert state(system,sid)['validation']['verdict']=='eligible'
    assert system['client'].post(f'/api/submissions/{sid}/retry',headers={'Origin':ORIGIN}).status_code==202
    system['pipeline'].process_once();result=state(system,sid)
    assert result['validation']['verdict']=='needs_review' and result['acceptance'] is None
    assert not result['revision']['evidence']['review_context']['line_mappings']


@pytest.mark.parametrize('bad_mapping',[
    [{'invoice_line':0,'po_line_code':'MISSING'}],
    [{'invoice_line':50,'po_line_code':'SERVICE'}],
    [{'invoice_line':0,'po_line_code':'SERVICE'},{'invoice_line':0,'po_line_code':'SERVICE'}],
    [{'invoice_line':True,'po_line_code':'SERVICE'}],
])
def test_admin_invalid_line_mapping_is_rejected_without_new_revision(system,bad_mapping):
    sid,value=mapped_case(system);before=state(system,sid)
    system['client'].cookies.set(COOKIE,'admin');body,_=mapping_payload(system,sid,value);body['line_mappings']=bad_mapping
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body)
    assert response.status_code==422,response.text
    assert state(system,sid)['revision']['id']==before['revision']['id']
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==0


def test_manual_line_options_are_reference_pinned_and_role_scoped(system):
    sid,value=mapped_case(system);system['client'].cookies.set(COOKIE,'admin');body,_=mapping_payload(system,sid,value)
    no_pin=dict(body);no_pin.pop('review_reference_id')
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=no_pin).status_code==422
    with system['db'].transaction() as c:import_reference(c,sample(),'changed-review-reference',str(ADMIN))
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==409
    system['client'].cookies.set(COOKIE,'user')
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body).status_code==403
    assert system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},json={'reason':'Try forbidden acceptance'}).status_code==403


def test_two_manually_resolved_invoices_still_compete_for_the_same_remaining_balance(system):
    first,v1=mapped_case(system);second,v2=mapped_case(system,'INV-ADMIN-02')
    system['client'].cookies.set(COOKIE,'admin')
    for sid,value in ((first,v1),(second,v2)):
        body,_=mapping_payload(system,sid,value)
        response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body)
        assert response.status_code==200,response.text
        assert state(system,sid)['validation']['verdict']=='eligible'
    accepted=system['client'].post(f'/api/admin/submissions/{first}/accept',headers={'Origin':ORIGIN},json={'reason':'Authorize first reviewed invoice'})
    held=system['client'].post(f'/api/admin/submissions/{second}/accept',headers={'Origin':ORIGIN},json={'reason':'Try second reviewed invoice'})
    assert accepted.status_code==200 and held.status_code==409
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==1
    assert scalar(system,'SELECT sum(amount_minor) FROM app.acceptances')==600000
    assert state(system,second)['acceptance'] is None


def test_admin_may_confirm_ocr_confidence_only_when_text_already_supports_the_value(system):
    # Actual PDF bytes/text; OCR confidence is simulated to target adjudication.
    # Existing extraction tests separately exercise real Tesseract scans.
    doc=read_document((FIXTURES/'happy_full.pdf').read_bytes(),'application/pdf')
    doc.pages[0].method='ocr';doc.pages[0].low_confidence_tokens=['INV-1001']
    system['pipeline'].reader=lambda *_:doc.model_copy(deep=True)
    sid,_=upload(system);system['pipeline'].process_once();assert state(system,sid)['submission']['status']=='needs_review'
    system['client'].cookies.set(COOKIE,'admin')
    options=system['client'].get(f'/api/admin/submissions/{sid}/review-options').json()
    assert options['ocr_fields']==['invoice_number']
    body=correction_payload(system,sid);body['verified_ocr_fields']=['invoice_number']
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body)
    assert response.status_code==200,response.text
    result=state(system,sid);assert result['validation']['verdict']=='eligible' and result['acceptance'] is None
    assert result['revision']['evidence']['raw_issues'][0]['code']=='LOW_OCR_CONFIDENCE'
    assert result['revision']['evidence']['issues']==[]
    assert result['revision']['evidence']['review_context']['verified_ocr_fields']==['invoice_number']
    assert system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},json={'reason':'Read the original identifier and authorize acceptance'}).status_code==200


def test_ocr_confirmation_cannot_override_an_unreadable_total(system):
    value=candidate('INV-SCAN-01');value.total_gross=field(None);system['extractor'].candidate=value
    sid,_=upload(system,'scan_blurred_total.pdf');system['pipeline'].process_once();before=state(system,sid)
    system['client'].cookies.set(COOKIE,'admin')
    body=correction_payload(system,sid,candidate('INV-SCAN-01'));body['verified_ocr_fields']=['total_gross']
    response=system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=body)
    assert response.status_code==422,response.text
    assert state(system,sid)['revision']['id']==before['revision']['id']
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==0


def test_fresh_pack_runs_complete_case_study_and_admin_resolution_locally(system,tmp_path):
    from tools.generate_fixtures import generate_demo_pack
    pack=generate_demo_pack(tmp_path/'REHEARSAL','REHEARSAL',admin_review=True)
    tabs={p.stem:list(csv.reader(p.open())) for p in (Path(__file__).parent/'reference_data').glob('*.csv')}
    for name,records in pack['reference_rows'].items():
        tabs[name].extend([[record[column] for column in tabs[name][0]] for record in records])
    with system['db'].transaction() as c:import_reference(c,parse_reference(tabs),'local-rehearsal-only',str(ADMIN))
    fixtures=pack['fixtures'];prefix='PO-DEMO-REHEARSAL-'
    def run(index,quantity='10',total='10000.00',description=None,po=None):
        f=fixtures[index]
        desc=description or next(x['description'] for x in pack['reference_rows']['POLines'] if x['po_code']==f['po_code'])
        value=candidate(f['invoice_number'],f['po_code'] if po is None else po,desc,quantity,total)
        system['extractor'].candidate=value
        sid,_=upload(system,data=(tmp_path/'REHEARSAL'/f['file']).read_bytes(),display_name=f['file'])
        system['pipeline'].process_once();return sid,value
    happy,_=run(0);assert state(system,happy)['submission']['status']=='accepted'
    duplicate,_=run(1);assert state(system,duplicate)['submission']['status']=='blocked_duplicate'
    partial,_=run(2,'6','6000.00');assert state(system,partial)['submission']['status']=='accepted'
    over,_=run(3,'4.5','4500.00');assert state(system,over)['submission']['status']=='needs_review'
    amb=fixtures[5];value=candidate(amb['invoice_number'],None,'Website design - demo REHEARSAL','5','5000.00')
    system['extractor'].candidate=value;sid,_=upload(system,data=(tmp_path/'REHEARSAL'/amb['file']).read_bytes());system['pipeline'].process_once()
    assert state(system,sid)['validation']['po_code'] is None
    system['client'].cookies.set(COOKIE,'admin')
    assert system['client'].post(f'/api/admin/submissions/{sid}/correct',headers={'Origin':ORIGIN},json=correction_payload(system,sid,value,prefix+'AMBIG-A')).status_code==200
    assert system['client'].post(f'/api/admin/submissions/{sid}/accept',headers={'Origin':ORIGIN},json={'reason':'Verified exact ambiguous PO and supplier context'}).status_code==200
    blurred=fixtures[6];unreadable=candidate(blurred['invoice_number'],blurred['po_code'],'Document support - demo REHEARSAL')
    unreadable.total_gross=field(None);system['extractor'].candidate=unreadable
    unclear,_=upload(system,data=(tmp_path/'REHEARSAL'/blurred['file']).read_bytes());system['pipeline'].process_once()
    unclear_result=state(system,unclear)
    assert unclear_result['submission']['status']=='needs_review' and unclear_result['revision']['total_gross_minor'] is None
    assert 'total_gross' in unclear_result['revision']['unresolved_critical_fields']
    reviewed,value=run(7,'5','5000.00','Office ops support - demo REHEARSAL')
    assert state(system,reviewed)['submission']['status']=='needs_review'
    body,_=mapping_payload(system,reviewed,value)
    assert system['client'].post(f'/api/admin/submissions/{reviewed}/correct',headers={'Origin':ORIGIN},json=body).status_code==200
    assert system['client'].post(f'/api/admin/submissions/{reviewed}/accept',headers={'Origin':ORIGIN},json={'reason':'Verified abbreviated printed service and mapped authorized line'}).status_code==200
    # Publish the exact four ledger decisions; held/duplicate runs create no task.
    while system['pipeline'].publish_once():pass
    assert scalar(system,'SELECT count(*) FROM app.acceptances')==4
    assert scalar(system,"SELECT count(*) FROM app.export_tasks WHERE status='published'")==4
    assert scalar(system,"SELECT sum(amount_minor) FROM app.acceptances")==2600000
    assert len(system['publisher'].rows)==4

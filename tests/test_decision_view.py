from copy import deepcopy
from app.decision_view import explain_decision,recorded_timing


def held(code='po_match',subtype='AMBIGUOUS_PO'):
    return {'submission':{'status':'needs_review'},'validation':{'checks':[{'code':code,'status':'review','reason_code':subtype}]}}


def test_financial_state_comes_from_ledger_not_badge_or_publication():
    data=held();data['acceptance']={'id':'recorded'};data['publication']={'status':'failed'}
    result=explain_decision(data)
    assert result['commitment']=='recorded' and result['report']=='failed' and result['reason_code']=='ACCEPTED'
    assert 'again' in result['next_action']
    del data['acceptance'];data['submission']['status']='accepted'
    assert explain_decision(data)['reason_code']=='INCONSISTENT_RECORD'
    assert explain_decision(data)['commitment']=='not_recorded'


def test_absent_total_never_offers_transcription_or_po_arithmetic():
    data=held();data['revision']={'evidence':{'candidate':{'total_gross':{'value':None}}}}
    result=explain_decision(data)
    assert result['reason_code']=='PAYABLE_MISSING' and 'clearer original' in result['next_action']
    assert 'cannot replace' in result['next_action'] and result['report']=='not_required'


def test_closed_and_ambiguous_po_actions_are_different():
    ambiguous=explain_decision(held())
    assert 'exact candidate' in ambiguous['next_action'] and 'separately' in ambiguous['next_action']
    closed=explain_decision(held(subtype='PO_CLOSED'))
    assert 'do not substitute' in closed['next_action']
    over=explain_decision(held('po_balance',None))
    assert 'cannot override' in over['next_action']


def test_every_check_has_a_safe_business_action_and_waiting_never_passes():
    for code in ('required_fields','vendor_match','po_match','source_evidence','duplicate_check','currency','arithmetic','line_allocation','po_balance'):
        result=explain_decision(held(code,None))
        assert result['primary_reason'] and result['next_action'] and result['commitment']=='not_recorded'
    data=held();data['validation']['checks'].append({'code':'currency','status':'review','blocked_by':['po_match']})
    original=deepcopy(data);assert explain_decision(data)['reason_code']=='AMBIGUOUS_PO';assert data==original


def test_rejected_failed_expired_and_duplicate_are_explicit_outcomes():
    for status,expected in [('rejected','REJECTED'),('processing_failed','PROCESSING_FAILED'),('expired','SOURCE_EXPIRED'),('blocked_duplicate','DUPLICATE')]:
        data=held();data['submission']['status']=status
        assert explain_decision(data)['reason_code']==expected
        assert explain_decision(data)['commitment']=='not_recorded'


def test_timings_only_use_recorded_events_for_the_selected_run():
    run={'id':'selected','state':'completed','created_at':'2026-11-07T10:00:00Z','started_at':'2026-11-07T10:00:02Z','finished_at':'2026-11-07T10:00:12Z'}
    def event(r,s,t):return {'run_id':r,'event_type':'processing.stage','stage':s,'created_at':f'2026-11-07T10:00:{t:02}Z'}
    timings=recorded_timing(run,[event('old','reading_document',1),event('selected','reading_document',3),event('selected','extracting_fields',5)])
    assert timings['queue_seconds']==2 and timings['processing_seconds']==10
    assert [r['seconds'] for r in timings['stages']]==[2,7]
    run['finished_at']=None;run['state']='running'
    timings=recorded_timing(run,[event('selected','extracting_fields',5)])
    assert timings['stages'][0]['seconds'] is None and timings['stages'][0]['state']=='in_progress'
    assert timings['processing_seconds'] is None


def test_unknown_or_inconsistent_timing_is_not_filled_with_fake_duration():
    run={'id':'r','state':'failed','created_at':'bad','started_at':'2026-11-07T10:00:10Z','finished_at':'2026-11-07T10:00:00Z'}
    assert recorded_timing(run,[])=={'stages':[],'queue_seconds':None,'processing_seconds':None}


def test_passing_validation_is_not_a_committed_decision_and_recheck_reason_is_run_scoped():
    data={'submission':{'status':'needs_review'},'validation':{'verdict':'eligible','acceptance_mode':'automatic'},'run':{'id':'current'}}
    assert explain_decision(data)['reason_code']=='ELIGIBLE_NOT_COMMITTED'
    data['audit']=[{'event_type':'acceptance.recheck_held','run_id':'older'}]
    assert explain_decision(data)['reason_code']=='ELIGIBLE_NOT_COMMITTED'
    data['audit'][0]['run_id']='current'
    assert explain_decision(data)['reason_code']=='FINAL_RECHECK_HELD'


def test_date_and_conflicting_total_holds_have_specific_non_override_actions():
    data=held('required_fields',None);data['revision']={'unresolved_critical_fields':['invoice_date']}
    result=explain_decision(data);assert result['reason_code']=='DATE_REVIEW_REQUIRED' and 'do not guess' in result['next_action']
    data=held('source_evidence',None);data['revision']={'evidence':{'issues':[{'code':'CONFLICTING_PAYABLE_VALUES','field':'total_gross'}]}}
    result=explain_decision(data);assert result['reason_code']=='CONFLICTING_PAYABLE_VALUES' and 'corrected invoice' in result['next_action']


def test_missing_allocation_is_the_primary_blocker_before_dependent_arithmetic():
    data=held('line_allocation',None);data['validation']['checks'].append({'code':'arithmetic','status':'review'})
    assert explain_decision(data)['reason_code']=='LINE_ALLOCATION'

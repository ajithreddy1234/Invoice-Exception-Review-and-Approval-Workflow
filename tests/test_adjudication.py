"""Human discretion must change interpretation, never source facts or limits."""
from copy import deepcopy
from decimal import Decimal
import pytest
from app.adjudication import review_evidence
from app.rules import evaluate
from test_rules import invoice,reference,ledger,synthetic,source,checks


def variant():return invoice(description='Office ops support')


def test_manual_description_mapping_preserves_printed_wording_and_requires_explicit_admin():
    value=variant();doc=synthetic(value)
    assert evaluate(value,doc,reference(),ledger()).verdict=='needs_review'
    decision=evaluate(value,doc,reference(),ledger(),line_mappings={0:'SERVICE'})
    assert decision.verdict=='eligible' and decision.acceptance_mode=='admin_required'
    assert all(c['status']=='pass' for c in decision.checks) and len(decision.checks)==9
    assert decision.revision['line_items'][0]['description']['value']=='Office ops support'
    mapped=decision.revision['evidence']['review_context']['line_mappings'][0]
    assert mapped['source_description']=='Office ops support' and mapped['po_description']=='Office support package'
    assert mapped['source']['quote']=='Office ops support'


@pytest.mark.parametrize('mapping',[{0:'MISSING'},{2:'SERVICE'},{True:'SERVICE'}])
def test_invalid_mapping_cannot_produce_eligibility(mapping):
    value=variant();result=evaluate(value,synthetic(value),reference(),ledger(),line_mappings=mapping)
    assert result.verdict=='needs_review' and checks(result)['line_allocation']=='review'


@pytest.mark.parametrize('change', ['unit','price','quantity','tax','vendor','currency','duplicate','balance','missing_description','missing_quantity','missing_price'])
def test_mapping_never_waives_other_business_checks(change):
    value=variant();ref=reference();used=ledger()
    if change=='missing_description':value.line_items[0].description.value=None;value.line_items[0].description.source=None
    if change=='missing_quantity':value.line_items[0].quantity.value=None;value.line_items[0].quantity.source=None
    if change=='missing_price':value.line_items[0].unit_price.value=None;value.line_items[0].unit_price.source=None
    if change=='unit':value.line_items[0].unit.value=value.line_items[0].unit.source.quote='day'
    if change=='price':value.line_items[0].unit_price.value='1100.00';value.line_items[0].unit_price.source.quote='1,100.00'
    if change=='quantity':used['accepted_quantities']={('PO-FULL','SERVICE'):Decimal(1)}
    if change=='tax':value.tax_amount.value='100.00';value.tax_amount.source.quote='100.00'
    if change=='vendor':value.vendor_name.value=value.vendor_name.source.quote='Unknown Vendor'
    if change=='currency':value.currency.value=value.currency.source.quote='USD'
    if change=='duplicate':used['duplicate']=True
    if change=='balance':used['accepted_amounts']={'PO-FULL':100000}
    result=evaluate(value,synthetic(value),ref,used,line_mappings={0:'SERVICE'})
    assert result.verdict!='eligible' and result.acceptance_mode=='not_allowed'


def uncertain_identity():
    value=invoice();doc=source('happy_full.pdf')
    doc.pages[0].method='ocr';doc.pages[0].low_confidence_tokens=['INV-1001']
    return value,doc


def test_human_confirmation_only_acknowledges_grounded_ocr_confidence():
    value,doc=uncertain_identity()
    assert evaluate(value,doc,reference(),ledger()).verdict=='needs_review'
    decision=evaluate(value,doc,reference(),ledger(),verified_ocr_fields=['invoice_number'])
    assert decision.verdict=='eligible' and decision.acceptance_mode=='admin_required'
    evidence=decision.revision['evidence']
    assert evidence['issues']==[] and any(i['code']=='LOW_OCR_CONFIDENCE' for i in evidence['raw_issues'])
    # No persisted or model-proposed flag can affect a normal processing run.
    assert evaluate(value,doc,reference(),ledger()).verdict=='needs_review'


@pytest.mark.parametrize('path',['total_gross','anything','line_items.999.quantity','__dict__'])
def test_unsupported_ocr_confirmation_is_a_failure_not_a_silent_waiver(path):
    value,doc=uncertain_identity();raw,effective=review_evidence(value,doc,[path])
    assert any(i.code=='INVALID_OCR_VERIFICATION' for i in effective)
    assert any(i.code=='LOW_OCR_CONFIDENCE' for i in raw)


def test_confirming_ocr_cannot_invent_missing_or_unsupported_fields():
    value,doc=uncertain_identity();value.invoice_number.value='PO-FULL';value.invoice_number.source.quote='PO-FULL'
    _,effective=review_evidence(value,doc,['invoice_number'])
    assert any(i.code=='INVOICE_IDENTITY_EVIDENCE_REQUIRED' for i in effective)
    assert any(i.code=='INVALID_OCR_VERIFICATION' for i in effective)
    value=invoice(number='INV-SCAN-01');doc=source('scan_blurred_total.pdf')
    result=evaluate(value,doc,reference(),ledger(),verified_ocr_fields=['total_gross'])
    assert result.verdict!='eligible' and checks(result)['source_evidence']=='review'


def test_changed_quoted_value_cannot_borrow_an_ocr_acknowledgement():
    value,doc=uncertain_identity();value.invoice_number.value='INV-1002'
    _,effective=review_evidence(value,doc,['invoice_number'])
    assert any(i.code=='VALUE_NOT_SUPPORTED' for i in effective)
    assert any(i.code=='INVALID_OCR_VERIFICATION' for i in effective)

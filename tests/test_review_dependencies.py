"""Root-cause labels never turn a held financial decision into an approval."""
import pytest
from test_rules import invoice,reference,ledger,synthetic,checks,source
from app.rules import evaluate,CHECK_CODES


def test_unregistered_printed_po_explains_the_actual_dependency():
    value=invoice(po='PO-DEMO-D-PARTIAL')
    result=evaluate(value,synthetic(value),reference(),ledger());items={c['code']:c for c in result.checks}
    assert result.verdict=='needs_review' and result.acceptance_mode=='not_allowed'
    assert list(items)==list(CHECK_CODES)
    assert items['po_match']['reason_code']=='PO_NOT_REGISTERED'
    assert 'PO-DEMO-D-PARTIAL' in items['po_match']['detail']
    for code in ('currency','arithmetic','line_allocation','po_balance'):
        assert items[code]['status']=='review' and items[code]['blocked_by']==['po_match']
        assert items[code]['detail'].startswith('Waiting for a valid purchase-order match')
    assert 'tax rate conflicts' not in items['line_allocation']['detail']
    assert result.summary.endswith('Check: po_match.')
    assert result.allocations==[]


def test_po_disambiguation_clears_dependencies_but_remains_admin_only():
    value=invoice(number='INV-AMB-01',po=None,description='Website design milestones',quantity='5',net='5000.00',total='5000.00')
    doc=source('ambiguous_no_po.pdf')
    held=evaluate(value,doc,reference(),ledger())
    assert next(c for c in held.checks if c['code']=='po_match')['reason_code']=='AMBIGUOUS_PO'
    fixed=evaluate(value,doc,reference(),ledger(),selected_po='PO-AMBIG-A')
    assert fixed.verdict=='eligible' and fixed.acceptance_mode=='admin_required'
    assert all(c['status']=='pass' and 'blocked_by' not in c for c in fixed.checks)
    assert fixed.revision['po_reference'] is None


@pytest.mark.parametrize('kind,expected',[('closed','PO_CLOSED'),('vendor','PO_VENDOR_MISMATCH')])
def test_existing_but_invalid_po_has_a_specific_reason(kind,expected):
    value=invoice();ref=reference()
    po=next(p for p in ref['pos'] if p['po_code']=='PO-FULL')
    if kind=='closed':po['status']='closed'
    else:po['vendor_code']='V-BETA'
    result=evaluate(value,synthetic(value),ref,ledger())
    assert result.verdict=='needs_review'
    assert next(c for c in result.checks if c['code']=='po_match')['reason_code']==expected


def test_independent_currency_problem_is_not_hidden_by_missing_po():
    value=invoice(po='PO-MISSING');value.currency.value=value.currency.source.quote='EUR'
    result=evaluate(value,synthetic(value),reference(),ledger());currency=next(c for c in result.checks if c['code']=='currency')
    assert currency['status']=='review' and 'blocked_by' not in currency
    assert 'currency' in result.summary and result.acceptance_mode=='not_allowed'

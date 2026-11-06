"""Real generated files/OCR plus explicit candidate rules; not model accuracy tests."""
from hashlib import sha256
import json
from pathlib import Path
import pytest
from app.extraction import read_document
from app.rules import evaluate
from test_rules import invoice,field,reference,ledger

DIRECTORY=Path(__file__).parent/'fixtures/layouts'
ENTRIES=json.loads((DIRECTORY/'manifest.json').read_text())['fixtures']


@pytest.mark.parametrize('entry',ENTRIES,ids=lambda e:e['file'])
def test_independent_layout_input_has_an_explained_grounded_outcome(entry):
    data=(DIRECTORY/entry['file']).read_bytes();assert sha256(data).hexdigest()==entry['sha256']
    document=read_document(data,entry['mime']);assert document.pages and any(p.text.strip() for p in document.pages)
    s=entry['fields'];candidate=invoice(number=s['number'],po=s['po'],vendor=s['vendor'],description=s['description'],quantity=s['quantity'],unit=s['unit'],net=s['net'],tax=s['tax'],total=s['total'],presentation='exclusive' if s['rate']!='0' else 'none')
    candidate.invoice_date=field(s['date'])
    result=evaluate(candidate,document,reference(),ledger())
    expected=entry['expected_with_grounded_candidate']
    assert result.verdict in ('eligible','needs_review') if expected=='eligible_or_review' else result.verdict==expected,result.checks
    if result.verdict=='needs_review':assert any(c['status']!='pass' and c['detail'] for c in result.checks)
    if entry['file']=='06_scan_statement.pdf':assert all(p.method=='ocr' for p in document.pages)
    if 'date' in entry['file']:assert result.revision['invoice_date'] is None


def test_layout_manifest_records_real_provenance_and_intentional_scan_identity():
    assert len(ENTRIES)==8
    assert sum(e['engine']=='LibreOffice Writer ODT export' for e in ENTRIES)==3
    assert next(e for e in ENTRIES if e['file']=='06_scan_statement.pdf')['duplicate_identity_of']=='03_writer_tax.pdf'

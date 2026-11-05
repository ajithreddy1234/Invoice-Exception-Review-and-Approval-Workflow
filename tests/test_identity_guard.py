from pathlib import Path
import pytest
from app.extraction import DocumentText,PageText,validate_evidence,read_document
from app.invoice_api import Reason
from app.register import decode_cursor,encode_cursor
from fastapi import HTTPException
from pydantic import ValidationError
from test_extraction import candidate,field

FIXTURES=Path(__file__).parent/'fixtures/pdfs'


def issues(value,document):
    return {(i.field,i.code) for i in validate_evidence(value,document)}


def test_actual_po_reference_cannot_be_substituted_for_invoice_identity():
    document=read_document((FIXTURES/'happy_full.pdf').read_bytes(),'application/pdf')
    value=candidate();value.invoice_number=field('PO-FULL')
    assert ('invoice_number','INVOICE_IDENTITY_EVIDENCE_REQUIRED') in issues(value,document)


@pytest.mark.parametrize('label',['Invoice number:','Invoice No.','Invoice #','Invoice:','Bill No:','Invoice ID:'])
def test_labelled_identifiers_preserve_punctuation_and_leading_zeros(label):
    value=candidate();value.invoice_number=field('0001/2026-A')
    doc=DocumentText(pages=[PageText(number=1,method='embedded',text=label+' 0001/2026-A')])
    assert not any(i.field=='invoice_number' for i in validate_evidence(value,doc))


def test_stacked_identifier_label_and_repeated_header_are_supported_but_conflicts_are_not():
    value=candidate();doc=DocumentText(pages=[PageText(number=1,method='embedded',text='Invoice number:\nINV-1001')])
    assert not any(i.field=='invoice_number' for i in validate_evidence(value,doc))
    doc.pages.append(PageText(number=2,method='embedded',text='Invoice No: INV-1001'))
    assert ('invoice_number','CONFLICTING_INVOICE_IDENTITIES') not in issues(value,doc)
    doc.pages[1].text='Invoice No: INV-2002'
    assert ('invoice_number','CONFLICTING_INVOICE_IDENTITIES') in issues(value,doc)


def test_header_without_identifier_and_uncertain_label_cannot_authorize_automation():
    value=candidate();doc=DocumentText(pages=[PageText(number=1,method='embedded',text='INVOICE\nAcme Services Pvt Ltd\nPO reference: INV-1001')])
    assert ('invoice_number','INVOICE_IDENTITY_EVIDENCE_REQUIRED') in issues(value,doc)
    doc.pages[0].text='Invoice number: INV-1001';doc.pages[0].method='ocr';doc.pages[0].low_confidence_tokens=['number']
    assert ('invoice_number','LOW_OCR_CONFIDENCE') in issues(value,doc)


@pytest.mark.parametrize('reason',['     ',' \n\t ','  abc  '])
def test_audit_reasons_reject_whitespace_before_db_work(reason):
    with pytest.raises(ValidationError):Reason(reason=reason)


def test_reason_normalization_and_strict_cursor_input():
    assert Reason(reason='  Checked original invoice  ').reason=='Checked original invoice'
    row={'created_at':'2026-11-06T00:00:00+00:00','id':'11111111-1111-4111-8111-111111111111'}
    dt,identifier=decode_cursor(encode_cursor(row));assert dt.tzinfo and str(identifier)==row['id']
    for value in ['garbage','%%%','eyJhdCI6IjIwMjYtMTEtMDYiLCJpZCI6IjExMSJ9']:
        with pytest.raises(HTTPException):decode_cursor(value)


def word(text,x,y,width=60,confidence=95):
    return dict(text=text,left=x,top=y,width=width,height=20,confidence=confidence)


def test_ocr_geometry_pairs_stacked_id_without_mixing_bill_to_column():
    from app.extraction import _ocr_invoice_regions
    lines=[[word('Invoice',900,100),word('number',970,100)],
           [word('BILL',100,140),word('TO',170,140),word('INV-1001',900,140,100)]]
    regions=_ocr_invoice_regions(lines)
    assert len(regions)==1 and regions[0]['value']=='INV-1001'
    assert regions[0]['label_box']==[900,100,1030,120]
    assert regions[0]['value_box']==[900,140,1000,160]
    doc=DocumentText(pages=[PageText(number=1,method='ocr',text='Invoice number\nBILL TO INV-1001',
                                    invoice_number_regions=regions)])
    assert not any(i.field=='invoice_number' for i in validate_evidence(candidate(),doc))


@pytest.mark.parametrize('extra',[
    [word('INV-1001',100,140)],  # unrelated left column
    [word('INV-1001',900,240)],  # too far from label
    [word('PO',900,140),word('INV-1001',970,140)],  # a different field, not a value
])
def test_ocr_geometry_never_borrows_unrelated_identifiers(extra):
    from app.extraction import _ocr_invoice_regions
    regions=_ocr_invoice_regions([[word('Invoice',900,100),word('number',970,100)],extra])
    assert len(regions)==1 and regions[0]['value'] is None


def test_ocr_geometry_uncertainty_and_missing_value_always_hold_for_review():
    from app.extraction import _ocr_invoice_regions
    regions=_ocr_invoice_regions([[word('Invoice',900,100),word('number',970,100)],
                                  [word('INV-1001',900,140,confidence=50)]])
    doc=DocumentText(pages=[PageText(number=1,method='ocr',text='Invoice number\nINV-1001',invoice_number_regions=regions)])
    assert ('invoice_number','LOW_OCR_CONFIDENCE') in issues(candidate(),doc)
    regions[0]['value']=None
    doc.pages[0].invoice_number_regions=[type(doc.pages[0].invoice_number_regions[0])(**regions[0])]
    assert ('invoice_number','INVOICE_IDENTITY_AMBIGUOUS_LAYOUT') in issues(candidate(),doc)

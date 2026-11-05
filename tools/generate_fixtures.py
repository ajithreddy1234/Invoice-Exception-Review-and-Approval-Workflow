#!/usr/bin/env python3
"""Generate synthetic source invoices; never connect to the application/services.

Run: python tools/generate_fixtures.py
Optional: --output-dir /path/to/fixtures
Requires reportlab, pypdfium2, Pillow, pypdf.
Expected outcomes live ONLY in manifest.json, never in the invoice content.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
from zipfile import ZipFile, ZIP_DEFLATED
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
W, H = A4
TOTAL_Y = 306
CENT = Decimal('0.01')
GENERATOR_VERSION = '1.1.0'


def money(value: str | Decimal, currency: str = 'INR') -> str:
    return f'{currency} {Decimal(value):,.2f}'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Invoice:
    number: str | None = 'INV-1001'
    date: str | None = '2026-10-31'
    vendor: str = 'V-ACME'
    vendor_label: str | None = None
    include_vendor_identifiers: bool = True
    po: str | None = 'PO-FULL'
    currency: str = 'INR'
    description: str = 'Office support package'
    quantity: str | None = '10'
    unit: str = 'hour'
    unit_net: str | None = '1000.00'
    net: str = '10000.00'
    tax: str = '0.00'
    total: str | None = '10000.00'
    tax_rate: str = '0'
    tax_presentation: str = 'none'
    rounding: str = '0.00'
    layout: str = 'navy'


def read_rows(name: str) -> list[dict[str, str]]:
    with (ROOT / 'tests' / 'reference_data' / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def make_pdf(invoice: Invoice, vendors: dict[str, dict[str, str]]) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, invariant=1, pageCompression=1)
    c.setTitle(f'Invoice {invoice.number or "unreferenced"}')
    vendor_name = invoice.vendor_label or vendors[invoice.vendor]['legal_name']
    c.setAuthor(vendor_name)
    navy = colors.HexColor('#17324D' if invoice.layout == 'navy' else '#315C4E')
    muted = colors.HexColor('#5B6875')
    pale = colors.HexColor('#EDF2F6')
    c.setFillColor(navy)
    c.rect(0, H - 115, W, 115, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 21)
    c.drawString(44, H - 48, vendor_name)
    c.setFont('Helvetica', 10)
    c.drawString(44, H - 70, '14 Example Business Park, Bengaluru, India')
    email = f'billing@{invoice.vendor.lower()}.example.test' if invoice.include_vendor_identifiers else 'accounts@example.test'
    c.drawString(44, H - 87, f'Accounts: {email}')
    c.setFont('Helvetica-Bold', 12)
    c.drawRightString(W - 44, H - 103, 'INVOICE' if invoice.layout == 'navy' else 'SERVICE INVOICE')

    c.setFillColor(muted)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(44, 680, 'BILL TO')
    c.setFillColor(navy)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(44, 659, 'Aster Operations Pvt Ltd')
    c.setFillColor(muted)
    c.setFont('Helvetica', 10)
    c.drawString(44, 642, '25 Example Avenue, Bengaluru, India')
    c.drawString(44, 625, 'Accounts Payable Department')
    if invoice.include_vendor_identifiers:
        c.drawString(44, 601, 'Vendor reference: ' + invoice.vendor)
        c.drawString(44, 585, 'Tax registration: ' + vendors[invoice.vendor]['tax_registration_id'])
    facts = []
    if invoice.number is not None:
        facts.append(('Invoice number', invoice.number))
    if invoice.date is not None:
        facts.append(('Invoice date', invoice.date))
    if invoice.po is not None:
        facts.append(('PO reference', invoice.po))
    facts.append(('Currency', invoice.currency))
    y = 700
    for label, value in facts:
        c.setFillColor(muted)
        c.setFont('Helvetica', 9)
        c.drawString(360, y, label)
        c.setFillColor(navy)
        c.setFont('Helvetica-Bold', 10)
        c.drawString(360, y - 15, value)
        y -= 35

    c.setFillColor(pale)
    c.rect(44, 541, W - 88, 27, fill=1, stroke=0)
    c.setFillColor(navy)
    c.setFont('Helvetica-Bold', 9)
    for label, x, right in [('Description', 53, False), ('Qty', 329, True),
                            ('Unit', 347, False), ('Unit price', 447, True), ('Amount', W - 53, True)]:
        (c.drawRightString if right else c.drawString)(x, 551, label)
    c.setFont('Helvetica', 9)
    # Two lines keep longer descriptions within their column.
    words = invoice.description.split()
    lines, line = [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if c.stringWidth(trial, 'Helvetica', 9) > 247:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    if len(lines) > 2:
        raise ValueError('Fixture description exceeds supported row height')
    for i, text in enumerate(lines):
        c.drawString(53, 519 - i * 14, text)
    if invoice.quantity is not None:
        c.drawRightString(329, 519, invoice.quantity)
        c.drawString(347, 519, invoice.unit)
    if invoice.unit_net is not None:
        rate = Decimal(invoice.unit_net)
        if invoice.tax_presentation == 'inclusive':
            rate *= 1 + Decimal(invoice.tax_rate) / 100
        c.drawRightString(447, 519, f'{rate:,.2f}')
    line_amount = invoice.total if invoice.tax_presentation == 'inclusive' else invoice.net
    c.drawRightString(W - 53, 519, f'{Decimal(line_amount):,.2f}')
    c.setStrokeColor(pale)
    c.line(44, 481, W - 44, 481)
    if invoice.tax_presentation == 'inclusive':
        c.setFillColor(muted)
        c.drawString(53, 459, f'All listed prices include {invoice.tax_rate}% GST.')
    else:
        for label, value, baseline in [
            ('Subtotal (net)', invoice.net, 399),
            (f'GST ({invoice.tax_rate}%)', invoice.tax, 377),
        ]:
            c.setFillColor(muted)
            c.drawString(337, baseline, label)
            c.setFillColor(navy)
            c.drawRightString(W - 53, baseline, money(value, invoice.currency))
        if Decimal(invoice.rounding) != 0:
            c.setFillColor(muted)
            c.drawString(337, 355, 'Rounding adjustment')
            c.setFillColor(navy)
            c.drawRightString(W - 53, 355, money(invoice.rounding, invoice.currency))

    c.setFillColor(pale)
    c.roundRect(325, TOTAL_Y - 18, W - 369, 50, 5, fill=1, stroke=0)
    c.setFillColor(navy)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(337, TOTAL_Y + 12, 'TOTAL PAYABLE')
    if invoice.total is not None:
        c.setFont('Helvetica-Bold', 16)
        c.drawRightString(W - 53, TOTAL_Y - 7, money(invoice.total, invoice.currency))

    c.setFillColor(muted)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(44, 231, 'Payment terms')
    c.setFont('Helvetica', 9)
    c.drawString(44, 212, 'Payment due within 14 days of the invoice date.')
    c.drawString(44, 196, 'Please include the invoice reference in your correspondence.')
    if invoice.layout == 'green':
        c.drawString(44, 180, 'For invoice enquiries, contact the accounts team above.')
    c.setStrokeColor(pale)
    c.line(44, 66, W - 44, 66)
    c.setFont('Helvetica', 8)
    c.drawString(44, 49, 'SYNTHETIC DEMO DOCUMENT - not a real payment request')
    c.drawRightString(W - 44, 49, 'Page 1 of 1')
    c.showPage()
    c.save()
    return out.getvalue()


def raster(pdf: bytes, scanned: bool = False) -> Image.Image:
    document = pdfium.PdfDocument(pdf)
    page = document[0]
    bitmap = page.render(scale=2)
    result = bitmap.to_pil().convert('RGB').copy()
    bitmap.close()
    page.close()
    document.close()
    if scanned:
        result = ImageEnhance.Contrast(result.convert('L')).enhance(0.94).convert('RGB')
        rng = random.Random(41031)
        draw = ImageDraw.Draw(result)
        for _ in range(450):
            x, y = rng.randrange(result.width), rng.randrange(result.height)
            draw.point((x, y), fill=(212, 212, 212))
    return result


def image_pdf(image: Image.Image) -> bytes:
    from reportlab.lib.utils import ImageReader
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=A4, invariant=1, pageCompression=1)
    c.setTitle('Scanned invoice')
    c.drawImage(ImageReader(image), 0, 0, W, H)
    c.showPage()
    c.save()
    return output.getvalue()


def generate(output: Path) -> dict:
    vendors = {v['vendor_code']: v for v in read_rows('Vendors.csv')}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'pdfs').mkdir(exist_ok=True)
    (output / 'images').mkdir(exist_ok=True)
    entries = []
    pdf_bytes = {}

    def record(name, data, invoice, expected, family, precondition='Fresh scenario: referenced PO unused.', fixture_id=None, **extra):
        relative = ('pdfs/' if name.endswith('.pdf') else 'images/') + name
        (output / relative).write_bytes(data)
        fields = asdict(invoice)
        fields.pop('layout')
        fields.pop('vendor_label')
        fields.pop('include_vendor_identifiers')
        if not invoice.include_vendor_identifiers:
            fields['vendor'] = None
            fields['vendor_name'] = invoice.vendor_label or vendors[invoice.vendor]['legal_name']
        if invoice.tax_presentation == 'inclusive':
            # Only gross rate/amount are printed. Do not label derived net/tax
            # as if they were visible fields in the original source.
            fields['unit_price_gross'] = str((Decimal(invoice.unit_net) *
                (1 + Decimal(invoice.tax_rate)/100)).quantize(CENT, rounding=ROUND_HALF_UP))
            fields['unit_net'] = fields['net'] = fields['tax'] = None
        if extra.get('unreadable_total'):
            fields['total'] = None
        entries.append(dict(id=fixture_id or Path(name).stem, file=relative, sha256=digest(data), bytes=len(data),
            family=family, expected_decision=expected, precondition=precondition,
            expected_source_fields=fields, **extra))
        return data

    def pdf(name, invoice, expected='accepted', family='happy', **extra):
        data = make_pdf(invoice, vendors)
        pdf_bytes[name] = data
        record(name, data, invoice, expected, family, **extra)
        return data

    base = Invoice()
    happy = pdf('happy_full.pdf', base)
    pdf('vendor_alias_only.pdf', replace(base, number='INV-ALIAS-01', vendor_label='Acme Services',
        include_vendor_identifiers=False), family='vendor_matching',
        reason='Only the approved vendor alias is printed; no vendor code or tax identifier is supplied.')
    pdf('vendor_unknown_name.pdf', replace(base, number='INV-UNKNOWN-01', vendor_label='Northstar Office Services',
        include_vendor_identifiers=False), 'needs_review', 'vendor_matching',
        reason='Printed vendor name has no approved reference match; the PO reference must not substitute for vendor evidence.')
    record('duplicate_same_renamed.pdf', happy, base, 'blocked_duplicate', 'duplicates',
        precondition='First accept happy_full.pdf. Renaming leaves the file content unchanged.')
    pdf('duplicate_reexported.pdf', replace(base, layout='green'), 'blocked_duplicate', 'duplicates',
        precondition='First accept happy_full.pdf. Content hash changes, invoice identity stays the same.')
    pdf('other_vendor_same_number.pdf', replace(base, vendor='V-BETA', po='PO-BETA', description='Consulting services'),
        family='duplicates', precondition='Accept happy_full.pdf first; PO-BETA remains unused. Same number from a different vendor is legitimate.')
    pdf('conflicting_revision.pdf', replace(base, total='9500.00', net='9500.00', quantity='9.5'),
        'needs_review', 'duplicates', precondition='First accept happy_full.pdf; identical vendor/number but altered money requires investigation.')

    partial = replace(base, number='INV-PART-01', po='PO-PARTIAL', description='Consulting services',
        quantity='6', net='6000.00', total='6000.00')
    pdf('split_6000.pdf', partial, family='partial_billing')
    pdf('split_4000.pdf', replace(partial, number='INV-PART-02', quantity='4', net='4000.00', total='4000.00'),
        family='partial_billing', precondition='After split_6000.pdf ONLY: four authorised hours remain.')
    pdf('split_4500.pdf', replace(partial, number='INV-PART-03', quantity='4.5', net='4500.00', total='4500.00'),
        'needs_review', 'partial_billing', precondition='After split_6000.pdf ONLY; reset before this branch if split_4000 was already accepted.')
    pdf('ambiguous_no_po.pdf', replace(base, number='INV-AMB-01', po=None,
        description='Website design milestones', quantity='5', net='5000.00', total='5000.00'),
        'needs_review', 'ambiguous_po', expected_candidates=['PO-AMBIG-A', 'PO-AMBIG-B'])

    scan_invoice = replace(base, number='INV-SCAN-01')
    scan_image = raster(make_pdf(scan_invoice, vendors), scanned=True)
    record('scan_clean.pdf', image_pdf(scan_image), scan_invoice, 'accepted', 'uncertain_document',
        fixture_id='scan_clean_pdf', image_only=True)
    blurred = scan_image.copy()
    # Remove legibility ONLY in the payable value, preserving the label and page.
    # No hidden original text is embedded in the resulting image-only PDF.
    box = (int(334*2), int((H-(TOTAL_Y+10))*2), int((W-49)*2), int((H-(TOTAL_Y-14))*2))
    region = blurred.crop(box).filter(ImageFilter.GaussianBlur(12))
    region = ImageEnhance.Contrast(region).enhance(0.08)
    blurred.paste(region, box)
    record('scan_blurred_total.pdf', image_pdf(blurred), replace(scan_invoice, number='INV-SCAN-01'),
        'needs_review', 'uncertain_document', image_only=True, unreadable_total=True,
        precondition='Fresh scenario: do NOT first accept scan_clean.pdf; these are alternative source-quality branches of the same invoice.')

    for name, changed in [
        ('missing_number.pdf', replace(base, number=None)),
        ('missing_date.pdf', replace(base, number='INV-NODATE-01', date=None)),
        ('missing_total.pdf', replace(base, number='INV-NOTOTAL-01', total=None)),
    ]:
        pdf(name, changed, 'needs_review', 'uncertain_document')
    pdf('rounding_within.pdf', replace(base, number='INV-ROUND-01', total='9999.50', rounding='-0.50'), family='tolerance')
    pdf('rounding_outside.pdf', replace(base, number='INV-ROUND-02', total='9998.00', rounding='-2.00'), 'needs_review', 'tolerance')
    pdf('cap_over_by_050.pdf', replace(base, number='INV-CAP-01', total='10000.50', rounding='0.50'), 'needs_review', 'tolerance')
    tax = replace(base, number='INV-TAX-01', po='PO-TAX', description='Tax advisory services',
        tax='1800.00', total='11800.00', tax_rate='18', tax_presentation='exclusive')
    pdf('tax_separate.pdf', tax, family='tax')
    pdf('tax_inclusive.pdf', replace(tax, number='INV-TAX-02', tax_presentation='inclusive'), family='tax')
    pdf('tax_mismatch.pdf', replace(tax, number='INV-TAX-03', total='11700.00'), 'needs_review', 'tax')
    pdf('bundled_charges.pdf', replace(partial, number='INV-BUNDLE-01',
        description='Monthly consulting engagement (bundled)', quantity=None, unit='', unit_net=None),
        'needs_review', 'bundled_charges', test_id='V12',
        reason='Amount fits, but the source does not substantiate PO hour/quantity allocation.')
    race = replace(partial, po='PO-RACE', description='Load-test consulting services')
    for number, name in [('INV-RACE-01','race_a_6000.pdf'),('INV-RACE-02','race_b_6000.pdf')]:
        pdf(name, replace(race, number=number), 'one_accepted_one_needs_review', 'concurrency',
            precondition='Submit both race files concurrently to an unused PO-RACE. Either can win; only one commitment is allowed.')
    pdf('vendor_unapproved.pdf', replace(base, number='INV-HOLD-01', vendor='V-HOLD', po='PO-HOLD',
        description='Unapproved vendor services'), 'needs_review', 'vendor_status')
    pdf('currency_mismatch.pdf', replace(base, number='INV-USD-01', currency='USD'), 'needs_review', 'currency')

    image_out = io.BytesIO()
    raster(happy).save(image_out, format='PNG', optimize=True)
    record('duplicate_screenshot.png', image_out.getvalue(), base, 'blocked_duplicate', 'duplicates',
        precondition='First accept happy_full.pdf; screenshot has different bytes but the same invoice identity.')
    image_out = io.BytesIO()
    scan_image.save(image_out, format='JPEG', quality=88, optimize=True)
    record('scan_clean.jpg', image_out.getvalue(), scan_invoice, 'accepted', 'image_input',
        fixture_id='scan_clean_jpg',
        precondition='Fresh scenario. If scan_clean.pdf was accepted already, this must instead be a duplicate.')
    image_invoice = replace(base, number='INV-IMAGE-01')
    image_out = io.BytesIO()
    raster(make_pdf(image_invoice, vendors)).save(image_out, format='PNG', optimize=True)
    record('clean_invoice.png', image_out.getvalue(), image_invoice, 'accepted', 'image_input')

    manifest = dict(generator_version=GENERATOR_VERSION, synthetic=True,
        invoice_date='2026-10-31', currencies=['INR','USD'],
        warning='Expected outcomes are test metadata; never pass them to extraction or preprogram application decisions.',
        dependencies={x:version(x) for x in ['reportlab','pypdfium2','Pillow','pypdf']},
        scenario_sequences={
            'happy':['happy_full'],
            'duplicates':['happy_full','duplicate_same_renamed','duplicate_reexported','duplicate_screenshot','other_vendor_same_number','conflicting_revision'],
            'partial_fits':['split_6000','split_4000'],
            'partial_overbilling':['split_6000','split_4500'],
            'ambiguous':['ambiguous_no_po'],
            'unreadable':['scan_blurred_total'],
            'vendor_alias':['vendor_alias_only'],
            'vendor_unknown':['vendor_unknown_name'],
            'concurrency':['race_a_6000','race_b_6000'],
        }, fixtures=entries)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    verify(output, manifest)
    return manifest


def verify(output: Path, manifest: dict) -> None:
    by_id = {x['id']:x for x in manifest['fixtures']}
    assert len(by_id) == len(manifest['fixtures']), 'Fixture IDs must be unique'
    assert len({x['file'] for x in manifest['fixtures']}) == len(manifest['fixtures']), 'Fixture paths must be unique'
    for sequence in manifest['scenario_sequences'].values():
        assert all(fixture_id in by_id for fixture_id in sequence), 'Unknown fixture ID in scenario sequence'
    report = []
    for item in manifest['fixtures']:
        path = output/item['file']
        data = path.read_bytes()
        assert digest(data) == item['sha256'], path
        assert len(data) < 5*1024*1024, path
        if path.suffix == '.pdf':
            reader = PdfReader(io.BytesIO(data))
            assert len(reader.pages) == 1, path
            text = reader.pages[0].extract_text().strip()
            if item.get('image_only'):
                assert not text, f'Scan must have no hidden text: {path}'
            else:
                assert 'SYNTHETIC DEMO' in text, path
                vendor_code = item['expected_source_fields']['vendor']
                if vendor_code is not None:
                    assert vendor_code in text, path
                else:
                    assert item['expected_source_fields']['vendor_name'] in text, path
                    assert 'Vendor reference:' not in text and 'Tax registration:' not in text, path
                    assert not any(v['vendor_code'] in text or v['tax_registration_id'] in text
                                   for v in read_rows('Vendors.csv')), path
                    assert reader.metadata.author == item['expected_source_fields']['vendor_name'], path
                number = item['expected_source_fields']['number']
                if number:
                    assert number in text, path
        else:
            with Image.open(path) as image:
                assert image.format in ('JPEG','PNG'), path
                assert image.width > 1000 and image.height > 1000, path
        report.append(f"- PASS: {item['file']} — {len(data)} bytes, SHA-256 verified")
    assert by_id['happy_full']['sha256'] == by_id['duplicate_same_renamed']['sha256']
    assert by_id['happy_full']['sha256'] != by_id['duplicate_reexported']['sha256']
    assert by_id['happy_full']['sha256'] != by_id['duplicate_screenshot']['sha256']
    assert len(manifest['fixtures']) == 30
    assert sum(x['file'].endswith('.pdf') for x in manifest['fixtures']) == 27
    (output/'VERIFICATION.md').write_text('# Fixture verification\n\n27 PDFs and 3 images generated and structurally checked. All 30 fixture IDs and paths are unique, and scenario sequences reference existing IDs. This is not an end-to-end extraction/decision result.\n\n'+'\n'.join(report)+'\n\nExact renamed duplicate has identical bytes; re-export and screenshot have different hashes. Scan PDFs contain images only, with no hidden text. Alias-only and unknown-name PDFs print neither a vendor code nor tax identifier, and use the printed vendor name in their author metadata. Scenario outcomes require the stated initial conditions; reset between independent branches.\n')


def generate_demo_pack(output: Path, pack: str) -> dict:
    """Independent, immutable demo budget; expected outcomes never enter PDFs."""
    if not re.fullmatch(r'[A-Z][A-Z0-9]{0,11}', pack):
        raise ValueError('Pack must be 1-12 uppercase letters/digits, starting with a letter')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output is not empty. Choose a new pack or an empty output directory.')
    output.mkdir(parents=True, exist_ok=True)
    vendors = {v['vendor_code']: v for v in read_rows('Vendors.csv')}
    prefix = f'PO-DEMO-{pack}-'
    descriptions = {
        'FULL': f'Office support - demo {pack}',
        'PARTIAL': f'Consulting services - demo {pack}',
        'SCAN': f'Document support - demo {pack}',
        'AMBIG-A': f'Website design - demo {pack}',
        'AMBIG-B': f'Website design - demo {pack}',
    }
    pos, lines = [], []
    for suffix, description in descriptions.items():
        po = prefix + suffix
        pos.append(dict(po_code=po, vendor_code='V-ACME', currency='INR',
                        authorized_gross='10000.00', status='open',
                        billing_mode='full' if suffix in ('FULL','SCAN') else 'partial'))
        lines.append(dict(po_code=po, line_code='SERVICE', description=description,
                          quantity='10.0000', unit='hour', unit_net='1000.00', tax_rate_percent='0.00'))
    for name, rows in [('PurchaseOrders',pos),('POLines',lines)]:
        with (output/(name+'.csv')).open('w', newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    base = Invoice(number=f'INV-DEMO-{pack}-FULL-01',po=prefix+'FULL',description=descriptions['FULL'])
    partial = replace(base,number=f'INV-DEMO-{pack}-PART-01',po=prefix+'PARTIAL',
                      description=descriptions['PARTIAL'],quantity='6',net='6000.00',total='6000.00')
    fixtures=[]
    def add(filename, invoice, outcome, prerequisite, title, data=None):
        data = data if data is not None else make_pdf(invoice,vendors)
        (output/filename).write_bytes(data)
        fixtures.append(dict(file=filename,title=title,expected=outcome,prerequisite=prerequisite,
                             sha256=digest(data),bytes=len(data),invoice_number=invoice.number,po_code=invoice.po))
        return data
    happy=add('01_clean_invoice.pdf',base,'Accepted when all nine checks pass','Use this first, with an unused pack.','Clean PDF')
    add('02_duplicate_invoice.pdf',base,'Blocked duplicate','First accept 01_clean_invoice.pdf.','Duplicate',happy)
    add('03_partial_6000.pdf',partial,'Accepted; INR 4,000 remains','Use before the two partial-billing checks below.','Partial invoice')
    add('04_partial_over_4500.pdf',replace(partial,number=f'INV-DEMO-{pack}-PART-OVER',quantity='4.5',net='4500.00',total='4500.00'),
        'Needs review; balance is insufficient','After 03_partial_6000.pdf, before 05_partial_remainder_4000.pdf.','Over the remaining balance')
    add('05_partial_remainder_4000.pdf',replace(partial,number=f'INV-DEMO-{pack}-PART-FINAL',quantity='4',net='4000.00',total='4000.00'),
        'Accepted if the remaining INR 4,000 is unused','Optional: use after demonstrating the INR 4,500 hold.','Remaining balance fits')
    add('06_ambiguous_po.pdf',replace(base,number=f'INV-DEMO-{pack}-AMB-01',po=None,description=descriptions['AMBIG-A'],quantity='5',net='5000.00',total='5000.00'),
        'Needs review; two exact PO candidates','No printed PO. Admin may choose an exact candidate, revalidate and explicitly accept.','Ambiguous purchase order')
    scan_invoice=replace(base,number=f'INV-DEMO-{pack}-SCAN-01',po=prefix+'SCAN',description=descriptions['SCAN'])
    scan=raster(make_pdf(scan_invoice,vendors),scanned=True)
    box=(int(334*2),int((H-(TOTAL_Y+10))*2),int((W-49)*2),int((H-(TOTAL_Y-14))*2))
    blurred=ImageEnhance.Contrast(scan.crop(box).filter(ImageFilter.GaussianBlur(12))).enhance(0.08)
    scan.paste(blurred,box)
    add('07_blurred_total.pdf',scan_invoice,'Needs review; printed payable is unreadable',
        'Independent scan PO. Other visible amounts must not substitute for a printed payable.','Unreadable payable',image_pdf(scan))
    manifest={'pack':pack,'synthetic':True,'generator_version':'demo-pack-v1','fixtures':fixtures,
              'reference_rows':{'PurchaseOrders':pos,'POLines':lines}}
    guide='# Demo pack '+pack+'\n\nSynthetic documents. No payments are executed. Follow the order below.\n\n'
    guide+='Each acceptance consumes its PO budget. Reusing an accepted file must be blocked; prepare another pack for a fresh rehearsal. The original ledger is never reset.\n\n'
    for f in fixtures:guide+=f"- {f['file']}: {f['expected']}. {f['prerequisite']}\n"
    (output/'SCENARIOS.md').write_text(guide)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for item in fixtures:
        reader=PdfReader(output/item['file'])
        assert len(reader.pages)==1
        text=reader.pages[0].extract_text().strip()
        assert not text if item['file']=='07_blurred_total.pdf' else item['invoice_number'] in text
    assert fixtures[0]['sha256']==fixtures[1]['sha256']
    assert len({f['invoice_number'] for f in fixtures})==6
    with ZipFile(output/f'invoice-demo-{pack}.zip','w',ZIP_DEFLATED) as archive:
        for filename in [f['file'] for f in fixtures]+['SCENARIOS.md','manifest.json']:
            archive.write(output/filename,filename)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--pack', help='Create a fresh demo pack, e.g. B, C or D; never reset an existing pack')
    args = parser.parse_args()
    target=args.output_dir or (ROOT/'tests'/'fixtures'/'demo_packs'/args.pack if args.pack else ROOT/'tests'/'fixtures')
    result = generate_demo_pack(target.resolve(),args.pack) if args.pack else generate(target.resolve())
    print(json.dumps({'generated':len(result['fixtures']), 'pack':args.pack,
                      'output_dir':str(target.resolve())}, indent=2))

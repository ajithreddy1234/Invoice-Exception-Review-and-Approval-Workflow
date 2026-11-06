"""Eight synthetic messy inputs; offline only, never a source of decisions.

Two ReportLab layout families and real LibreOffice Writer ODT-to-PDF exports.
The photo-like image is simulated, not a claimed camera capture. No proprietary
Zoho/Stripe/Canva export or live model verification is implied.
"""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile,ZIP_DEFLATED,ZIP_STORED
from html import escape
import argparse,json,subprocess,tempfile

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
from reportlab.lib.styles import getSampleStyleSheet
from PIL import Image,ImageEnhance
import pypdfium2 as pdfium

ROOT=Path(__file__).resolve().parents[1]


def spec(number,**changes):
    return dict(number=number,vendor='Beta Consulting Pvt Ltd',po='PO-BETA',date='2026-10-31',
        description='Consulting services',quantity='10',unit='1000.00',net='10000.00',tax='0.00',rate='0',total='10000.00') | changes


def money(value):return f'{float(value):,.2f}'


def card(path,s):
    c=canvas.Canvas(str(path),pagesize=A4,invariant=1)
    c.setFillColor(colors.HexColor('#234c49'));c.rect(0,0,24,A4[1],fill=1,stroke=0)
    c.setFillColor(colors.HexColor('#234c49'));c.setFont('Helvetica-Bold',28);c.drawString(52,774,'INVOICE')
    c.setFont('Helvetica-Bold',17);c.drawString(52,735,s['vendor'])
    c.setFillColor(colors.black);c.setFont('Helvetica',11)
    for y,line in zip(range(698,586,-24),[f"Invoice number: {s['number']}",f"Invoice date: {s['date']}",f"Purchase order: {s['po']}",'Currency: INR','Bill to: Example Procurement Company']):c.drawString(52,y,line)
    c.setFillColor(colors.HexColor('#edf2ec'));c.rect(48,438,493,112,fill=1,stroke=0)
    c.setFillColor(colors.black);c.setFont('Helvetica-Bold',13);c.drawString(62,523,s['description'])
    c.setFont('Helvetica',11)
    for y,line in zip((497,475,453),[f"Quantity: {s['quantity']} hour",f"Unit price (net): INR {money(s['unit'])}",f"Line net: INR {money(s['net'])}"]):c.drawString(62,y,line)
    for y,line in zip((389,363,316,290),[f"Subtotal (net): INR {money(s['net'])}",f"GST ({s['rate']}%): INR {money(s['tax'])}",'TOTAL PAYABLE',f"INR {money(s['total'])}"]):
        c.setFont('Helvetica-Bold' if y<330 else 'Helvetica',19 if y==290 else 12);c.drawString(62,y,line)
    c.setFont('Helvetica',9);c.drawString(52,80,'Synthetic test invoice - no real supplier or payment instruction.');c.save()


def table(path,s):
    styles=getSampleStyleSheet();story=[]
    for text,style in [(s['vendor'],'Title'),('TAX INVOICE / SERVICES','Heading2'),(f"Invoice number: {s['number']}",'Normal'),(f"Invoice date: {s['date']} | Purchase order: {s['po']}",'Normal'),('Currency: INR | Bill to: Example Procurement Company','Normal')]:story.extend([Paragraph(text,styles[style]),Spacer(1,14)])
    data=[['Service','Qty / unit','Unit net (INR)','Line net (INR)'],[s['description'],s['quantity']+' hour',money(s['unit']),money(s['net'])]]
    t=Table(data,colWidths=[210,85,100,100]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#233854')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('BOTTOMPADDING',(0,0),(-1,-1),14),('TOPPADDING',(0,0),(-1,-1),14),('GRID',(0,0),(-1,-1),.5,colors.HexColor('#ccd3dc'))]));story.extend([Spacer(1,22),t,Spacer(1,30)])
    for line in [f"Subtotal (net): INR {money(s['net'])}",f"GST ({s['rate']}%): INR {money(s['tax'])}",f"TOTAL PAYABLE INR {money(s['total'])}",'Synthetic test invoice - no payment instruction.']:
        story.extend([Paragraph(line,styles['Heading2'] if line.startswith('TOTAL') else styles['Normal']),Spacer(1,16)])
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=50,rightMargin=50,topMargin=55,bottomMargin=55).build(story)


def writer(path,s,work):
    paragraphs=[('Title','STATEMENT OF PROFESSIONAL SERVICES'),('Heading',s['vendor']),
        ('Text',f"Invoice number: {s['number']}"),('Text',f"Invoice date: {s['date']}"),
        ('Text',f"Purchase order: {s['po']}"),('Text','Currency: INR'),('Text','Bill to: Example Procurement Company'),
        ('Heading','Charges for the period'),('Text',s['description']),('Text',f"Quantity: {s['quantity']} hour"),
        ('Text',f"Unit price (net): INR {money(s['unit'])}"),('Text',f"Line net: INR {money(s['net'])}"),
        ('Text',f"Subtotal (net): INR {money(s['net'])}"),('Text',f"GST ({s['rate']}%): INR {money(s['tax'])}"),
        ('Heading','TOTAL PAYABLE'),('Heading',f"INR {money(s['total'])}"),('Text','Synthetic test invoice. No payment details.')]
    body=''.join(f'<text:p text:style-name="{style}">{escape(text)}</text:p>' for style,text in paragraphs)
    namespace='xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"'
    content=f'''<?xml version="1.0" encoding="UTF-8"?><office:document-content {namespace} office:version="1.2"><office:automatic-styles>
      <style:style style:name="Title" style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0.5cm"/><style:text-properties fo:font-size="22pt" fo:font-weight="bold" fo:color="#40516b"/></style:style>
      <style:style style:name="Heading" style:family="paragraph"><style:paragraph-properties fo:margin-top="0.4cm" fo:margin-bottom="0.3cm"/><style:text-properties fo:font-size="15pt" fo:font-weight="bold"/></style:style>
      <style:style style:name="Text" style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0.25cm"/><style:text-properties fo:font-size="11pt"/></style:style>
      </office:automatic-styles><office:body><office:text>{body}</office:text></office:body></office:document-content>'''
    manifest='''<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>'''
    odt=work/(path.stem+'.odt')
    with ZipFile(odt,'w',ZIP_DEFLATED) as z:
        z.writestr('mimetype','application/vnd.oasis.opendocument.text',compress_type=ZIP_STORED);z.writestr('content.xml',content);z.writestr('META-INF/manifest.xml',manifest)
    subprocess.run(['soffice','--headless','-env:UserInstallation='+str((work/'lo-profile').as_uri()),'--convert-to','pdf','--outdir',str(path.parent),str(odt)],capture_output=True,timeout=90,check=True)
    if not path.is_file():raise RuntimeError('Writer PDF export missing')


def raster(path):
    with pdfium.PdfDocument(path.read_bytes()) as doc:
        page=doc[0];bitmap=page.render(scale=2)
        try:return bitmap.to_pil().convert('RGB')
        finally:bitmap.close();page.close()


def generate(destination):
    destination.mkdir(parents=True,exist_ok=True)
    entries=[]
    def add(name,s,engine,outcome,create):
        create(destination/name,s);entries.append({'file':name,'mime':'application/pdf','engine':engine,'synthetic':True,'invoice_number':s['number'],'po':s['po'],'printed_date':s['date'],'expected_with_grounded_candidate':outcome,'fields':s})
    with tempfile.TemporaryDirectory(prefix='invoice-layouts-') as tmp:
        work=Path(tmp)
        add('01_card_invoice.pdf',spec('INV-LAYOUT-CARD-01'),'ReportLab canvas','eligible',card)
        partial=spec('INV-LAYOUT-TABLE-01');partial.update(vendor='Acme Services Pvt Ltd',po='PO-PARTIAL',quantity='6',net='6000.00',total='6000.00')
        add('02_table_invoice.pdf',partial,'ReportLab Platypus','eligible',table)
        tax=spec('INV-LAYOUT-WRITER-01');tax.update(vendor='Acme Services Pvt Ltd',po='PO-TAX',description='Tax advisory services',rate='18',tax='1800.00',total='11800.00')
        add('03_writer_tax.pdf',tax,'LibreOffice Writer ODT export','eligible',lambda p,s:writer(p,s,work))
        for name,number,date in [('04_writer_slash_date.pdf','INV-LAYOUT-DATE-01','13/10/2026'),('05_writer_ambiguous_date.pdf','INV-LAYOUT-DATE-02','05/06/2026')]:
            s=spec(number);s['date']=date
            add(name,s,'LibreOffice Writer ODT export','needs_review',lambda p,s:writer(p,s,work))
        image=raster(destination/'03_writer_tax.pdf');image.save(destination/'06_scan_statement.pdf','PDF',resolution=144);image.close()
        entries.append({'file':'06_scan_statement.pdf','mime':'application/pdf','engine':'Rasterized Writer export (no text layer)','synthetic':True,'invoice_number':tax['number'],'po':tax['po'],'expected_with_grounded_candidate':'eligible_or_review','fields':tax,'duplicate_identity_of':'03_writer_tax.pdf'})
        photo=spec('INV-LAYOUT-PHOTO-01');card(work/'photo.pdf',photo);image=raster(work/'photo.pdf')
        image=ImageEnhance.Contrast(image).enhance(.83).rotate(2,resample=Image.Resampling.BICUBIC,expand=True,fillcolor='white')
        image=ImageEnhance.Brightness(image).enhance(.92);image.save(destination/'07_photo_like.jpg',quality=80);image.close()
        entries.append({'file':'07_photo_like.jpg','mime':'image/jpeg','engine':'Simulated rotated photograph from ReportLab','synthetic':True,'invoice_number':photo['number'],'po':photo['po'],'expected_with_grounded_candidate':'eligible_or_review','fields':photo})
        wrong=spec('INV-LAYOUT-TOTAL-01');wrong['total']='9700.00'
        add('08_inconsistent_payable.pdf',wrong,'ReportLab canvas','needs_review',card)
    for entry in entries:
        data=(destination/entry['file']).read_bytes();entry.update(sha256=sha256(data).hexdigest(),bytes=len(data))
    report={'synthetic':True,'provenance':'Generated locally with ReportLab and actual LibreOffice Writer exports; no third-party branded export or real camera capture claimed.','reference_dataset':'tests/reference_data; use an isolated fresh ledger per independent case','fixtures':entries}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'tests/fixtures/layouts');args=p.parse_args()
    report=generate(args.output.resolve());print(json.dumps({'fixtures':len(report['fixtures']),'output':str(args.output),'synthetic':True}))

"""Offline fixture tooling never exposes samples through the application."""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

from app.auth import Actor,current_actor
from app.config import Settings
from tools.demo_packs import ASSETS,catalog
from app.main import create_app

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_demo',ROOT/'scripts/prepare_demo.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


def test_packs_have_separate_budget_identities_and_only_intended_duplicates():
    packs=catalog();assert {'B','C'}<={p['pack'] for p in packs}
    identities=[];po_codes=[]
    for p in packs:
        files=p['fixtures'];extra=int(any(f['file']=='08_admin_line_review.pdf' for f in files));assert len(files)==7+extra
        assert files[0]['sha256']==files[1]['sha256']
        assert len({f['invoice_number'] for f in files})==6+extra
        identities.append({f['invoice_number'] for f in files})
        po_codes.append({x['po_code'] for x in p['reference_rows']['PurchaseOrders']})
        assert len(po_codes[-1])==5+extra
        for f in files:
            data=(ASSETS/p['pack']/f['file']).read_bytes();assert sha256(data).hexdigest()==f['sha256']
            pages=PdfReader(io.BytesIO(data)).pages;assert len(pages)==1
            text=pages[0].extract_text()
            if f['file']=='07_blurred_total.pdf':assert not text.strip()
            else:
                assert f['invoice_number'] in text
                assert f['expected'] not in text
        with ZipFile(ASSETS/p['pack']/f"invoice-demo-{p['pack']}.zip") as archive:
            assert set(archive.namelist())=={f['file'] for f in files}|{'SCENARIOS.md','manifest.json'}
    for i in range(len(packs)):
        for j in range(i):
            assert not identities[i]&identities[j]
            assert not po_codes[i]&po_codes[j]


def test_generator_can_create_the_next_pack_without_overwriting_one(tmp_path):
    import sys
    sys.path.insert(0,str(ROOT/'tools'))
    from generate_fixtures import generate_demo_pack
    folder=tmp_path/'D';p=generate_demo_pack(folder,'D')
    assert len(p['fixtures'])==7 and all(row['po_code'].startswith('PO-DEMO-D-') for row in p['reference_rows']['PurchaseOrders'])
    original=(folder/'01_clean_invoice.pdf').read_bytes()
    with pytest.raises(ValueError,match='not empty'):generate_demo_pack(folder,'D')
    assert (folder/'01_clean_invoice.pdf').read_bytes()==original
    with pytest.raises(ValueError,match='Pack must'):generate_demo_pack(tmp_path/'invalid','../D')


def test_additive_reference_planning_is_idempotent_and_preserves_numeric_equivalence():
    p=catalog()[0];name='PurchaseOrders';headers=prepare.HEADERS[name]
    rows=[list(headers)]+[[record[h] for h in headers] for record in p['reference_rows'][name]]
    rows[1][3]=10000.0
    assert prepare.additions(rows,p['reference_rows'][name],headers)==[]
    assert len(prepare.additions([list(headers)],p['reference_rows'][name],headers))==5
    rows[1][3]=9999
    with pytest.raises(ValueError,match='Existing demo reference differs'):
        prepare.additions(rows,p['reference_rows'][name],headers)


def test_preparation_preserves_validation_and_rejects_formula_or_chip_exemplars():
    headers=('status',)
    prepare.validate_exemplar([{'dataValidation':{'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':'open'}]}}}],[['open']],headers)
    with pytest.raises(ValueError,match='dropdown'):
        prepare.validate_exemplar([{'dataValidation':{'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':'closed'}]}}}],[['open']],headers)
    with pytest.raises(ValueError,match='Structured/formula'):
        prepare.validate_exemplar([{'userEnteredValue':{'formulaValue':'=1'}}],[['open']],headers)


@pytest.mark.parametrize('role',[None,'user','admin'])
def test_sample_routes_are_absent_even_for_authenticated_users(role):
    settings=Settings(_env_file=None,database_url='',supabase_url='',supabase_publishable_key='',
                      supabase_secret_key='',google_application_credentials='',google_spreadsheet_id='',
                      gemini_api_key='',gemini_model='',worker_enabled=False,auto_import_on_startup=False)
    app=create_app(settings)
    if role:
        app.dependency_overrides[current_actor]=lambda:Actor(UUID('11111111-1111-4111-8111-111111111111'),'Workspace user',role)
    with TestClient(app) as client:
        for path in ('/api/demo','/api/demo/packs/B/download','/api/demo/packs/B/files/01_clean_invoice.pdf'):
            response=client.get(path)
            assert response.status_code==404
            assert response.headers['cache-control']=='no-store'


def test_admin_review_pack_has_an_independent_po_and_preserves_source_wording(tmp_path):
    import sys
    sys.path.insert(0,str(ROOT/'tools'))
    from generate_fixtures import generate_demo_pack
    pack=generate_demo_pack(tmp_path/'E','E',admin_review=True)
    assert len(pack['fixtures'])==8 and len(pack['reference_rows']['PurchaseOrders'])==6
    item=pack['fixtures'][-1];assert item['po_code']=='PO-DEMO-E-REVIEW'
    printed=PdfReader(tmp_path/'E'/item['file']).pages[0].extract_text()
    assert 'Office ops support - demo E' in printed and 'Office operations support - demo E' not in printed
    line=next(x for x in pack['reference_rows']['POLines'] if x['po_code']==item['po_code'])
    assert line['description']=='Office operations support - demo E'
    assert sha256((tmp_path/'E'/item['file']).read_bytes()).hexdigest()==item['sha256']

"""Authenticated synthetic samples; no reset, approval shortcut or fixture extraction."""
from hashlib import sha256
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb

from .auth import Actor, current_actor

router=APIRouter()
ASSETS=Path(__file__).parent/'demo_assets'/'packs'


def catalog():
    result=[]
    for path in sorted(ASSETS.glob('*/manifest.json')):
        data=json.loads(path.read_text())
        if data['pack']!=path.parent.name:
            raise RuntimeError('DEMO_ASSET_INVALID')
        result.append(data)
    return result


def pack_data(pack):
    found=next((item for item in catalog() if item['pack']==pack),None)
    if found is None:
        raise HTTPException(404,'DEMO_PACK_NOT_FOUND')
    return found


DEMO_SQL='''
WITH active AS (
 SELECT v.* FROM app.runtime_state t JOIN app.reference_versions v
 ON v.id=t.active_reference_version_id WHERE t.singleton
), wanted AS (
 SELECT * FROM jsonb_to_recordset(%s::jsonb) AS w(pack text,po_code text,
 description text,billing_mode text)
)
SELECT (SELECT valid_until>now() FROM active) AS fresh,
 coalesce((SELECT jsonb_agg(jsonb_build_object('pack',w.pack,'po_code',w.po_code,
 'prepared',coalesce(p.vendor_code='V-ACME' AND p.currency='INR' AND p.status='open'
 AND p.billing_mode=w.billing_mode AND p.authorized_gross_minor=1000000
 AND l.line_code='SERVICE' AND l.description=w.description AND l.quantity=10
 AND l.unit='hour' AND l.unit_net_minor=100000 AND l.tax_rate_bps=0,false),
 'used',EXISTS(SELECT 1 FROM app.acceptances a WHERE a.po_code=w.po_code)))
 FROM wanted w LEFT JOIN active v ON true LEFT JOIN app.reference_pos p
 ON p.reference_version_id=v.id AND p.po_code=w.po_code
 LEFT JOIN app.reference_lines l ON l.reference_version_id=v.id AND l.po_code=w.po_code
 AND l.line_code='SERVICE'),'[]') AS rows
'''


@router.get('/api/demo')
def demo_catalog(request: Request,actor: Actor=Depends(current_actor)):
    packs=catalog();wanted=[]
    for pack in packs:
        for po,line in zip(pack['reference_rows']['PurchaseOrders'],pack['reference_rows']['POLines']):
            wanted.append({'pack':pack['pack'],'po_code':po['po_code'],
                           'description':line['description'],'billing_mode':po['billing_mode']})
    state=request.app.state.db.read_one(DEMO_SQL,(Jsonb(wanted),)) or {}
    rows=state.get('rows',[])
    return {'reference_fresh':bool(state.get('fresh')),'packs':[
        {'pack':p['pack'],'prepared':len([r for r in rows if r['pack']==p['pack'] and r['prepared']])==len(p['reference_rows']['PurchaseOrders']),
         'used':any(r['used'] for r in rows if r['pack']==p['pack']),
         'download_url':f"/api/demo/packs/{p['pack']}/download",
         'fixtures':[{k:f[k] for k in ('file','title','expected','prerequisite')} for f in p['fixtures']]}
        for p in packs]}


@router.get('/api/demo/packs/{pack}/download')
def download_pack(pack:str,actor:Actor=Depends(current_actor)):
    data=pack_data(pack)
    return FileResponse(ASSETS/data['pack']/f'invoice-demo-{pack}.zip',
                        media_type='application/zip',filename=f'invoice-demo-{pack}.zip')


@router.get('/api/demo/packs/{pack}/files/{filename}')
def download_sample(pack:str,filename:str,actor:Actor=Depends(current_actor)):
    data=pack_data(pack)
    entry=next((f for f in data['fixtures'] if f['file']==filename),None)
    if entry is None or Path(filename).name!=filename:
        raise HTTPException(404,'DEMO_FILE_NOT_FOUND')
    path=ASSETS/pack/filename
    if sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
        raise HTTPException(503,'DEMO_ASSET_INTEGRITY_ERROR')
    return FileResponse(path,media_type='application/pdf',filename=filename)

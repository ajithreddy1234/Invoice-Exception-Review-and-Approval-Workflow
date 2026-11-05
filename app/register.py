"""Ownership-scoped invoice search and stable keyset pagination."""
import base64
import binascii
from datetime import datetime
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from .auth import verified_user_id
from .workspace import INVOICE_SCOPE_SQL

router=APIRouter()
Status=Literal['all','review_queue','received','processing','accepted','needs_review',
               'blocked_duplicate','rejected','processing_failed','reference_hold','expired']


def decode_cursor(value):
    if value is None:
        return None,None
    try:
        data=json.loads(base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True))
        if not isinstance(data,dict) or set(data)!={'at','id'}:
            raise ValueError
        at=datetime.fromisoformat(str(data['at']))
        if at.tzinfo is None:
            raise ValueError
        return at,UUID(str(data['id']))
    except (ValueError,TypeError,KeyError,binascii.Error):
        raise HTTPException(422,'INVALID_INVOICE_CURSOR') from None


def encode_cursor(row):
    data=json.dumps({'at':row['created_at'],'id':row['id']},separators=(',',':')).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


REGISTER_SQL=INVOICE_SCOPE_SQL+r'''
, matched AS MATERIALIZED (
 SELECT * FROM named n WHERE
 (%s='all' OR n.status=%s OR (%s='review_queue' AND n.status IN ('needs_review','reference_hold')))
 AND (%s='all' OR n.vendor_code=%s OR (%s='unmatched' AND n.vendor_code IS NULL))
 AND strpos(lower(concat_ws(' ',n.original_filename,n.invoice_number,n.vendor_name,n.po_code)),lower(%s))>0
), candidates AS (
 SELECT * FROM matched WHERE (%s::timestamptz IS NULL OR (created_at,id)<(%s::timestamptz,%s::uuid))
 ORDER BY created_at DESC,id DESC LIMIT %s
), page AS (
 SELECT * FROM candidates ORDER BY created_at DESC,id DESC LIMIT %s
)
SELECT (SELECT to_jsonb(u) FROM actor u) AS actor,
 coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.created_at DESC,p.id DESC) FROM page p),'[]') AS items,
 (SELECT count(*) FROM matched) AS total_count,
 (SELECT count(*) FROM candidates)>%s AS has_more,
 now() AS generated_at
'''


@router.get('/api/invoices')
def invoice_register(request:Request,status:Status='all',vendor:str=Query('all',max_length=100),
                     search:str=Query('',max_length=200),cursor:str|None=Query(None,max_length=512),
                     limit:int=Query(25,ge=1,le=100),user_id=Depends(verified_user_id)):
    at,identifier=decode_cursor(cursor)
    row=request.app.state.db.read_one(REGISTER_SQL,(user_id,status,status,status,vendor,vendor,vendor,
        search.strip(),at,at,identifier,limit+1,limit,limit))
    if not row or not row['actor']:
        raise HTTPException(403,'ACCOUNT_DISABLED_OR_UNPROVISIONED')
    items=row['items']
    return {'items':items,'total_count':row['total_count'],'page_size':limit,
            'next_cursor':encode_cursor(items[-1]) if row['has_more'] and items else None,
            'scope':'company' if row['actor']['role']=='admin' else 'your_invoices',
            'generated_at':row['generated_at']}

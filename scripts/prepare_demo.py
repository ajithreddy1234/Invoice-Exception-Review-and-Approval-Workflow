#!/usr/bin/env python3
"""Plan/apply additive synthetic PO rows to the configured invoice Sheet.

Default is read-only. --apply copies only exemplar formatting/validation, appends
literal rows atomically, verifies them, then activates the normal DB import.
It never edits AcceptedInvoices, deletes ledger rows or resets commitments.
"""
from __future__ import annotations
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.db import Database
from app.demo import pack_data
from app.procurement import HEADERS, SheetsGateway, parse_reference, import_reference

NUMERIC={'authorized_gross','quantity','unit_net','tax_rate_percent'}


def normalized(row,headers):
    values=[]
    for index,key in enumerate(headers):
        value=row[index] if index<len(row) else ''
        values.append(Decimal(str(value)) if key in NUMERIC else ' '.join(str(value).split()))
    return tuple(values)


def additions(existing,desired,headers):
    """Return missing rows, reject a same-code conflict; never overwrite it."""
    if tuple(existing[0])!=tuple(headers):
        raise ValueError('Reference headers differ from the supported schema')
    keys=(0,1) if 'line_code' in headers else (0,)
    seen={}
    for row in existing[1:]:
        if not any(x not in ('',None) for x in row):continue
        key=tuple(str(row[i]).strip() for i in keys)
        if key in seen:raise ValueError('Duplicate reference identity in Sheet')
        seen[key]=normalized(row,headers)
    result=[]
    for record in desired:
        row=[record[h] for h in headers];key=tuple(str(row[i]).strip() for i in keys)
        canonical=normalized(row,headers)
        if key in seen:
            if seen[key]!=canonical:raise ValueError('Existing demo reference differs; choose a new pack ID')
        else:
            seen[key]=canonical;result.append(row)
    return result


def validate_exemplar(cells,rows,headers):
    for index,key in enumerate(headers):
        cell=cells[index] if index<len(cells) else {}
        if cell.get('chipRuns') or 'formulaValue' in cell.get('userEnteredValue',{}):
            raise ValueError('Structured/formula reference cells require manual preparation')
        rule=cell.get('dataValidation')
        if not rule:continue
        condition=rule.get('condition',{});kind=condition.get('type')
        if kind!='ONE_OF_LIST':raise ValueError('Unsupported reference validation; prepare this pack manually')
        allowed={v.get('userEnteredValue') for v in condition.get('values',[])}
        if any(str(row[index]) not in allowed for row in rows):
            raise ValueError('New reference violates existing dropdown validation')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packs',nargs='+',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();settings=Settings()
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials
    report={'applied':False,'packs':args.packs,'changes':[]}
    try:
        packs=[pack_data(p) for p in dict.fromkeys(args.packs)]
        credentials=Credentials.from_service_account_file(settings.google_application_credentials,
          scopes=['https://www.googleapis.com/auth/spreadsheets'])
        base='https://sheets.googleapis.com/v4/spreadsheets/'+settings.google_spreadsheet_id
        with AuthorizedSession(credentials,refresh_timeout=20) as session:
            def api(method,path='',**kwargs):
                r=session.request(method,base+path,timeout=20,max_allowed_time=20,**kwargs)
                if r.status_code!=200:raise RuntimeError('GOOGLE_SHEETS_OPERATION_FAILED')
                return r.json()
            meta=api('GET',params={'fields':'spreadsheetId,properties(title),sheets(properties,tables)'})
            tabs={s['properties']['title']:s for s in meta['sheets']}
            gateway=SheetsGateway(settings.google_spreadsheet_id,settings.google_application_credentials)
            before=gateway.read_reference()
            wanted={name:[row for pack in packs for row in pack['reference_rows'][name]]
                    for name in ('PurchaseOrders','POLines')}
            batch=[]
            for name,records in wanted.items():
                headers=HEADERS[name];rows=additions(before[name],records,headers)
                if not rows:continue
                sheet=tabs[name];props=sheet['properties'];sid=props['sheetId'];start=len(before[name]);width=len(headers)
                if sheet.get('tables'):raise ValueError('Native tables require manual pack preparation')
                if start<2:raise ValueError('A complete literal reference exemplar is required')
                exemplar=api('GET',params=[('ranges',f"'{name}'!A{start}:{chr(64+width)}{start}"),
                  ('includeGridData','true'),('fields','sheets(data(rowData(values(userEnteredValue,effectiveValue,dataValidation,chipRuns,userEnteredFormat))))')])
                cells=exemplar['sheets'][0]['data'][0]['rowData'][0].get('values',[])
                validate_exemplar(cells,rows,headers)
                end=start+len(rows)
                if end>props['gridProperties']['rowCount']:
                    batch.append({'appendDimension':{'sheetId':sid,'dimension':'ROWS','length':end-props['gridProperties']['rowCount']}})
                source={'sheetId':sid,'startRowIndex':start-1,'endRowIndex':start,'startColumnIndex':0,'endColumnIndex':width}
                dest={'sheetId':sid,'startRowIndex':start,'endRowIndex':end,'startColumnIndex':0,'endColumnIndex':width}
                for paste in ('PASTE_FORMAT','PASTE_DATA_VALIDATION'):
                    batch.append({'copyPaste':{'source':source,'destination':dest,'pasteType':paste}})
                values=[{'values':[{'userEnteredValue':{'numberValue':float(v)} if headers[i] in NUMERIC else {'stringValue':str(v)}} for i,v in enumerate(row)]} for row in rows]
                batch.append({'updateCells':{'range':dest,'rows':values,'fields':'userEnteredValue'}})
                batch.append({'autoResizeDimensions':{'dimensions':{'sheetId':sid,'dimension':'COLUMNS','startIndex':0,'endIndex':1}}})
                report['changes'].append({'sheet':name,'range':f'A{start+1}:{chr(64+width)}{end}','added_rows':len(rows)})
            # Validate the combined import before publishing any master data.
            combined={name:[*values] for name,values in before.items()}
            for name,records in wanted.items():combined[name]+=additions(before[name],records,HEADERS[name])
            parse_reference(combined)
            if args.apply:
                if gateway.read_reference()!=before:raise ValueError('Reference data changed during planning; rerun')
                if batch:api('POST',':batchUpdate',json={'requests':batch})
                after=gateway.read_reference()
                for name,records in wanted.items():
                    if after[name][:len(before[name])]!=before[name] or additions(after[name],records,HEADERS[name]):
                        raise RuntimeError('DEMO_REFERENCE_READBACK_FAILED')
                snapshot=parse_reference(after);db=Database(settings.database_url.get_secret_value())
                try:
                    db.permission_gate()
                    current=db.read_one('''SELECT v.id,v.source_hash,v.valid_until>now() AS fresh
                        FROM app.runtime_state t JOIN app.reference_versions v
                        ON v.id=t.active_reference_version_id WHERE t.singleton''')
                    if current and current['source_hash']==snapshot.source_hash and current['fresh']:
                        ref=current['id']
                    else:
                        with db.transaction() as conn:
                            ref=import_reference(conn,snapshot,settings.google_spreadsheet_id,ttl_hours=settings.reference_ttl_hours)
                    report.update(applied=True,reference_version_id=str(ref))
                finally:db.close()
        report['spreadsheet_url']='https://docs.google.com/spreadsheets/d/'+settings.google_spreadsheet_id
        if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2));return 0
    except Exception as error:
        # Do not echo provider responses/credential-bearing exception text.
        print(json.dumps({'status':'failed','error_type':type(error).__name__,
                         'message':str(error) if isinstance(error,ValueError) else 'Preparation failed; prior DB reference remains valid'}))
        return 1


if __name__=='__main__':raise SystemExit(main())

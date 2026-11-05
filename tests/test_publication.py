from copy import deepcopy
from datetime import date, datetime, timezone
from urllib.parse import unquote
from unittest.mock import MagicMock, patch
from uuid import UUID

import httpx
import pytest
import requests

from app.publication import HEADERS, PublicationConflict, PublicationError, SheetsPublisher


@pytest.fixture
def acceptance():
    return {'id': UUID('10000000-0000-0000-0000-000000000001'),
            'submission_id': UUID('20000000-0000-0000-0000-000000000001'),
            'reference_version_id': UUID('30000000-0000-0000-0000-000000000001'),
            'vendor_code': 'V-ACME', 'invoice_number': 'INV-1001',
            'invoice_date': date(2026,11,2), 'po_code': 'PO-FULL', 'currency':'INR',
            'amount_minor':1000000, 'method':'automatic',
            'accepted_at':datetime(2026,11,2,10,15,tzinfo=timezone.utc), 'sheet_row':2}


class FakeSheet:
    def __init__(self):
        self.headers=list(HEADERS); self.rows={}; self.row_count=1000; self.columns=11
        self.calls=[]; self.fail_write_after_commit_once=False; self.fail_confirmation=False
        self.http_error=None; self.missing_table=False
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,deepcopy(kwargs)))
        assert kwargs['timeout']==20 and kwargs['max_allowed_time']==20
        if self.http_error:
            return httpx.Response(self.http_error,text='private upstream key diagnostics')
        if method=='GET' and '/values/' not in url:
            sheet={'properties':{'title':'AcceptedInvoices','sheetId':12,
                   'gridProperties':{'rowCount':self.row_count,'columnCount':self.columns}}}
            return httpx.Response(200,json={'sheets':[] if self.missing_table else [sheet]})
        if method=='POST':
            assert url.endswith(':batchUpdate')
            dimension=kwargs['json']['requests'][0]['appendDimension']
            assert dimension['sheetId']==12 and dimension['dimension']=='ROWS'
            assert dimension['length']>0
            self.row_count+=dimension['length']
            return httpx.Response(200,json={})
        target=unquote(url.split('/values/')[1])
        if method=='GET' and target=="'AcceptedInvoices'!A1:K1":
            return httpx.Response(200,json={'range':target,'values':[self.headers]})
        row=int(target.split('!A')[1].split(':')[0]); assert row<=self.row_count
        if method=='PUT':
            assert kwargs['params']['valueInputOption']=='RAW'
            assert kwargs['json']['range']==target
            self.rows[row]=kwargs['json']['values'][0].copy()
            if self.fail_confirmation: self.rows[row][7]='999.99'
            if self.fail_write_after_commit_once:
                self.fail_write_after_commit_once=False
                raise requests.ReadTimeout('private ambiguous request details')
            return httpx.Response(200,json={'updatedRange':target})
        assert method=='GET'
        return httpx.Response(200,json={'range':target,'values':[self.rows[row]] if row in self.rows else []})
    @property
    def writes(self): return [call for call in self.calls if call[0]=='PUT']


@pytest.fixture
def publisher():
    sheet=FakeSheet(); session=MagicMock(); session.request.side_effect=sheet.request
    context=MagicMock(); context.__enter__.return_value=session
    with patch('google.oauth2.service_account.Credentials.from_service_account_file'), \
            patch('google.auth.transport.requests.AuthorizedSession',return_value=context):
        yield SheetsPublisher('demo_spreadsheet_id','/private/not-real.json'),sheet


def test_writes_exact_fixed_row_as_raw_strings_and_confirms(publisher,acceptance):
    client,sheet=publisher
    assert client.publish(acceptance)=="'AcceptedInvoices'!A2:K2"
    assert len(sheet.writes)==1
    row=sheet.rows[2]
    assert len(row)==11 and row[0]==str(acceptance['id'])
    assert row[4]=='2026-11-02' and row[7]=='10000.00' and row[9]=='2026-11-02T10:15:00+00:00'
    assert all(isinstance(value,str) for value in row)
    assert sheet.calls[-1][0]=='GET'
    assert not any(':append' in call[1] for call in sheet.calls)


def test_replay_does_not_append_or_rewrite(publisher,acceptance):
    client,sheet=publisher
    assert client.publish(acceptance)==client.publish(acceptance)
    assert len(sheet.writes)==1 and len(sheet.rows)==1


def test_timeout_after_commit_replays_same_reserved_row_after_restart(publisher,acceptance):
    client,sheet=publisher; sheet.fail_write_after_commit_once=True
    with pytest.raises(PublicationError,match='SPREADSHEET_PUBLICATION_UNAVAILABLE'):
        client.publish(acceptance)
    assert sheet.rows[2][0]==str(acceptance['id'])
    restarted=SheetsPublisher('demo_spreadsheet_id','/private/not-real.json')
    assert restarted.publish(acceptance)=="'AcceptedInvoices'!A2:K2"
    assert len(sheet.writes)==1 and len(sheet.rows)==1


@pytest.mark.parametrize('existing', [['another-acceptance-id','unrelated data'],['','manual accounting data']])
def test_occupied_row_is_never_overwritten(publisher,acceptance,existing):
    client,sheet=publisher; sheet.rows[2]=existing.copy()
    with pytest.raises(PublicationConflict,match='SPREADSHEET_ROW_OCCUPIED'): client.publish(acceptance)
    assert sheet.rows[2]==existing and not sheet.writes


def test_same_acceptance_mirror_drift_repaired_from_ledger(publisher,acceptance):
    client,sheet=publisher; sheet.rows[2]=[str(acceptance['id']),'unfinished publication']
    client.publish(acceptance)
    assert sheet.rows[2][1]==str(acceptance['submission_id']) and sheet.rows[2][7]=='10000.00'


def test_header_mismatch_blocks_growth_and_writes(publisher,acceptance):
    client,sheet=publisher; sheet.headers[0]='invoice_id'; acceptance['sheet_row']=2000
    with pytest.raises(PublicationConflict,match='SPREADSHEET_HEADERS_MISMATCH'): client.publish(acceptance)
    assert not sheet.writes and not any(call[0]=='POST' for call in sheet.calls)


@pytest.mark.parametrize('change',['missing','columns'])
def test_invalid_table_is_conflict(publisher,acceptance,change):
    client,sheet=publisher
    if change=='missing': sheet.missing_table=True
    else: sheet.columns=10
    with pytest.raises(PublicationConflict,match='SPREADSHEET_TABLE_INVALID'): client.publish(acceptance)
    assert not sheet.writes


def test_capacity_growth_never_replaces_or_deletes_other_rows(publisher,acceptance):
    client,sheet=publisher; sheet.rows[500]=['another-row-preserved']; acceptance['sheet_row']=2001
    client.publish(acceptance)
    assert sheet.row_count==2001 and sheet.rows[500]==['another-row-preserved']
    grows=[call for call in sheet.calls if call[0]=='POST']; assert len(grows)==1
    assert grows[0][2]['json']=={'requests':[{'appendDimension':{'sheetId':12,'dimension':'ROWS','length':1001}}]}
    client.publish(acceptance)
    assert len([call for call in sheet.calls if call[0]=='POST'])==1


def test_failed_readback_does_not_report_success(publisher,acceptance):
    client,sheet=publisher; sheet.fail_confirmation=True
    with pytest.raises(PublicationConflict,match='SPREADSHEET_WRITE_NOT_CONFIRMED'): client.publish(acceptance)


def test_formula_invoice_number_stays_literal(publisher,acceptance):
    client,sheet=publisher; acceptance['invoice_number']='=IMPORTXML("https://example.test","//text()")'
    client.publish(acceptance)
    assert sheet.rows[2][3]==acceptance['invoice_number']
    assert sheet.writes[0][2]['params']=={'valueInputOption':'RAW'}


@pytest.mark.parametrize('amount,expected',[(1,'0.01'),(1000050,'10000.50'),
    (9223372036854775807,'92233720368547758.07')])
def test_money_keeps_exact_minor_units(publisher,acceptance,amount,expected):
    client,sheet=publisher; acceptance['amount_minor']=amount; client.publish(acceptance)
    assert sheet.rows[2][7]==expected


def test_readback_normalizes_existing_numeric_money(publisher,acceptance):
    client,sheet=publisher; client.publish(acceptance); sheet.rows[2][7]=10000; client.publish(acceptance)
    assert len(sheet.writes)==1


@pytest.mark.parametrize('field,value',[('sheet_row',1),('sheet_row',10001),('sheet_row',True),
    ('sheet_row','2'),('amount_minor',0),('amount_minor',True),('amount_minor',10000.1),
    ('currency','EUR'),('method','override'),('id','invalid'),('invoice_number','')])
def test_invalid_ledger_payload_rejected_before_network(publisher,acceptance,field,value):
    client,sheet=publisher; acceptance[field]=value
    with pytest.raises(PublicationError,match='PUBLICATION_RECORD_INVALID'): client.publish(acceptance)
    assert not sheet.calls


@pytest.mark.parametrize('status',[403,404,429,500])
def test_provider_errors_are_sanitized(publisher,acceptance,status):
    client,sheet=publisher; sheet.http_error=status
    with pytest.raises(PublicationError) as error: client.publish(acceptance)
    assert 'private' not in str(error.value) and str(acceptance['id']) not in str(error.value)
    assert not sheet.writes


def test_credential_failure_sanitized(acceptance):
    with patch('google.oauth2.service_account.Credentials.from_service_account_file',
               side_effect=ValueError('private key material')):
        with pytest.raises(PublicationError,match='SPREADSHEET_PUBLICATION_UNAVAILABLE'):
            SheetsPublisher('demo_spreadsheet_id','/private/not-real.json').publish(acceptance)

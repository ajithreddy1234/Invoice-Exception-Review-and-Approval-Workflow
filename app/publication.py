"""Idempotent publication to a reserved report row, never a blind append.

The DB outbox permanently reserves ``sheet_row`` for each immutable acceptance.
Do not sort/insert/delete report rows manually. Google Sheets has no compare-and-
set row update; protect this output tab from concurrent human edits. PostgreSQL
remains the authoritative ledger regardless of report edits or provider failure.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re
from urllib.parse import quote
from uuid import UUID

HEADERS = ('acceptance_id', 'submission_id', 'vendor_code', 'invoice_number', 'invoice_date',
           'po_code', 'currency', 'accepted_amount', 'method', 'accepted_at', 'reference_version_id')
MAX_SHEET_ROW = 10000


class PublicationError(RuntimeError):
    """A sanitized transient/configuration publication failure."""


class PublicationConflict(PublicationError):
    """Unsafe table structure, occupied reservation, or failed verification."""


def _record(acceptance: dict) -> tuple[int, list[str]]:
    try:
        row = acceptance['sheet_row']
        if isinstance(row, bool) or not isinstance(row, int) or not 2 <= row <= MAX_SHEET_ROW:
            raise ValueError
        amount = acceptance['amount_minor']
        if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= 9223372036854775807:
            raise ValueError
        money = f'{amount // 100}.{amount % 100:02d}'
        values = [str(UUID(str(acceptance['id']))), str(UUID(str(acceptance['submission_id']))),
                  acceptance['vendor_code'], acceptance['invoice_number'], acceptance['invoice_date'],
                  acceptance['po_code'], acceptance['currency'], money, acceptance['method'],
                  acceptance['accepted_at'], str(UUID(str(acceptance['reference_version_id'])))]
        values = [value.isoformat() if isinstance(value, (datetime, date)) else value for value in values]
        if any(not isinstance(value, str) or not value or len(value) > 2000 for value in values):
            raise ValueError
        if values[6] not in ('INR', 'USD') or values[8] not in ('automatic', 'admin'):
            raise ValueError
        return row, values
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PublicationError('PUBLICATION_RECORD_INVALID') from None


def _normalized(values: list) -> list[str] | None:
    """Normalize provider cells without losing monetary precision."""
    if len(values) != len(HEADERS):
        return None
    result = []
    for index, value in enumerate(values):
        if index == 7:
            try:
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    return None
                if isinstance(value, (int, float)) and abs(value) >= 2 ** 53:
                    return None
                raw = str(value)
                if len(raw) > 30 or not re.fullmatch(r'\d+(?:\.\d+)?', raw):
                    return None
                with localcontext() as context:
                    context.prec = 80
                    amount = Decimal(raw)
                    if amount * 100 != (amount * 100).to_integral_value():
                        return None
                    result.append(format(amount, '.2f'))
            except (ValueError, InvalidOperation):
                return None
        else:
            if not isinstance(value, str):
                return None
            result.append(value)
    return result


class SheetsPublisher:
    def __init__(self, spreadsheet_id: str, credentials_file: str, timeout: float = 20):
        if not isinstance(spreadsheet_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', spreadsheet_id):
            raise PublicationError('PUBLICATION_CONFIGURATION_INVALID')
        if not 0 < timeout <= 60:
            raise PublicationError('PUBLICATION_CONFIGURATION_INVALID')
        self.spreadsheet_id = spreadsheet_id
        self.credentials_file = credentials_file
        self.timeout = timeout
        self._base = 'https://sheets.googleapis.com/v4/spreadsheets/' + quote(spreadsheet_id, safe='')

    def _request(self, session, method, path, **kwargs):
        response = session.request(method, self._base + path, timeout=self.timeout,
                                   max_allowed_time=self.timeout, **kwargs)
        if response.status_code != 200:
            raise PublicationError('SPREADSHEET_PUBLICATION_UNAVAILABLE')
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise PublicationError('SPREADSHEET_RESPONSE_INVALID') from None
        if not isinstance(payload, dict):
            raise PublicationError('SPREADSHEET_RESPONSE_INVALID')
        return payload

    def _read(self, session, cell_range):
        payload = self._request(session, 'GET', '/values/' + quote(cell_range, safe=''),
                                params={'valueRenderOption': 'UNFORMATTED_VALUE',
                                        'dateTimeRenderOption': 'FORMATTED_STRING'})
        values = payload.get('values', [])
        if (not isinstance(values, list) or len(values) > 1 or
                (values and not isinstance(values[0], list))):
            raise PublicationConflict('SPREADSHEET_ROW_INVALID')
        return values[0] if values else []

    def _table(self, session):
        metadata = self._request(session, 'GET', '', params={
            'fields': 'sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))'})
        try:
            sheets = metadata['sheets']
            if not isinstance(sheets, list):
                raise ValueError
            matching = [sheet['properties'] for sheet in sheets if sheet['properties']['title'] == 'AcceptedInvoices']
            if len(matching) != 1:
                raise ValueError
            properties = matching[0]
            sheet_id = properties['sheetId']
            rows = properties['gridProperties']['rowCount']
            columns = properties['gridProperties']['columnCount']
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (sheet_id, rows, columns)):
                raise ValueError
            if sheet_id < 0 or rows < 1 or columns < len(HEADERS):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise PublicationConflict('SPREADSHEET_TABLE_INVALID') from None
        return sheet_id, rows

    def _grow(self, session, sheet_id, rows, target_row):
        if rows < target_row:
            # Append dimensions only: setting rowCount from a stale metadata read
            # could shrink another worker's growth and erase data farther down.
            self._request(session, 'POST', ':batchUpdate', json={'requests': [{
                'appendDimension': {'sheetId': sheet_id, 'dimension': 'ROWS', 'length': target_row - rows}}]})

    def publish(self, acceptance: dict) -> str:
        row, expected = _record(acceptance)
        cell_range = f"'AcceptedInvoices'!A{row}:K{row}"
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials
        try:
            credentials = Credentials.from_service_account_file(
                self.credentials_file, scopes=['https://www.googleapis.com/auth/spreadsheets'])
            with AuthorizedSession(credentials, refresh_timeout=self.timeout) as session:
                sheet_id, rows = self._table(session)
                if tuple(self._read(session, "'AcceptedInvoices'!A1:K1")) != HEADERS:
                    raise PublicationConflict('SPREADSHEET_HEADERS_MISMATCH')
                self._grow(session, sheet_id, rows, row)
                existing = self._read(session, cell_range)
                if _normalized(existing) == expected:
                    return cell_range
                if existing and any(value not in ('', None) for value in existing):
                    if not existing or existing[0] != expected[0]:
                        raise PublicationConflict('SPREADSHEET_ROW_OCCUPIED')
                self._request(session, 'PUT', '/values/' + quote(cell_range, safe=''),
                              params={'valueInputOption': 'RAW'},
                              json={'range': cell_range, 'majorDimension': 'ROWS', 'values': [expected]})
                if _normalized(self._read(session, cell_range)) != expected:
                    raise PublicationConflict('SPREADSHEET_WRITE_NOT_CONFIRMED')
                return cell_range
        except PublicationError:
            raise
        except Exception:
            # A timeout after a PUT can mean the write succeeded. Do not mark the
            # outbox complete; replay will inspect this exact reserved row.
            raise PublicationError('SPREADSHEET_PUBLICATION_UNAVAILABLE') from None

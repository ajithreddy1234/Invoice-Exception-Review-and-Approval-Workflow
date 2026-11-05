"""Operator checks: never print connection strings, credentials or invoice text."""
import argparse
import json
from pathlib import Path
import sys

from .config import get_settings
from .db import Database
from .procurement import SheetsGateway, parse_reference, import_reference


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['doctor', 'import-sheet', 'probe-gemini'])
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--file', type=Path)
    args = parser.parse_args()
    s = get_settings()
    result = {'configured': s.configured()}
    failed = False
    if args.command in ('doctor', 'import-sheet'):
        if args.live or args.command == 'import-sheet':
            db = Database(s.database_url.get_secret_value())
            try:
                result['database'] = db.permission_gate()
            except Exception:
                result['database'] = 'failed: check connection, schema and restricted grants'
                failed = True
            try:
                gateway = SheetsGateway(s.google_spreadsheet_id, s.google_application_credentials)
                snapshot = parse_reference(gateway.read_reference())
                result['sheet'] = {'valid': True, 'po_count': len(snapshot.pos), 'source_hash': snapshot.source_hash}
                if args.command == 'import-sheet' and not failed:
                    with db.transaction() as conn:
                        version_id = import_reference(conn, snapshot, s.google_spreadsheet_id,
                                                      ttl_hours=s.reference_ttl_hours)
                    result['active_reference_version_id'] = version_id
            except Exception:
                result['sheet'] = 'failed: check sharing, tab names and input data; prior reference preserved'
                failed = True
        else:
            failed = not all(result['configured'].values())
    else:
        if not args.file:
            parser.error('probe-gemini requires --file <synthetic invoice PDF>')
        try:
            from .extraction import GeminiExtractor, read_document, validate_evidence
            data = args.file.read_bytes()
            mime = 'application/pdf' if data.startswith(b'%PDF-') else 'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg'
            text = read_document(data, mime)
            candidate = GeminiExtractor(s.gemini_api_key.get_secret_value(), s.gemini_model).extract(text)
            issues = validate_evidence(candidate, text)
            result['fresh_live_extraction'] = True
            result['evidence_issues'] = [{'field': i.field, 'code': i.code} for i in issues]
            result['approval_performed'] = False
            failed = bool(issues)
        except Exception:
            result['fresh_live_extraction'] = 'failed: check key, free-tier model, quota and input'
            failed = True
    print(json.dumps(result, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())


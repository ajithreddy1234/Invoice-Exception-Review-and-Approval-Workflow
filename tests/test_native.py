"""Real Postgres integration. Only the isolated native runner supplies this URL."""
import csv
from dataclasses import replace
from pathlib import Path
import os

import psycopg
import pytest

from app.db import Database
from app.procurement import import_reference, parse_reference

URL = os.getenv('INVOICE_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='Run scripts/native-api.mjs for isolated native Postgres')
ROOT = Path(__file__).resolve().parents[2]
ACTOR = '11111111-1111-4111-8111-111111111111'


def sample():
    return parse_reference({p.stem: list(csv.reader(p.open()))
                            for p in (Path(__file__).resolve().parent / 'reference_data').glob('*.csv')})


def test_real_connection_rejects_forgery():
    db = Database(URL)
    assert db.permission_gate() == {'restricted_role': 'service_role', 'forged_status_update': 'denied'}


def test_real_import_and_exact_tax_conversion():
    db = Database(URL)
    snapshot = sample()
    with db.transaction() as conn:
        version = import_reference(conn, snapshot, 'native-test-sheet', ACTOR)
    with db.transaction() as conn:
        row = conn.execute('SELECT active_reference_version_id AS id FROM app.runtime_state').fetchone()
        assert str(row['id']) == version
        line = conn.execute("SELECT tax_rate_bps,unit_net_minor FROM app.reference_lines WHERE reference_version_id=%s AND po_code='PO-TAX'", (version,)).fetchone()
        assert line == {'tax_rate_bps': 1800, 'unit_net_minor': 100000}
        assert conn.execute('SELECT count(*) AS n FROM app.acceptances').fetchone()['n'] == 0


def test_invalid_activation_rolls_back_all_staging_and_pointer():
    db = Database(URL)
    with db.transaction() as conn:
        before = conn.execute('SELECT active_reference_version_id AS id FROM app.runtime_state').fetchone()['id']
        count = conn.execute('SELECT count(*) AS n FROM app.reference_versions').fetchone()['n']
    original = sample()
    # Bypass parser deliberately to prove the SQL activation gate also rejects it.
    broken = replace(original, pos=tuple(replace(p, authorized_gross_minor=1) if p.po_code == 'PO-FULL' else p for p in original.pos))
    with pytest.raises(psycopg.Error, match='REFERENCE_LINE_TOTAL_MISMATCH'):
        with db.transaction() as conn:
            import_reference(conn, broken, 'native-invalid-sheet', ACTOR)
    with db.transaction() as conn:
        assert conn.execute('SELECT active_reference_version_id AS id FROM app.runtime_state').fetchone()['id'] == before
        assert conn.execute('SELECT count(*) AS n FROM app.reference_versions').fetchone()['n'] == count


def test_refresh_keeps_stable_po_identity_and_immutable_history():
    db = Database(URL)
    with db.transaction() as conn:
        old = conn.execute('SELECT active_reference_version_id AS id FROM app.runtime_state').fetchone()['id']
        created = conn.execute("SELECT created_at FROM app.po_accounts WHERE po_code='PO-FULL'").fetchone()['created_at']
        new = import_reference(conn, sample(), 'native-test-sheet', ACTOR)
    assert str(old) != new
    with db.transaction() as conn:
        assert conn.execute("SELECT created_at FROM app.po_accounts WHERE po_code='PO-FULL'").fetchone()['created_at'] == created
        assert conn.execute('SELECT status FROM app.reference_versions WHERE id=%s', (old,)).fetchone()['status'] == 'valid'
        with pytest.raises(psycopg.Error, match='REFERENCE_SNAPSHOT_IS_FROZEN'):
            with conn.transaction():
                conn.execute('DELETE FROM app.reference_lines WHERE reference_version_id=%s', (old,))


def test_unprivileged_actor_cannot_activate():
    db = Database(URL)
    with pytest.raises(psycopg.Error, match='ADMIN_REQUIRED'):
        with db.transaction() as conn:
            import_reference(conn, sample(), 'native-test-sheet', '22222222-2222-4222-8222-222222222222')


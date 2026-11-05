import importlib.util
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

spec = importlib.util.spec_from_file_location('set_database_connection', Path(__file__).resolve().parents[1] / 'scripts/set_database_connection.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TEMPLATE = 'postgresql://postgres.demo:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres'


@pytest.mark.parametrize('password', ['dummy', 'dummy@x', 'dummy@x#?/:%+ y', 'dummy%40x', 'dummy"\'x'])
def test_database_password_is_encoded_once_without_changing_it(password):
    parsed = conninfo_to_dict(module.connection_uri(TEMPLATE, password))
    assert parsed['password'] == password
    assert parsed['host'] == 'aws-0-ap-south-1.pooler.supabase.com'
    assert parsed['sslmode'] == 'require'


@pytest.mark.parametrize('template', ['not-a-uri', TEMPLATE.replace(':6543', ':5432'), TEMPLATE.replace('.pooler.supabase.com', '.example.com'), TEMPLATE + '#bad'])
def test_invalid_template_is_rejected(template):
    with pytest.raises(ValueError):
        module.connection_uri(template, 'dummy')


def test_pool_diagnostics_cannot_print_a_credential_bearing_driver_error(caplog):
    import logging
    import app.db
    secret='postgresql://demo:never-log-this-password@db.example/test'
    with caplog.at_level(logging.WARNING,logger='psycopg.pool'):
        try:raise ValueError(secret)
        except ValueError:
            logging.getLogger('psycopg.pool').warning('error connecting: %s',secret,exc_info=True)
    assert 'never-log-this-password' not in caplog.text
    assert 'Database pool event; connection details omitted' in caplog.text
    assert all(not r.args and not r.exc_info and not r.exc_text for r in caplog.records)

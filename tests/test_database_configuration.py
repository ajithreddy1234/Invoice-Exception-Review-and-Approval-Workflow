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

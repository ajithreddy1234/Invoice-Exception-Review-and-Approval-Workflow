"""HTTP boundary tests with no external resources or credential files."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.auth import COOKIE, Actor, SupabaseAuth, current_actor, require_admin
from app.config import Settings
from app.db import DatabaseUnavailable
from app.main import create_app

USER = UUID('aaaaaaaa-0000-0000-0000-000000000001')
ADMIN = UUID('aaaaaaaa-0000-0000-0000-000000000002')
ORIGIN = 'http://127.0.0.1:8000'


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
    def fetchone(self):
        return self.row
    def fetchall(self):
        return self.rows


class FakeDatabase:
    def __init__(self):
        self.profiles = {
            USER: {'user_id': USER, 'display_name': 'Recruiter User', 'role': 'user', 'enabled': True},
            ADMIN: {'user_id': ADMIN, 'display_name': 'Recruiter Admin', 'role': 'admin', 'enabled': True},
        }
        self.executed = []
        self.reference = {'id': uuid4(), 'status': 'valid', 'source_spreadsheet_id': 'demo_spreadsheet_id',
                          'source_hash': 'a' * 64, 'imported_at': datetime.now(timezone.utc),
                          'valid_until': datetime.now(timezone.utc) + timedelta(days=1), 'fresh': True}
        self.gate_error = None
    @contextmanager
    def transaction(self):
        yield self
    def read_one(self, sql, params=None):
        return self.execute(sql, params).fetchone()
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if 'FROM app.profiles' in sql:
            return FakeCursor(self.profiles.get(params[0]))
        if 'FROM app.runtime_state' in sql:
            return FakeCursor(self.reference)
        if 'FROM app.submissions' in sql:
            return FakeCursor(rows=[])
        raise AssertionError('Unexpected database query in HTTP boundary test')
    def permission_gate(self):
        if self.gate_error:
            raise self.gate_error
        return {'restricted_role': 'service_role', 'forged_status_update': 'denied'}


class FakeAuth:
    def __init__(self):
        self.checked_tokens = []
        self.login_inputs = []
        self.logout_tokens = []
        self.login_error = None
        self.logout_error = None
        self.result_token = 'verified-user-token'
    def login(self, email, password):
        self.login_inputs.append((email, password))
        if self.login_error:
            raise self.login_error
        # Intentional misleading role in provider metadata: app must use DB role.
        return {'access_token': self.result_token, 'expires_in': 7200,
                'user': {'id': str(USER), 'user_metadata': {'role': 'admin'}},
                'refresh_token': 'never-return-this-refresh-token'}
    def user_id(self, token):
        self.checked_tokens.append(token)
        if token == 'verified-user-token':
            return USER
        if token == 'verified-admin-token':
            return ADMIN
        raise HTTPException(401, 'SESSION_EXPIRED')
    def logout(self, token):
        self.logout_tokens.append(token)
        if self.logout_error:
            raise self.logout_error


def settings(**overrides):
    values = dict(app_origin=ORIGIN, cookie_secure=False, auto_import_on_startup=False,
                  database_url='', supabase_url='', supabase_publishable_key='',
                  google_application_credentials='', google_spreadsheet_id='',
                  gemini_api_key='', gemini_model='')
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def boundary():
    db, auth, sheets = FakeDatabase(), FakeAuth(), MagicMock()
    config = settings(database_url='postgresql://not-real/', supabase_url='https://not-real.supabase.co',
                      supabase_publishable_key='public-test-key', google_application_credentials='/not-real/key.json',
                      google_spreadsheet_id='demo_spreadsheet_id')
    app = create_app(config, db=db, auth=auth, sheets=sheets)
    with TestClient(app) as client:
        wait_for_startup(app)
        yield app, client, db, auth, sheets


@pytest.mark.parametrize('path', ['/api/auth/login', '/api/auth/logout', '/api/admin/procurement/sync'])
@pytest.mark.parametrize('origin', [None, 'https://evil.example', 'null', ORIGIN + '.evil.example'])
def test_all_state_changes_require_exact_origin(boundary, path, origin):
    app, client, db, auth, sheets = boundary
    headers = {} if origin is None else {'Origin': origin}
    response = client.post(path, headers=headers, json={'email': 'demo@example.test', 'password': 'password'})
    assert response.status_code == 403
    assert response.json() == {'detail': 'ORIGIN_REJECTED'}
    assert not auth.login_inputs
    sheets.read_reference.assert_not_called()


@pytest.mark.parametrize('path', ['/api/me', '/api/submissions', '/api/procurement/status', '/api/admin/health'])
def test_no_cookie_is_unauthenticated(boundary, path):
    _, client, _, auth, _ = boundary
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()['detail'] == 'LOGIN_REQUIRED'
    assert not auth.checked_tokens


def test_verified_token_maps_database_profile_role(boundary):
    _, client, db, auth, _ = boundary
    response = client.post('/api/auth/login', headers={'Origin': ORIGIN},
                           json={'email': 'demo@example.test', 'password': 'private-password', 'role': 'admin'})
    assert response.status_code == 200
    assert response.json()['role'] == 'user'
    assert response.json()['id'] == str(USER)
    assert response.json()['expires_in'] == 3600
    assert auth.checked_tokens == []  # Password grant already verified by Auth.
    assert client.cookies.get(COOKIE) == 'verified-user-token'
    assert 'private-password' not in response.text
    assert 'access_token' not in response.text
    assert 'refresh' not in response.text
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=3600' in cookie
    assert client.get('/api/me').json()['role'] == 'user'
    assert auth.checked_tokens == ['verified-user-token']


@pytest.mark.parametrize('profile', ['disabled', 'missing'])
def test_disabled_or_missing_profile_rejects_verified_auth(boundary, profile):
    _, client, db, auth, _ = boundary
    if profile == 'disabled':
        db.profiles[USER]['enabled'] = False
    else:
        db.profiles.pop(USER)
    client.cookies.set(COOKIE, 'verified-user-token')
    assert client.get('/api/me').status_code == 403
    response = client.post('/api/auth/login', headers={'Origin': ORIGIN},
                           json={'email': 'demo@example.test', 'password': 'private-password'})
    assert response.status_code == 403
    assert 'set-cookie' not in response.headers


def test_invalid_token_does_not_use_client_identity(boundary):
    _, client, db, auth, _ = boundary
    client.cookies.set(COOKIE, 'forged-token')
    response = client.get('/api/me', headers={'X-User-Id': str(ADMIN), 'X-Role': 'admin'})
    assert response.status_code == 401
    assert not db.executed


@pytest.mark.parametrize('path,method', [('/api/admin/health','get'),('/api/admin/procurement/sync','post')])
def test_normal_user_forbidden_admin_actions(boundary, path, method):
    _, client, _, _, sheets = boundary
    client.cookies.set(COOKIE, 'verified-user-token')
    response = getattr(client, method)(path, headers={'Origin': ORIGIN})
    assert response.status_code == 403
    assert response.json()['detail'] == 'ADMIN_REQUIRED'
    sheets.read_reference.assert_not_called()


def test_admin_sync_uses_verified_profile_actor(boundary):
    app, client, db, auth, sheets = boundary
    client.cookies.set(COOKIE, 'verified-admin-token')
    expected = {'reference_version_id': str(uuid4()), 'source_hash': 'a'*64, 'status': 'active'}
    with patch('app.main.sync_reference', return_value=expected) as sync:
        response = client.post('/api/admin/procurement/sync', headers={'Origin': ORIGIN},
                               json={'actor_id': str(USER)})
    assert response.status_code == 200
    assert response.json() == expected
    sync.assert_called_once_with(app, ADMIN)


def test_dependency_override_supports_isolated_route_check(boundary):
    app, client, _, auth, _ = boundary
    app.dependency_overrides[current_actor] = lambda: Actor(ADMIN, 'Injected admin', 'admin')
    response = client.get('/api/me')
    assert response.status_code == 200
    assert response.json()['role'] == 'admin'
    assert auth.checked_tokens == []
    app.dependency_overrides.clear()


@pytest.mark.parametrize('body', [
    {'email':'x','password':'do-not-echo-this-secret'},
    {'email':['do-not-echo-this-secret'],'password':'do-not-echo-this-secret'},
    {'email':'demo@example.test','password':{'secret':'do-not-echo-this-secret'}},
    {'email':'demo@example.test','password':'do-not-echo-this-secret'*100},
])
def test_validation_never_echoes_credentials(boundary, body):
    _, client, _, auth, _ = boundary
    response = client.post('/api/auth/login', headers={'Origin':ORIGIN}, json=body)
    assert response.status_code == 422
    assert 'do-not-echo-this-secret' not in response.text
    assert not auth.login_inputs
    assert all('input' not in error and 'ctx' not in error for error in response.json()['detail'])


def test_logout_clears_cookie_even_when_remote_logout_unavailable(boundary):
    _, client, _, auth, _ = boundary
    client.cookies.set(COOKIE, 'verified-user-token')
    auth.logout_error = HTTPException(503, 'AUTH_UNAVAILABLE')
    response = client.post('/api/auth/logout', headers={'Origin':ORIGIN})
    assert response.status_code == 200
    assert response.json() == {'signed_out':True, 'remote_session_revoked':False}
    assert auth.logout_tokens == ['verified-user-token']
    cookie = response.headers['set-cookie'].lower()
    assert 'max-age=0' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie


def test_secure_deployment_cookie_flag():
    db, auth = FakeDatabase(), FakeAuth()
    config = Settings(_env_file=None, app_origin='https://demo.example', cookie_secure=True,
                      auto_import_on_startup=False)
    with TestClient(create_app(config, db=db, auth=auth, sheets=MagicMock())) as client:
        response = client.post('/api/auth/login', headers={'Origin':'https://demo.example'},
                               json={'email':'demo@example.test','password':'private-password'})
        assert 'secure' in response.headers['set-cookie'].lower()
        logout = client.post('/api/auth/logout', headers={'Origin':'https://demo.example'})
        assert 'secure' in logout.headers['set-cookie'].lower()


def test_missing_configuration_is_live_but_not_ready():
    with TestClient(create_app(settings(), db=FakeDatabase(), auth=FakeAuth(), sheets=MagicMock())) as client:
        assert client.get('/health/live').status_code == 200
        response = client.get('/health/ready')
        assert response.status_code == 503
        assert response.json()['status'] == 'setup_required'
        assert not any(response.json()['configured'].values())


def test_ready_requires_fresh_reference_and_gate(boundary):
    _, client, db, _, _ = boundary
    response = client.get('/health/ready')
    assert response.status_code == 200
    assert response.json()['invoice_pipeline_complete'] is False
    db.reference['fresh'] = False
    assert client.get('/health/ready').status_code == 503
    db.gate_error = DatabaseUnavailable('credential-bearing-private-url')
    response = client.get('/health/ready')
    assert response.status_code == 503
    assert 'private' not in response.text


def test_submissions_query_scopes_to_authenticated_actor(boundary):
    _, client, db, _, _ = boundary
    client.cookies.set(COOKIE, 'verified-user-token')
    assert client.get('/api/submissions?uploaded_by=' + str(ADMIN)).status_code == 200
    sql, params = db.executed[-1]
    assert 's.uploaded_by=%s' in sql
    assert params == ('user', USER)


def test_all_successful_reads_have_security_headers(boundary):
    _, client, _, _, _ = boundary
    response = client.get('/health/live')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']


@pytest.mark.parametrize('upstream,status,detail', [(400,401,'INVALID_CREDENTIALS'),
    (401,401,'INVALID_CREDENTIALS'), (429,429,'LOGIN_RATE_LIMITED'), (503,503,'AUTH_UNAVAILABLE')])
def test_auth_provider_errors_are_sanitized(upstream, status, detail):
    provider = SupabaseAuth('https://not-real.supabase.co', 'test-key')
    provider._call = MagicMock(return_value=MagicMock(status_code=upstream, text='private-upstream-diagnostic'))
    with pytest.raises(HTTPException) as error:
        provider.login('demo@example.test', 'private-password')
    assert error.value.status_code == status
    assert error.value.detail == detail


@pytest.mark.parametrize('upstream', [401,403])
def test_expired_auth_tokens_do_not_reach_profile_lookup(upstream):
    provider = SupabaseAuth('https://not-real.supabase.co', 'test-key')
    provider._call = MagicMock(return_value=MagicMock(status_code=upstream))
    with pytest.raises(HTTPException) as error:
        provider.user_id('expired-token')
    assert error.value.status_code == 401
    assert error.value.detail == 'SESSION_EXPIRED'


@pytest.mark.parametrize('payload', [{}, {'id':'not-a-uuid'}, {'id':None}, []])
def test_auth_user_response_requires_verified_uuid(payload):
    provider = SupabaseAuth('https://not-real.supabase.co', 'test-key')
    provider._call = MagicMock(return_value=MagicMock(status_code=200, json=lambda:payload))
    with pytest.raises(HTTPException) as error:
        provider.user_id('token')
    assert error.value.status_code == 503
    assert error.value.detail == 'AUTH_RESPONSE_INVALID'


@pytest.mark.parametrize('payload', [
    [], None, {}, {'user': []},
    {'user': {'id': str(USER)}, 'access_token': '', 'expires_in': 3600},
    {'user': {'id': str(USER)}, 'access_token': 123, 'expires_in': 3600},
    {'user': {'id': 'invalid-uuid'}, 'access_token': 'private-upstream-token', 'expires_in': 3600},
    {'user': {'id': str(USER)}, 'access_token': 'private-upstream-token', 'expires_in': 'garbage'},
    {'user': {'id': str(USER)}, 'access_token': 'private-upstream-token', 'expires_in': True},
    {'user': {'id': str(USER)}, 'access_token': 'private-upstream-token', 'expires_in': 0},
    {'user': {'id': str(USER)}, 'access_token': 'private-upstream-token', 'expires_in': -1},
    {'user': {'id': str(USER)}, 'access_token': 'private-upstream-token', 'expires_in': 1.5},
])
def test_malformed_login_provider_response_fails_safely(boundary, payload):
    app, client, _, _, _ = boundary
    provider = SupabaseAuth('https://not-real.supabase.co', 'test-key')
    provider._call = MagicMock(return_value=MagicMock(status_code=200, json=lambda: payload))
    app.state.auth = provider
    response = client.post('/api/auth/login', headers={'Origin': ORIGIN},
                           json={'email': 'demo@example.test', 'password': 'private-password'})
    assert response.status_code == 503
    assert response.json() == {'detail': 'AUTH_RESPONSE_INVALID'}
    assert 'set-cookie' not in response.headers
    assert 'private' not in response.text
    provider._call.assert_called_once()


def test_non_json_login_provider_response_fails_safely(boundary):
    app, client, _, _, _ = boundary
    provider = SupabaseAuth('https://not-real.supabase.co', 'test-key')
    upstream = MagicMock(status_code=200)
    upstream.json.side_effect = ValueError('private-invalid-json-diagnostic')
    provider._call = MagicMock(return_value=upstream)
    app.state.auth = provider
    response = client.post('/api/auth/login', headers={'Origin': ORIGIN},
                           json={'email': 'demo@example.test', 'password': 'private-password'})
    assert response.status_code == 503
    assert response.json() == {'detail': 'AUTH_RESPONSE_INVALID'}
    assert 'set-cookie' not in response.headers
    assert 'private' not in response.text


def wait_for_startup(app, timeout=3):
    import time
    until=time.monotonic()+timeout
    while not app.state.startup_complete and time.monotonic()<until:
        time.sleep(0.005)
    assert app.state.startup_complete


def test_slow_database_cannot_block_http_listener_or_start_workers_early():
    from threading import Event
    import time
    entered,release=Event(),Event()
    db,auth=FakeDatabase(),FakeAuth()
    def gate():
        entered.set()
        assert release.wait(4)
        return {'restricted_role':'service_role'}
    db.permission_gate=gate
    app=create_app(settings(database_url='postgresql://not-real/',supabase_url='https://not-real.supabase.co',
        supabase_publishable_key='public',google_application_credentials='/not-real/key.json',
        google_spreadsheet_id='demo_spreadsheet_id'),db=db,auth=auth,sheets=MagicMock())
    workers=MagicMock();workers.running=False;app.state.workers=workers
    started=time.monotonic()
    with TestClient(app) as client:
        try:
            assert time.monotonic()-started<1
            assert entered.wait(1)
            assert client.get('/').status_code==200
            assert client.get('/health/live').status_code==200
            response=client.get('/health/ready')
            assert response.status_code==503 and response.json()['status']=='starting'
            assert response.headers['retry-after']=='2'
            workers.start.assert_not_called()
        finally:release.set()
        wait_for_startup(app)
        workers.start.assert_called_once()
    workers.stop.assert_called_once()


def test_slow_sheet_import_cannot_block_login_page_and_failed_import_preserves_readiness():
    from threading import Event
    entered,release=Event(),Event()
    db=FakeDatabase()
    config=settings(database_url='postgresql://not-real/',supabase_url='https://not-real.supabase.co',
        supabase_publishable_key='public',google_application_credentials='/not-real/key.json',
        google_spreadsheet_id='demo_spreadsheet_id',auto_import_on_startup=True)
    def slow_import(app):
        entered.set()
        assert release.wait(4)
        raise RuntimeError('private-provider-details-must-not-be-returned')
    app=create_app(config,db=db,auth=FakeAuth(),sheets=MagicMock())
    with patch('app.main.sync_reference',side_effect=slow_import),TestClient(app) as client:
        try:
            assert entered.wait(1)
            assert client.get('/').status_code==200
            assert client.get('/health/live').status_code==200
            assert client.get('/health/ready').status_code==503
        finally:release.set()
        wait_for_startup(app)
        assert app.state.startup=='reference_import_failed'
        assert client.get('/health/ready').status_code==200  # last valid snapshot remains current
        db.reference['fresh']=False
        assert client.get('/health/ready').status_code==503


def test_shutdown_interrupts_database_startup_backoff_without_starting_workers():
    from threading import Event
    import time
    failed=Event();db=FakeDatabase()
    def gate():
        failed.set();raise DatabaseUnavailable('private-connection-uri')
    db.permission_gate=gate
    app=create_app(settings(database_url='postgresql://not-real/'),db=db,auth=FakeAuth(),sheets=MagicMock())
    workers=MagicMock();app.state.workers=workers
    started=time.monotonic()
    with TestClient(app) as client:
        assert failed.wait(1)
        assert client.get('/health/live').status_code==200
    assert time.monotonic()-started<2
    workers.start.assert_not_called()


def test_database_recovers_without_a_redeploy_and_workers_start_once_after_permission_check():
    import time
    db=FakeDatabase();calls=[]
    def gate():
        calls.append(1)
        if len(calls)<3:raise DatabaseUnavailable('private-connection-uri')
        return {'restricted_role':'service_role'}
    db.permission_gate=gate
    app=create_app(settings(database_url='postgresql://not-real/'),db=db,auth=FakeAuth(),sheets=MagicMock())
    workers=MagicMock();app.state.workers=workers
    with patch('app.main.STARTUP_RETRY_SECONDS',0.01),TestClient(app) as client:
        wait_for_startup(app)
        assert len(calls)==3 and app.state.startup=='database_verified'
        workers.start.assert_called_once()
        response=client.get('/health/live')
        assert response.json()['version']=='0.6.0'
        assert 0<=response.json()['uptime_seconds']<3
        assert 'private' not in response.text

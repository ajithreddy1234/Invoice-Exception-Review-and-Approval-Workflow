from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

COOKIE = 'invoice_access'


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)


@dataclass(frozen=True)
class Actor:
    id: UUID
    display_name: str
    role: str


class SupabaseAuth:
    def __init__(self, url, key):
        self.url = url.rstrip('/')
        self.key = key
        self._client = httpx.Client(timeout=10, limits=httpx.Limits(
            max_connections=10, max_keepalive_connections=5, keepalive_expiry=60))

    def close(self):
        self._client.close()

    def _call(self, method, path, **kwargs):
        if not self.url or not self.key:
            raise HTTPException(503, 'AUTH_NOT_CONFIGURED')
        try:
            return self._client.request(method, f'{self.url}/auth/v1/{path}',
                                 headers={'apikey': self.key, **kwargs.pop('headers', {})},
                                 timeout=10, **kwargs)
        except httpx.HTTPError:
            raise HTTPException(503, 'AUTH_UNAVAILABLE') from None

    def login(self, email, password):
        r = self._call('POST', 'token?grant_type=password', json={'email': email, 'password': password})
        if r.status_code == 429:
            raise HTTPException(429, 'LOGIN_RATE_LIMITED')
        if r.status_code >= 500:
            raise HTTPException(503, 'AUTH_UNAVAILABLE')
        if r.status_code != 200:
            raise HTTPException(401, 'INVALID_CREDENTIALS')
        try:
            data = r.json()
            if not isinstance(data, dict) or not isinstance(data.get('user'), dict):
                raise ValueError
            UUID(data['user']['id'])
            if not isinstance(data.get('access_token'), str) or not data['access_token']:
                raise ValueError
            expiry = data.get('expires_in')
            if isinstance(expiry, bool) or not isinstance(expiry, int) or expiry <= 0:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise HTTPException(503, 'AUTH_RESPONSE_INVALID')
        return data

    def user_id(self, token):
        # Supabase validates signatures/expiry server-side, including key rotation.
        r = self._call('GET', 'user', headers={'Authorization': f'Bearer {token}'})
        if r.status_code in (401, 403):
            raise HTTPException(401, 'SESSION_EXPIRED')
        if r.status_code != 200:
            raise HTTPException(503, 'AUTH_UNAVAILABLE')
        try:
            return UUID(r.json()['id'])
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'AUTH_RESPONSE_INVALID') from None

    def logout(self, token):
        r = self._call('POST', 'logout?scope=local', headers={'Authorization': f'Bearer {token}'})
        if r.status_code not in (200, 204, 401, 403):
            raise HTTPException(503, 'AUTH_UNAVAILABLE')


def actor_for_id(request: Request, user_id: UUID):
    row = request.app.state.db.read_one('SELECT user_id,display_name,role,enabled FROM app.profiles WHERE user_id=%s', (user_id,))
    if not row or not row['enabled']:
        raise HTTPException(403, 'ACCOUNT_DISABLED_OR_UNPROVISIONED')
    return Actor(row['user_id'], row['display_name'], row['role'])


def verified_user_id(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'LOGIN_REQUIRED')
    return request.app.state.auth.user_id(token)


def current_actor(request: Request):
    return actor_for_id(request, verified_user_id(request))


def require_admin(request: Request):
    actor = current_actor(request)
    if actor.role != 'admin':
        raise HTTPException(403, 'ADMIN_REQUIRED')
    return actor


"""Private original files, accessed only through the authenticated backend.

No signed/public URLs are produced. The API layer must authorize the caller and
choose the object key; this privileged client does not implement ownership.
"""
from __future__ import annotations

from hashlib import sha256
import re
from urllib.parse import quote, urlsplit

import httpx

MAX_BYTES = 5 * 1024 * 1024
MIME_TYPES = frozenset({'application/pdf', 'image/jpeg', 'image/png'})


class StorageError(RuntimeError):
    """Sanitized provider error safe to persist as an operational failure."""


class StorageConflict(StorageError):
    pass


class StorageNotFound(StorageError):
    pass


class StorageGateway:
    def __init__(self, url: str, secret: str, bucket: str = 'invoice-originals', *, transport=None):
        parsed = urlsplit(url)
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if (not parsed.hostname or parsed.scheme not in ('http', 'https') or
                (parsed.scheme == 'http' and not local) or parsed.username or parsed.password or
                parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise StorageError('STORAGE_CONFIGURATION_INVALID')
        if not isinstance(secret, str) or not secret or '\n' in secret or '\r' in secret:
            raise StorageError('STORAGE_CONFIGURATION_INVALID')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', bucket):
            raise StorageError('STORAGE_CONFIGURATION_INVALID')
        self._base = url.rstrip('/') + '/storage/v1/object/' + quote(bucket, safe='')
        self._headers = {'apikey': secret}
        # Modern sb_secret keys are not JWT bearer tokens. Legacy service_role
        # JWTs need the Authorization header as well as the gateway apikey.
        if secret.startswith('eyJ'):
            self._headers['Authorization'] = 'Bearer ' + secret
        self._transport = transport

    @staticmethod
    def _key(key: str) -> str:
        if (not isinstance(key, str) or len(key) > 1024 or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', key) or
                any(part in ('', '.', '..') for part in key.split('/'))):
            raise StorageError('STORAGE_KEY_INVALID')
        return quote(key, safe='/')

    def _client(self):
        return httpx.Client(headers=self._headers, timeout=20, follow_redirects=False,
                            transport=self._transport)

    @staticmethod
    def _duplicate(response) -> bool:
        if response.status_code == 409:
            return True
        if response.status_code == 400:
            try:
                body = response.json()
                return isinstance(body, dict) and (body.get('error') == 'Duplicate' or
                       body.get('code') == 'ResourceAlreadyExists')
            except (ValueError, TypeError):
                pass
        return False

    def upload(self, key: str, data: bytes, mime_type: str) -> None:
        encoded = self._key(key)
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BYTES:
            raise StorageError('STORAGE_FILE_SIZE_INVALID')
        if mime_type not in MIME_TYPES:
            raise StorageError('STORAGE_MIME_INVALID')
        try:
            with self._client() as client:
                response = client.post(self._base + '/' + encoded, content=data,
                                       headers={'Content-Type': mime_type, 'x-upsert': 'false',
                                                'Cache-Control': 'no-store'})
            if response.status_code in (200, 201):
                return
            if self._duplicate(response):
                # A previous request may have committed before its response was
                # lost. Reusing a key is safe only for exactly the same bytes.
                existing = self.download(key)
                if sha256(existing).digest() == sha256(data).digest():
                    return
                raise StorageConflict('STORAGE_OBJECT_CONFLICT')
            raise StorageError('STORAGE_UPLOAD_UNAVAILABLE')
        except httpx.HTTPError:
            raise StorageError('STORAGE_UPLOAD_UNAVAILABLE') from None

    def download(self, key: str) -> bytes:
        encoded = self._key(key)
        try:
            with self._client() as client:
                with client.stream('GET', self._base + '/' + encoded) as response:
                    if response.status_code == 404:
                        raise StorageNotFound('STORAGE_OBJECT_NOT_FOUND')
                    if response.status_code != 200:
                        raise StorageError('STORAGE_DOWNLOAD_UNAVAILABLE')
                    declared = response.headers.get('content-length')
                    if declared is not None:
                        try:
                            if not 1 <= int(declared) <= MAX_BYTES:
                                raise StorageError('STORAGE_FILE_SIZE_INVALID')
                        except ValueError:
                            raise StorageError('STORAGE_DOWNLOAD_UNAVAILABLE') from None
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if len(data) + len(chunk) > MAX_BYTES:
                            raise StorageError('STORAGE_FILE_SIZE_INVALID')
                        data.extend(chunk)
                    if not data:
                        raise StorageError('STORAGE_FILE_SIZE_INVALID')
                    return bytes(data)
        except httpx.HTTPError:
            raise StorageError('STORAGE_DOWNLOAD_UNAVAILABLE') from None

    def delete(self, key: str) -> None:
        self._key(key)
        try:
            with self._client() as client:
                response = client.request('DELETE', self._base, json={'prefixes': [key]})
            # Bucket removal with a specific prefix is idempotent; missing means
            # the desired final state is already reached.
            if response.status_code not in (200, 204, 404):
                raise StorageError('STORAGE_DELETE_UNAVAILABLE')
        except httpx.HTTPError:
            raise StorageError('STORAGE_DELETE_UNAVAILABLE') from None

from unittest.mock import patch

import httpx
import pytest

from app.storage import MAX_BYTES, StorageConflict, StorageError, StorageGateway, StorageNotFound

URL = 'https://example.supabase.co'
KEY = 'private-user/submission-id/original.pdf'
DATA = b'%PDF-1.7\ninvoice contents'


def gateway(handler, secret='sb_secret_never-expose-this'):
    return StorageGateway(URL, secret, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize('secret,has_bearer', [('sb_secret_never-expose-this',False), ('eyJlegacy.jwt.signature',True)])
def test_upload_private_server_credentials_without_overwrite(secret, has_bearer):
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers['apikey'] == secret
        assert ('authorization' in request.headers) is has_bearer
        if has_bearer:
            assert request.headers['authorization'] == 'Bearer ' + secret
        assert request.headers['x-upsert'] == 'false'
        assert request.headers['content-type'] == 'application/pdf'
        assert request.content == DATA
        return httpx.Response(200, json={'Key': 'unused'})
    assert gateway(handle, secret).upload(KEY, DATA, 'application/pdf') is None
    assert requests[0].method == 'POST'
    assert requests[0].url.path == '/storage/v1/object/invoice-originals/' + KEY
    assert '/public/' not in str(requests[0].url)
    assert requests[0].extensions['timeout']['read'] == 20


@pytest.mark.parametrize('status,payload', [(409, {}), (400, {'error':'Duplicate'}),
    (400, {'code':'ResourceAlreadyExists'})])
def test_duplicate_upload_is_idempotent_only_when_hash_matches(status, payload):
    methods = []
    def handle(request):
        methods.append(request.method)
        return httpx.Response(status, json=payload) if request.method == 'POST' else httpx.Response(200, content=DATA)
    gateway(handle).upload(KEY, DATA, 'application/pdf')
    assert methods == ['POST', 'GET']


def test_different_bytes_at_same_key_are_never_overwritten():
    methods = []
    def handle(request):
        methods.append(request.method)
        return httpx.Response(409) if request.method == 'POST' else httpx.Response(200, content=b'other invoice')
    with pytest.raises(StorageConflict, match='STORAGE_OBJECT_CONFLICT'):
        gateway(handle).upload(KEY, DATA, 'application/pdf')
    assert methods == ['POST','GET']


def test_timeout_then_retry_verifies_previous_upload():
    saved = {}
    def handle(request):
        if request.method == 'POST':
            if not saved:
                saved['bytes'] = request.content
                raise httpx.ReadTimeout('private key and provider response', request=request)
            return httpx.Response(400, json={'error':'Duplicate'})
        return httpx.Response(200, content=saved['bytes'])
    client = gateway(handle)
    with pytest.raises(StorageError) as error:
        client.upload(KEY, DATA, 'application/pdf')
    assert 'private' not in str(error.value)
    client.upload(KEY, DATA, 'application/pdf')
    assert saved['bytes'] == DATA


@pytest.mark.parametrize('key', ['', '/absolute.pdf', '../original.pdf', 'folder/../original.pdf',
    'folder//original.pdf', 'folder/./original.pdf', 'folder/%2e%2e/x.pdf', 'folder\\x.pdf', '?secret=key'])
def test_invalid_keys_rejected_before_request(key):
    def unexpected(request):
        raise AssertionError('must not call network')
    with pytest.raises(StorageError, match='STORAGE_KEY_INVALID'):
        gateway(unexpected).upload(key, DATA, 'application/pdf')


@pytest.mark.parametrize('data,mime', [(b'','application/pdf'), (b'a'*(MAX_BYTES+1),'application/pdf'),
    (DATA,'text/html'), ('not bytes','application/pdf')])
def test_size_and_type_rejected_without_network(data,mime):
    def unexpected(request):
        raise AssertionError('must not call network')
    with pytest.raises(StorageError):
        gateway(unexpected).upload(KEY,data,mime)


def test_download_and_delete_are_private_and_specific():
    requests=[]
    def handle(request):
        requests.append(request)
        if request.method == 'GET':
            return httpx.Response(200, content=DATA)
        assert request.method == 'DELETE'
        assert request.content == ('{"prefixes":["' + KEY + '"]}').encode()
        assert request.url.path == '/storage/v1/object/invoice-originals'
        return httpx.Response(200, json=[])
    client = gateway(handle)
    assert client.download(KEY) == DATA
    assert client.delete(KEY) is None
    assert len(requests) == 2


@pytest.mark.parametrize('content,headers', [(b'a'*(MAX_BYTES+1),{}), (b'',{}),
    (b'a',{'content-length':str(MAX_BYTES+1)}), (b'a',{'content-length':'garbage'})])
def test_download_enforces_size_when_declared_or_streamed(content, headers):
    with pytest.raises(StorageError):
        gateway(lambda request: httpx.Response(200, content=content, headers=headers)).download(KEY)


def test_download_missing_object_has_sanitized_specific_error():
    with pytest.raises(StorageNotFound) as error:
        gateway(lambda request: httpx.Response(404, text='private upstream key')).download(KEY)
    assert str(error.value) == 'STORAGE_OBJECT_NOT_FOUND'


@pytest.mark.parametrize('method', ['upload','download','delete'])
@pytest.mark.parametrize('status', [403,429,500])
def test_errors_do_not_echo_secrets_or_keys(method,status):
    client = gateway(lambda request: httpx.Response(status, text='private-provider-key'))
    with pytest.raises(StorageError) as error:
        getattr(client, method)(KEY, DATA, 'application/pdf') if method == 'upload' else getattr(client,method)(KEY)
    assert 'private' not in str(error.value)
    assert KEY not in str(error.value)


@pytest.mark.parametrize('status', [200,204,404])
def test_delete_idempotent_success(status):
    assert gateway(lambda request:httpx.Response(status)).delete(KEY) is None


@pytest.mark.parametrize('code',[404,'404'])
def test_missing_object_wrapped_in_http_400_is_classified_without_leaking_body(code):
    client=gateway(lambda request:httpx.Response(400,json={'statusCode':code,'error':'not_found','message':'private upstream key'}))
    with pytest.raises(StorageNotFound) as error:client.download(KEY)
    assert str(error.value)=='STORAGE_OBJECT_NOT_FOUND'


@pytest.mark.parametrize('body',[
    b'{"statusCode":403,"message":"private"}',b'{"statusCode":400}',b'private html',
    b'[404]',b'{"error":"not_found"}', b'{"statusCode":404,"padding":"'+b'x'*5000+b'"}',
])
def test_other_or_oversized_400_bodies_are_not_misreported_as_missing(body):
    with pytest.raises(StorageError) as error:
        gateway(lambda request:httpx.Response(400,content=body)).download(KEY)
    assert not isinstance(error.value,StorageNotFound)
    assert str(error.value)=='STORAGE_DOWNLOAD_UNAVAILABLE'


@pytest.mark.parametrize('code',[404,'404'])
def test_delete_accepts_legacy_not_found_as_idempotent_success(code):
    assert gateway(lambda request:httpx.Response(400,json={'statusCode':code})).delete(KEY) is None


def test_delete_does_not_ignore_a_different_legacy_error():
    with pytest.raises(StorageError,match='STORAGE_DELETE_UNAVAILABLE'):
        gateway(lambda request:httpx.Response(400,json={'statusCode':403})).delete(KEY)

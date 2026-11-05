"""Bounded retries never retry invalid candidates or multiply SDK attempts."""
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app.extraction import DocumentText,PageText,GeminiExtractor,ExtractionError
from test_extraction import candidate


class ProviderError(Exception):
    def __init__(self,code):
        self.code=code
        self.response=SimpleNamespace(headers={'Retry-After':'90'})


def run(outcomes):
    calls=[];options=[];progress=[]
    class Client:
        def __init__(self,**kwargs):options.append(kwargs);self.models=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def generate_content(self,**kwargs):
            calls.append(kwargs);outcome=outcomes[len(calls)-1]
            if isinstance(outcome,Exception):raise outcome
            return SimpleNamespace(text=outcome)
    types=SimpleNamespace(HttpOptions=lambda **kw:kw,GenerateContentConfig=lambda **kw:kw)
    genai=SimpleNamespace(Client=Client,types=types)
    document=DocumentText(pages=[PageText(number=1,method='embedded',text='Invoice text')])
    with patch.dict('sys.modules',{'google':SimpleNamespace(genai=genai),'google.genai':genai}),patch('app.extraction.time.sleep') as sleep:
        try:
            value=GeminiExtractor('test-secret-not-real','model').extract(document,on_retry=lambda:progress.append('retry'))
            failure=None
        except ExtractionError as error:value=None;failure=error.code
    return value,failure,calls,options,progress,sleep


@pytest.mark.parametrize('error',[ProviderError(429),ProviderError(503),httpx.ReadTimeout('timeout')])
def test_one_transient_failure_retries_same_request_with_progress_and_no_sdk_retries(error):
    value,failure,calls,options,progress,sleep=run([error,candidate().model_dump_json()])
    assert value and not failure and len(calls)==2 and calls[0]==calls[1]
    assert options[0]['http_options']['retry_options']=={'attempts':1}
    assert progress==['retry']
    assert sleep.call_args.args[0]<=5


@pytest.mark.parametrize('error,code',[(ProviderError(429),'EXTRACTION_RATE_LIMITED'),
 (ProviderError(503),'EXTRACTION_PROVIDER_BUSY'),(httpx.ReadTimeout('timeout'),'EXTRACTION_TIMEOUT')])
def test_persistent_failure_stops_after_exactly_two_attempts(error,code):
    value,failure,calls,_,progress,_=run([error,error])
    assert value is None and failure==code and len(calls)==2 and progress==['retry']


@pytest.mark.parametrize('outcome',[ProviderError(400),ProviderError(401),ProviderError(403),'{}','not JSON',None])
def test_auth_configuration_invalid_json_and_empty_outputs_are_not_retried(outcome):
    value,failure,calls,_,progress,sleep=run([outcome])
    assert value is None and failure and len(calls)==1 and not progress
    sleep.assert_not_called()

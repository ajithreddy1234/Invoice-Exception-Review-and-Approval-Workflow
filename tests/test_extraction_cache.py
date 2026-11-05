from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from app.extraction import DocumentText,PageText
from app.extraction_cache import saved_extraction
from test_extraction import candidate


def test_invalid_stored_extraction_is_a_miss_instead_of_an_approval_shortcut():
    submission={'uploaded_by':uuid4(),'file_sha256':'a'*64,'mime_type':'application/pdf','byte_size':25}
    document=DocumentText(pages=[PageText(number=1,text='Total payable INR 10,000.00',method='embedded')]).model_dump(mode='json')
    for evidence in ({}, {'document':document,'candidate':{}}, {'document':None,'candidate':candidate().model_dump(mode='json')}):
        db=MagicMock();db.read_one.return_value={'id':uuid4(),'evidence':evidence}
        assert saved_extraction(db,submission,SimpleNamespace(gemini_model='model'),'pipeline') is None

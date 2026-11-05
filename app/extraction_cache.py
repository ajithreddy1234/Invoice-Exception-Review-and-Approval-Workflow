"""Reuse extraction evidence, never validation or decisions; no new storage table.

Only original provider revisions for the same uploader and exact file bytes may
be reused. Reused revisions cannot renew the original seven-day cache window.
"""
from pydantic import ValidationError

from .extraction import DocumentText, InvoiceCandidate, EXTRACTION_PROMPT_VERSION

READER_VERSION = 'invoice-document-v1'


def extraction_metadata(settings, source_revision_id=None):
    return {'model_id':settings.gemini_model, 'prompt_version':EXTRACTION_PROMPT_VERSION,
            'reader_version':READER_VERSION,
            'origin':'cache' if source_revision_id else 'provider',
            **({'source_revision_id':str(source_revision_id)} if source_revision_id else {})}


def saved_extraction(db, submission, settings, pipeline_version):
    if not settings.gemini_model:
        return None
    row=db.read_one('''SELECT r.id,r.evidence FROM app.invoice_revisions r
      JOIN app.submissions s ON s.id=r.submission_id
      JOIN app.processing_runs p ON p.revision_id=r.id
      WHERE s.uploaded_by=%s AND s.file_sha256=%s AND s.mime_type=%s AND s.byte_size=%s
      AND r.kind='extraction' AND r.created_at>now()-interval '7 days'
      AND p.pipeline_version=%s
      AND r.evidence #>> '{extractor,model_id}'=%s
      AND r.evidence #>> '{extractor,prompt_version}'=%s
      AND r.evidence #>> '{extractor,reader_version}'=%s
      AND r.evidence #>> '{extractor,origin}'='provider'
      ORDER BY r.created_at DESC LIMIT 1''',
      (submission['uploaded_by'],submission['file_sha256'],submission['mime_type'],submission['byte_size'],
       pipeline_version,settings.gemini_model,EXTRACTION_PROMPT_VERSION,READER_VERSION))
    if not row:
        return None
    try:
        document=DocumentText.model_validate(row['evidence']['document'])
        candidate=InvoiceCandidate.model_validate(row['evidence']['candidate'])
    except (ValidationError, KeyError, TypeError):
        return None
    return document,candidate,row['id']

"""Narrow human review permissions; source validation itself stays unchanged."""
from .extraction import EvidenceIssue, validate_evidence


def review_evidence(candidate, document, verified_ocr_fields=()):
    """Only acknowledge confidence when the text already supports the value.

    Never waive a missing value/quote, wrong identifier, unpaired OCR layout,
    conflicting total or any other source failure. The caller must authenticate
    the reviewer, freeze their reason/context and require explicit acceptance.
    """
    raw = validate_evidence(candidate, document)
    requested = set(verified_ocr_fields)
    eligible = {i.field for i in raw if i.code == 'LOW_OCR_CONFIDENCE'}
    eligible -= {i.field for i in raw if i.code != 'LOW_OCR_CONFIDENCE'}
    invalid = requested - eligible
    effective = [i for i in raw if not (i.code == 'LOW_OCR_CONFIDENCE' and i.field in requested & eligible)]
    effective += [EvidenceIssue(field=field,code='INVALID_OCR_VERIFICATION',
        detail='Human verification may acknowledge only an existing confidence warning with fully supported text.')
        for field in sorted(invalid)]
    return raw,effective

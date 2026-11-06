"""Read-only business explanations and timings from recorded facts."""
from datetime import datetime


def _time(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def recorded_timing(run, events):
    if not run:
        return {'stages': [], 'queue_seconds': None, 'processing_seconds': None}
    start, finish, queued = (_time(run.get(k)) for k in ('started_at', 'finished_at', 'created_at'))
    def elapsed(a, b):
        if a is None or b is None:
            return None
        try:
            return round((b-a).total_seconds(), 3) if b >= a else None
        except TypeError:
            return None
    rows = [e for e in events if str(e.get('run_id')) == str(run.get('id'))
            and e.get('event_type') == 'processing.stage' and _time(e.get('created_at'))]
    # SQL orders by event ID: repeated stages remain separate recovery attempts.
    stages = []
    for index, event in enumerate(rows):
        end = rows[index+1]['created_at'] if index+1 < len(rows) else run.get('finished_at')
        duration = elapsed(_time(event['created_at']), _time(end))
        stages.append({'stage': event.get('stage'), 'started_at': event['created_at'],
                       'finished_at': end if duration is not None else None,
                       'seconds': duration,
                       'state': 'recorded' if duration is not None else
                                'in_progress' if run.get('state') == 'running' else 'duration_unavailable'})
    return {'stages': stages, 'queue_seconds': elapsed(queued, start),
            'processing_seconds': elapsed(start, finish)}


def explain_decision(data):
    submission = data.get('submission') or {}
    acceptance = data.get('acceptance')
    validation = data.get('validation') or {}
    checks = {c['code']: c for c in validation.get('checks', [])}
    status = submission.get('status')
    publication = (data.get('publication') or {}).get('status')
    result = {'commitment': 'recorded' if acceptance else 'not_recorded',
              'report': (publication or 'pending') if acceptance else 'not_required',
              'financial_effect': 'The accepted invoice amount is recorded once against its PO.' if acceptance
                                  else 'No PO amount has been committed by this submission.'}
    def reason(code, text, action):
        return {**result, 'reason_code': code, 'primary_reason': text, 'next_action': action}
    if acceptance:
        return reason('ACCEPTED', 'Source evidence and procurement checks support the recorded acceptance.',
                      'No further decision is required.' if publication == 'published' else
                      'An administrator can inspect spreadsheet publication. Retrying publication must not accept the invoice again.')
    if status == 'accepted':
        return reason('INCONSISTENT_RECORD', 'An accepted status has no supporting ledger record.',
                      'An administrator must investigate. Do not infer that a commitment exists.')
    if status == 'rejected':
        reasons = [r.get('reason') for r in data.get('reviews', []) if r.get('action') == 'reject']
        return reason('REJECTED', reasons[0] if reasons else 'An administrator rejected this invoice.',
                      'Resolve the recorded rejection reason with the supplier or procurement team before submitting a corrected invoice.')
    if status == 'blocked_duplicate':
        return reason('DUPLICATE', 'This file or vendor/invoice identity matches an already accepted invoice.',
                      'Inspect the prior record if you have access, or ask an administrator. Do not submit it again to consume another PO balance.')
    if status == 'expired':
        return reason('SOURCE_EXPIRED', 'The original source has reached its retention limit.',
                      'Upload an authorized readable original for a new verification. Retained history remains available.')
    if status == 'processing_failed':
        return reason((data.get('run') or {}).get('error_code') or 'PROCESSING_FAILED',
                      'Document processing did not finish; no financial decision was committed.',
                      'Inspect the recorded error. Retry a temporary service failure; replace an unreadable or unsupported source. No approval can be inferred.')
    if status in ('received', 'processing') or (data.get('run') or {}).get('state') in ('queued', 'running'):
        return reason('PROCESSING', 'Verification is still running or queued.',
                      'Wait for the recorded outcome. The stage view shows saved events, not simulated progress.')
    reference = data.get('reference')
    if status == 'reference_hold' or (reference and (reference.get('fresh') is False or reference.get('is_active') is False)):
        return reason('REFERENCE_REFRESH_REQUIRED', 'The validation references are stale or no longer active.',
                      'An administrator must sync approved procurement data and rerun verification before any acceptance.')
    candidate = ((data.get('revision') or {}).get('evidence') or {}).get('candidate') or {}
    if candidate and not (candidate.get('total_gross') or {}).get('value'):
        return reason('PAYABLE_MISSING', 'The payable total is missing or unreadable in the extracted source evidence.',
                      'Request a clearer original. Subtotal, tax or PO balance cannot replace a missing printed payable total.')
    messages = {
        'required_fields': ('Critical information is missing, ambiguous or unsupported.', 'Verify the named missing fields against the original. Correct supported extraction with evidence or request a clearer/corrected invoice.'),
        'source_evidence': ('One or more extracted values lack reliable or consistent source evidence.', 'Compare the quoted page with the original. An administrator may correct supported extraction or confirm a grounded OCR warning; missing or contradictory values remain blocking.'),
        'duplicate_check': ('The duplicate protection check did not pass.', 'Ask an administrator to inspect the prior accepted identity. Do not override duplicate protection.'),
        'vendor_match': ('The supplier has no unique approved match.', 'Verify the printed supplier and authorized vendor master. Procurement must resolve onboarding or master-data issues; do not invent an approved vendor.'),
        'po_match': ('A unique authorized purchase order has not been resolved.', 'Verify the original and approved procurement records. An administrator may select only among exact inferred candidates when no PO is printed.'),
        'currency': ('The invoice currency does not have a valid matching PO and rule.', 'Verify invoice/PO currency and configured procurement rules. No currency conversion is performed.'),
        'line_allocation': ('Invoice charges cannot be allocated to supported authorized PO lines.', 'Verify quantities, units, prices and tax. A reasoned description mapping may preserve original wording; it cannot create missing quantities or raise authorization.'),
        'arithmetic': ('The printed payable, line amounts or tax do not reconcile under the recorded policy.', 'Check the original line amounts, tax and evidenced rounding. Request a corrected invoice when the source itself is inconsistent.'),
        'po_balance': ('The PO value, cumulative quantity or billing policy does not permit acceptance.', 'Check remaining authorization. Obtain a corrected invoice or a genuine approved PO amendment, sync and revalidate. An admin cannot override the cap.'),
    }
    for code, (text, action) in messages.items():
        item = checks.get(code)
        if item and item.get('status') != 'pass' and not item.get('blocked_by'):
            if code == 'required_fields':
                unresolved = (data.get('revision') or {}).get('unresolved_critical_fields') or []
                if 'invoice_date' in unresolved:
                    return reason('DATE_REVIEW_REQUIRED', 'The invoice date is missing or uses an unsupported or ambiguous format.',
                                  'Compare the printed date with the original. Use a supported, evidenced extraction or request a corrected invoice; do not guess a slash-date locale.')
                if 'invoice_number' in unresolved:
                    return reason('INVOICE_NUMBER_REQUIRED', 'The invoice number is missing or cannot be reliably identified.',
                                  'Verify the labelled invoice number against the original or request a clearer source. A PO/customer number is not a substitute.')
            if code == 'source_evidence':
                issues = ((data.get('revision') or {}).get('evidence') or {}).get('issues') or []
                if any(i.get('code') == 'CONFLICTING_PAYABLE_VALUES' for i in issues):
                    return reason('CONFLICTING_PAYABLE_VALUES', 'The source contains conflicting payable totals.',
                                  'Request a corrected invoice with one consistent payable total. Neither admin confirmation nor PO balance resolves contradictory totals.')
                if any(i.get('code') == 'LOW_OCR_CONFIDENCE' for i in issues):
                    return reason('OCR_REVIEW_REQUIRED', 'The document reading contains uncertain source evidence.',
                                  'Compare the original with the quoted values. An admin may confirm an already grounded OCR warning; unsupported values still require correction or a clearer source.')
            if code == 'po_match':
                subtype = item.get('reason_code')
                if subtype == 'AMBIGUOUS_PO' or len(validation.get('po_candidates', [])) > 1:
                    return reason('AMBIGUOUS_PO', 'More than one exact PO candidate matches this invoice.',
                                  'An administrator must verify and select the correct exact candidate, save and rerun checks, then accept separately if eligible. Keep an absent printed PO field empty.')
                if subtype == 'PO_CLOSED':
                    return reason(subtype, 'The printed purchase order is closed.', 'Procurement must verify authorization. Obtain a corrected invoice or a genuine approved procurement change; do not substitute another PO.')
                if subtype == 'PO_NOT_REGISTERED':
                    return reason(subtype, 'The printed PO reference is absent from the active approved procurement data.', 'Verify the printed reference with procurement. Import genuine approved PO and line records and revalidate; do not create data just to pass.')
                if subtype == 'PO_VENDOR_MISMATCH':
                    return reason(subtype, 'The printed PO belongs to a different supplier.', 'Verify the supplier and PO against the original and procurement records. Do not substitute an unrelated PO to pass.')
            return reason(code.upper(), text, action)
    if validation.get('verdict') == 'eligible' and validation.get('acceptance_mode') == 'admin_required':
        return reason('ADMIN_ACCEPTANCE_REQUIRED', 'All checks passed after review; explicit administrator acceptance is required.',
                      'An administrator must record a separate acceptance reason. Saving a correction alone does not commit PO value.')
    if validation.get('verdict') == 'eligible':
        held = [e for e in data.get('audit', []) if e.get('event_type') == 'acceptance.recheck_held'
                and str(e.get('run_id')) == str((data.get('run') or {}).get('id'))]
        if held:
            return reason('FINAL_RECHECK_HELD', 'The final acceptance transaction held the invoice after rechecking current authorization or duplicates.',
                          'Inspect the recorded recheck reason and rerun verification against current references/commitments. Earlier passing checks are not a committed acceptance.')
        return reason('ELIGIBLE_NOT_COMMITTED', 'Recorded validation is eligible, but no acceptance transaction has committed.',
                      'Wait for or inspect the final acceptance transaction. Eligibility alone does not consume PO balance.')
    return reason('VERIFICATION_REQUIRED', 'No recorded acceptance is available.',
                  'Inspect the recorded checks and processing state before taking action.')

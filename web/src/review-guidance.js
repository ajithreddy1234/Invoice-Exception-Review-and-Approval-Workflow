// Guidance comes from recorded checks and source fields, never filenames or
// expected fixture outcomes. It cannot change eligibility or authorize a write.
export function reviewGuidance(data, role) {
  if (data.acceptance || !['needs_review','reference_hold'].includes(data.submission?.status)) return null;
  if (['queued','running'].includes(data.run?.state)) return null;
  const admin = role === 'admin';
  const checks = data.validation?.checks || [];
  const po = checks.find(c => c.code === 'po_match');
  const candidate = data.revision?.evidence?.candidate;
  const reference = candidate?.po_reference?.value;
  const candidates = data.validation?.po_candidates || [];
  const ambiguous = po?.reason_code === 'AMBIGUOUS_PO' || (po?.status === 'review' && !reference && candidates.length > 1);
  const unregistered = po?.reason_code === 'PO_NOT_REGISTERED' || (po?.status === 'review' && reference && candidates.length === 0 && !data.validation?.po_code);
  if (ambiguous) return {
    title: 'A purchase order must be selected',
    message: admin
      ? 'Open “Correct extraction & resolve PO”, choose the verified exact candidate under “Purchase order selection”, enter a review reason and save. Keep the PO-reference field empty when the invoice prints no PO. After every check passes, enter a separate decision reason and use “Accept with reason”.'
      : 'More than one approved PO fits this invoice. An administrator must verify the correct PO and record the selection. You can track the result here.',
  };
  if (unregistered) return {
    title: 'PO reference has no approved match',
    message: `The extracted reference ${reference || ''} has no match in the active procurement data. Check it against the original. ${admin
      ? 'Have procurement verify its approved PO and line records, sync references, then rerun verification. Reject with a reason only if the invoice is not authorized. Do not substitute another PO or create reference data merely to make the checks pass.'
      : 'Ask an administrator to verify the approved procurement records. Changing invoice amounts or choosing another PO will not resolve this missing reference.'}`,
  };
  if (data.validation?.verdict === 'eligible' && data.validation.acceptance_mode === 'admin_required') return {
    title: 'Ready for explicit admin acceptance',
    message: admin ? 'The review is saved and all checks pass. Under “Review actions”, enter a decision reason and select “Accept with reason”. Saving corrections alone does not accept the invoice.'
      : 'All checks pass after review. An administrator must record the explicit acceptance.',
  };
  if (po?.status === 'pass' && checks.some(c => c.code === 'po_balance' && c.status !== 'pass')) return {
    title: 'PO authorization needs review',
    message: 'Check the remaining PO value, quantity and billing policy. Acceptance cannot exceed authorization. Request a corrected invoice or a genuine approved PO amendment; otherwise an administrator can reject with a reason.',
  };
  return null;
}

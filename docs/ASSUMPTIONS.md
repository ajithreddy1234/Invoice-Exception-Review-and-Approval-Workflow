# Case-study assumptions and boundaries

- One procurement workspace; normal users see their submissions, admins see the workspace.
- One PO per positive invoice. Credit notes, reversals, multiple-PO allocations and payments are outside this workflow.
- Google Sheets contains authorized vendors, POs, lines and rules. Imports validate immutable snapshots; invalid imports preserve the last valid data. An editable Sheet is not proof that a procurement change was authorized.
- Postgres owns accepted invoice identities, amounts and quantities. Existing company POs require reconciled opening commitments/duplicate history, or rollout must start with genuinely new POs. An empty ledger is not evidence of an unspent historical PO.
- The supplied reference dataset configures INR. Code paths support INR/USD when valid rules and reference data exist; no currency conversion is performed. Do not claim USD is configured merely because the parser recognizes it.
- Source text/OCR establishes what was read, not supplier authenticity, buyer identity or goods/service receipt. This is invoice-to-PO verification, not receipt matching.
- PDFs/JPEG/PNG, English OCR, up to 5 MiB and three pages. The supported date parser accepts ISO and named-month formats. Slash dates are held rather than silently interpreted by an assumed locale.
- Bundled amounts without supported quantities/units/prices cannot borrow missing values from a PO. Explicit source-backed units can be allocated under the normal rules.
- Missing payable totals cannot be supplied from arithmetic or the PO. Only an already grounded LOW_OCR_CONFIDENCE field may be confirmed against a readable original.
- Admins may correct extraction with source evidence or select among exact inferred candidates; they cannot replace a contradicting printed PO or override duplicate/financial failures. Current scope does not enforce independent manual approval or a future-date/age policy.
- Stale or changed reference data prevents new acceptance, including manual acceptance. Past valid commitments stay recorded; the policy panel uses the snapshot from that validation.
- Originals expire after seven days; derived evidence, identities, decisions and audit history remain. Retention is fixed, not configurable. Company retention, approved model processing and backup/restore operations require separate agreement.
- A document request is an in-app record, not an email. No email intake, payment, generated output invoice, ERP integration or multi-tenant SaaS is claimed.
- Free hosting can sleep and providers can be unavailable. Recorded failures remain unaccepted. An idle-start result, a warm response and a local Docker run are different evidence.

These notes are for the case-study pitch and repository. The application keeps
normal operational navigation and policy evidence; it does not contain a demo guide.

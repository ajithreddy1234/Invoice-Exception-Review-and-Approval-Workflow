# Five-minute invoice review demonstration

Use synthetic documents only. Authentication is required. Share separately chosen
demo Auth credentials with the recruiter; the DB password and provider keys are
never demo login credentials. Existing setup currently uses the owner's two Auth
users, so do not put their personal passwords in the README or public submission.

## Before recording/interview

- Open the actual deployment in advance; verify readiness and admin diagnostics.
  Sync references if stale. Confirm Gemini free-tier quota and source availability.
- Check the current ledger, pending publications and remaining PO balances.
  Accepted invoices cannot be reused as a fresh acceptance. There is no destructive
  reset button. Use existing accepted records when explaining prior success.
- Pick one never-accepted fixture with an available matching PO for fresh extraction.
  The app must validate it; fixture expected outcomes are never sent to Gemini.
- Have both an admin and normal-user browser session available. Test permissions
  separately; do not accidentally record real passwords/API keys.
- Keep source PDFs open locally as a fallback explanation if a provider is down.
  Label any previously processed example as historical, never as fresh extraction.

## Talk track

| Time | Action and point to demonstrate |
| --- | --- |
| 0:00–0:30 | Sign in and open Upload. PDF/JPG/PNG, 5 MiB, three-page bound. |
| 0:30–1:30 | Upload the selected fresh readable document. Show real stages, extracted source quotes and nine checks. Exact eligible invoices may auto-accept; the LLM proposes fields only. |
| 1:30–2:10 | Open an accepted record and its immutable acceptance ID. Show publication status and its matching `AcceptedInvoices` report row. Acceptance is a DB transaction; Sheet publication can lag. |
| 2:10–2:45 | Re-upload an already-accepted original (e.g. `happy_full.pdf`) and show duplicate protection without another acceptance/balance deduction. |
| 2:45–3:45 | Open the blurred-total record or upload the scan. Compare its preview, missing/unsupported payable field and review checks. Admin records a request for a clearer source; never computes a payable total to fill a missing printed amount. |
| 3:45–4:30 | Show an evidenced admin correction/PO choice on a reviewable original. Save creates another revision and reruns checks. Explicit admin acceptance is separate and unavailable while a check fails. |
| 4:30–5:00 | Dashboard company bars, invoice list and partial PO balance. Explain DB authority, imported Sheet references, durable report retry and one deployment limitation. |

Live model extraction can exceed the allocated minute. Show its running stage and
continue with a clearly labelled historical record, then return to its real result.
Never substitute fixture expected values or claim an unobserved success.

## Fixtures and current development ledger

The existing development ledger has genuine synthetic acceptances: PO-FULL
₹10,000, PO-PARTIAL ₹6,000 and PO-AMBIG-A ₹5,000, totalling ₹21,000 as verified
in Step 4. Recheck live totals before use. No payment was executed.

| File / record | Intended demonstration | Important dependency |
| --- | --- | --- |
| `happy_full.pdf` / existing accepted record | Happy-path evidence and report | Already accepted; new upload should be duplicate |
| `split_6000.pdf` / existing acceptance | Partial PO consumption | Already uses ₹6,000 of PO-PARTIAL |
| `split_4500.pdf` | Invoice exceeds the remaining ₹4,000 | Only holds for balance while remaining is below ₹4,500 |
| `split_4000.pdf` | Remaining balance fits exactly | Accepting consumes the rest; one-time on this ledger |
| `scan_blurred_total.pdf` | Unreadable printed payable stays unknown | No inferred/admin-invented total |
| `ambiguous_no_po.pdf` / existing revision history | Ambiguous exact candidates, correction and explicit admin approval | Already accepted after review; use history rather than a second acceptance |
| `vendor_unknown_name.pdf` | Unknown vendor → review | Printed PO cannot establish vendor identity |
| `tax_mismatch.pdf` | Printed subtotal/tax/total disagree | Arithmetic failure must remain held |
| `race_a_6000.pdf` + `race_b_6000.pdf` | Native concurrency proof | Fresh PO-RACE ₹10,000; one ₹6,000 acceptance, second cannot overspend |

Cross-format scan fixtures intentionally share an invoice identity. They are not
independent fresh-acceptance scenarios. Accepting one makes the others duplicates.

## Evidence and limitations to state candidly

The isolated native Postgres suite proves row locks, duplicate uniqueness and
transaction rollback under real separate connections. External providers are
simulated there; prior separate live-cloud results prove actual integrations.
Run `npm run test:native-api` to reproduce native evidence without using cloud data.

No email ingestion, output-invoice generation, payment, currency conversion,
tenant isolation, destructive reset or extraction cache is implemented. Sources
expire after seven days; hashes, extracted evidence and ledger history remain.
Admin cannot bypass a failed financial/evidence check. Current supported OCR is
English; quotas, free-host sleep and poor source quality can hold processing.

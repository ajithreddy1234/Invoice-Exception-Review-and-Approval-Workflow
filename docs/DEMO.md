# Five-minute evaluator demonstration

App: https://asa-invoice-review.onrender.com

Use the dedicated admin/user credentials supplied privately. Do not put passwords
in the repository, sample ZIPs or recording. The deployed application contains
only the normal invoice workflow. Use this repository document for the walkthrough.
Download the source archive and select a verified unused pack under
`tests/fixtures/demo_packs/`; there is no in-app sample-download endpoint.

## Prepare

Reserve an unused, imported pack for the evaluator and use a different authorized
PO for release verification. No static pack name guarantees unused data. Packs are shared across the workspace;
check the actual invoice history and PO balances before starting. Re-uploading an accepted file
must be blocked. The system never deletes the ledger to make a demo appear fresh.

Open the deployment in advance, check reference freshness, and allow any inactive
service to start. Choose an unused pack from `tests/fixtures/demo_packs/`. The package
contains seven synthetic PDFs and a scenario guide. Their expected results are
instructions for the evaluator, never inputs to extraction or approval logic.

## Demonstrate the process

| Order | File | What to show |
| --- | --- | --- |
| 1 | `01_clean_invoice.pdf` | Real extraction, source quotes, all nine checks, automatic acceptance and separate spreadsheet publication status |
| 2 | `02_duplicate_invoice.pdf` | Same source identity; blocked without another acceptance or balance deduction |
| 3 | `03_partial_6000.pdf` | Accepts six of ten authorized hours; INR 4,000 remains |
| 4 | `04_partial_over_4500.pdf` | Exceeds that remaining value/quantity; held without consuming balance |
| 5 | `06_ambiguous_po.pdf` | No printed PO and two exact candidates within this pack; admin review is required |
| 6 | `07_blurred_total.pdf` | Real OCR, unsupported payable total remains unknown; request a clearer source |

`05_partial_remainder_4000.pdf` is optional. Demonstrate the INR 4,500 hold first;
accepting the final INR 4,000 consumes the remaining budget and changes later
outcomes. Each pack's scan uses its own PO so the earlier clean acceptance does
not mask source uncertainty with an already-consumed PO.

Keep the recording to five minutes. Use two deliberate exceptions, rather than
rushing through the whole fixture set:

| Time | Show |
| --- | --- |
| 0:00–0:30 | The buyer's problem: verify supplier charges without silently overspending a PO. The model extracts; code decides. |
| 0:30–1:45 | One fresh clean extraction, saved stage timestamps, nine checks, the acceptance ID and its matching Sheet report row. |
| 1:45–2:30 | Duplicate blocked; no second PO commitment. Follow the prior-record link only if the account has access. |
| 2:30–4:15 | Ambiguous PO: inspect the exact candidates, select the supported one with a reason, save and revalidate, then explicitly accept separately. Show the saved revision. |
| 4:15–5:00 | Dashboard outcomes, straight-through acceptance definition and timing sample; state the key limitations. |

Choose the admin line-mapping example below instead of ambiguous PO if it better
explains the business. Rehearse actual extraction/publication timing. If a live
run needs longer, label any historical record you show; never substitute fake
progress or describe cached extraction as fresh.

A blurred **missing payable total is not the admin-acceptance example**. It must
stay held while a clearer source is requested. An admin can confirm a grounded
OCR confidence warning, but cannot derive a missing total from a PO or arithmetic.

## Explain the decisions

The model proposes fields from page text. Deterministic checks decide eligibility;
SQL locks the PO and rechecks source/reference freshness, duplicate identity and
cumulative commitments. Postgres owns the financial ledger. Sheets supplies
reference records and receives an acceptance report; its publication can retry
without accepting again.

Admin correction requires source quotes and a reason, preserves earlier revisions
and reruns the same checks. Selecting an ambiguous PO is limited to exact matches.
Explicit approval is a separate action. An admin cannot invent an unreadable
total or bypass failed financial/evidence checks. Acceptance never executes payment.

## If extraction is unavailable

A transient 429/503/timeout is retried once with a visible stage. A second failure
leaves the invoice unaccepted with a clear reason. Invalid candidate JSON, missing
source fields and configuration/auth errors are not solved by repeated requests.
For an identical previously reviewed file, matching original provider extraction
can be reused for seven days for that uploader. **Using saved extraction** is
shown explicitly; quotes and all nine checks are checked again against the current
reference and ledger. Model/prompt/reader/pipeline changes force fresh extraction.
There is no fixture-result shortcut. Show at least one fresh extraction and label
any reused or historical evidence honestly.

## Prepare a later pack

An authorized operator can generate another pack (for example D), inspect the
read-only preparation plan, then append/import its matching references:

```sh
.venv/bin/python tools/generate_fixtures.py --pack D
.venv/bin/python scripts/prepare_demo.py --packs D
.venv/bin/python scripts/prepare_demo.py --packs D --apply
```

The assets remain offline; provide their ZIP separately for the walkthrough.
Existing conflicting codes are rejected. Matching rows are reused without duplicates; unchanged current references
do not need a new version. No accepted records or report rows are reset.

## State the limits

Single workspace, synthetic samples, English OCR, PDF/JPEG/PNG, 5 MiB and at most
three pages. Originals expire after seven days; extracted evidence, hashes and
ledger/audit history remain. There is no payment, email delivery, generated output
invoice, currency conversion or ERP integration. Host sleep and model quotas are
deployment dependencies. The native tests reproduce concurrency/rollback evidence
in an isolated local Postgres database without resetting cloud data.

## Controlled admin example

Pack D includes `08_admin_line_review.pdf` and an independent REVIEW PO. Its
printed description is abbreviated; all units, quantities and prices remain
supported. Open admin review, map line 1 to SERVICE, give the
business/evidence reason and save. Show that acceptance is still empty, then use
the separate explicit acceptance action and inspect the recorded mapping. No
printed field is rewritten to match the PO.

Do not assume Pack D is unused or imported. Inspect the actual active references,
history and remaining commitments first. Reference imports and financial writes
need the workspace owner's authorization. New packs can include this example:

```sh
.venv/bin/python tools/generate_fixtures.py --pack E --admin-review
```

The normal source-only preparation tool can plan E's additive rows. Do not apply
changes or reset accepted records just to make a rehearsal appear fresh. For a
five-minute recording, prioritize a fresh clean acceptance, a duplicate and one
reasoned admin resolution; use other edge cases during the live walkthrough.

## Additional input-layout evidence

`tests/fixtures/layouts/` contains eight clearly labelled synthetic inputs:
ReportLab card/table layouts, actual LibreOffice Writer PDF exports, a rasterized
scan and a simulated rotated photograph. See its README for independent-ledger
requirements. These are robustness tests, not claims of supplier authenticity or
real Zoho/Stripe exports. The evaluation script can exercise real Gemini without
writing an acceptance or a spreadsheet row. Neither manifest expectations nor
reference PO data are sent to the model.

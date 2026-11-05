# Five-minute evaluator demonstration

App: https://asa-invoice-review.onrender.com

Use the dedicated admin/user credentials supplied privately. Do not put passwords
in the repository, sample ZIPs or recording. The deployed application contains
only the normal invoice workflow. Use this repository document for the walkthrough.
Download the source archive and open `tests/fixtures/demo_packs/C/invoice-demo-C.zip`
for the reserved sample pack; there is no in-app sample-download endpoint.

## Prepare

Use pack B for rehearsal and reserve an unused pack for the evaluator. Pack C is
provided separately for that purpose. Packs are shared across the workspace;
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

Keep the recording to five minutes: orient/login, upload the clean PDF, show
acceptance plus published report, demonstrate a duplicate and one or two review
cases, then explain the dashboard and audit history. Clearly label historical
records if using them while a live run finishes.

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

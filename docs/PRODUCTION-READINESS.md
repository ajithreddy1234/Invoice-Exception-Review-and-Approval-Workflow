# Case-study completion and company readiness

Assessment: 6 November 2026, application v0.9.0.

The running application implements PS-1's invoice-to-decision workflow. It has
upload, observable processing stages, source evidence, nine checks, admin review,
history and dashboards. Four deliberate edge-case families are duplicate invoices,
partial invoices/overbilling, ambiguous POs and unreadable critical fields. Tax,
rounding, missing fields, aliases and concurrent acceptance support these cases.
A five-minute video and delivery of the live link/private evaluator credentials
remain submission actions; software tests do not prove those actions happened.

## Business rules and accounting authority

Google Sheets supplies approved vendors, POs, PO lines and currency/rule settings.
Validated imports activate immutable snapshots; invalid imports preserve the last
valid version. Decisions require fresh references. Postgres owns accepted invoices,
identity uniqueness, quantity/value commitments and audit history. The
AcceptedInvoices tab is a report. Failed publication never reverses or repeats an
acceptance. No payment instruction is created.

Money is stored in integer minor units and quantities use decimal arithmetic.
Remaining PO value is authorized gross less accepted gross. This assumes the
ledger contains all commitments for the PO; the synthetic evaluation begins with
new POs. Existing company commitments require a reconciled opening import or
a rollout restricted to new POs. Review/rejection and
duplicates do not consume value. Acceptance is a transaction with PO locking and
freshness, identity and balance rechecks. Line quantities are cumulative as well
as monetary commitments. Full/partial billing and approved tolerances are explicit.

The model proposes fields from embedded text or local OCR, with a page and quote.
It does not decide eligibility. Unreadable payable values stay unknown. Neither
subtotal arithmetic nor the remaining PO balance can fill a missing payable total.
Printed-field evidence establishes what the document says; it does not establish
that the supplier issued it or that goods/services were delivered. Supplier
onboarding and receipt authorization remain business controls.

Admin corrections preserve prior evidence, need a reason and still run every
check. A separate explicit action accepts an eligible corrected invoice.

## Gaps closed in this release

| Finding | Change | Proof |
| --- | --- | --- |
| A PO number actually printed on the page could be proposed as the invoice ID | Require a labelled invoice/bill identifier; contradictory IDs hold for review. Preserve OCR word coordinates to pair stacked fields without mixing columns. Unsupported layouts hold safely. | Actual PDF substitution, changed-byte re-export, conflicting IDs, labels, OCR geometry and real clean/blurred scan tests |
| Search covered only the latest 200 submissions | Ownership-scoped server search and stable keyset pages over full history; dashboard totals remain independent | 225-record pagination with tied timestamps, older-record search, status/vendor filters, role/owner isolation and inserts between pages |
| Original download did not verify stored bytes | Verify SHA-256 before returning the original, matching preview/processing safeguards | Corrupted original returns conflict; committed acceptance is unchanged |
| Intake could create unlimited pending jobs | Short database advisory lock reserves capacity atomically; defaults 20 per uploader and 100 workspace-wide; retries obey limits and replay remains idempotent | Concurrent upload race, per-user limit, retry limit and replay tests |
| Expired queued source could incur extraction work | Stop before storage/OCR/model access and record expiry | Native test verifies no source/provider calls |
| Whitespace reasons reached SQL before rejection | Strip before request length validation; SQL guards remain in place | Whitespace/short-reason validation tests |

No ledger redesign, database migration, paid dependency or new provider is needed.
Changing the reader/prompt/pipeline versions invalidates old extraction reuse;
the first processing of an old unaccepted file needs current provider capacity.
Previously accepted records remain unchanged and still block duplicates.

## Required before real company use

| Gate | Why it is legitimate | Required decision or implementation |
| --- | --- | --- |
| Approved model-data processing | Invoice text can contain confidential or personal information; text-only extraction still sends it to an external provider | Review the actual account/region terms and company data policy. Google's unpaid-service terms caution against submitting sensitive/confidential/personal information and allow data use/human review, with regional differences. Use an approved processing arrangement before live records. No billing/provider migration was authorized or performed. |
| Opening commitments and duplicate history | A company's existing POs may already have approved invoices outside this app; an empty local ledger cannot know their consumption | Start with genuinely new POs, or reconcile and import verified historical accepted invoices/opening commitments and duplicate identities before activating existing POs. The report tab must not silently become a second ledger. No opening financial entries were invented by this release. |
| Approval authority and segregation of duties | One admin role is too broad where company policy requires independent review or high-value authorization | Obtain approval matrix, define value thresholds and requester/approver restrictions, then enforce those rules at acceptance and in role management. Do not invent financial limits. Current per-currency auto-accept on/off is not a complete approval matrix. |
| Authorized reference changes | Sheet editor access is currently authority to change reference data; snapshot validation checks structure and existing commitments, not business authorization | Name procurement owners, restrict editor access, and add reviewed reference-change approval if required. Keep report tabs distinct from reference tabs. |
| Buyer and receipt checks | A valid vendor/PO and arithmetic do not prove the right buyer was billed or goods/services were received | Add buyer legal entities/tax identifiers and receipt/service-approval data. Implement bill-to matching and two-/three-way matching according to actual process. Until then this is invoice/PO verification, not proof of delivery. |
| Credit notes, reversals and invoice lifecycle | Editing/deleting an acceptance breaks history; legitimate credits need separate accounting treatment | Design linked credit/reversal entries and downstream reconciliation. Current scope supports positive invoices, no cancellation/payment ledger. Agree the namespace for invoice-number reuse across entities/years before changing uniqueness. |
| Source retention, privacy and recovery | Seven-day source expiry is an evaluation policy, not a company's approved records policy | Approve retention and deletion rules for originals and extracted evidence, configure/implement them, back up both DB and private objects, and demonstrate a restore. A DB backup does not include source files. |
| Credentials and staff identity | Shared evaluator accounts and previously disclosed credentials are unsuitable for business operations | Rotate disclosed secrets, provision named staff accounts, verify least-privilege database/Storage access, and select MFA/SSO/revocation procedures as required. Runtime should use a dedicated restricted database login; a migration-owner credential with per-transaction role switching remains more powerful if compromised. No rotation is claimed by this release. |
| Availability and monitoring | Sleeping workers cannot offer continuous processing; configured provider keys do not establish current quota | Choose always-on hosting with agreed recovery targets, monitor job age, extraction failures, publication backlog and reference freshness, and alert an operator. Load-test the agreed volume. |
| Deployment controls | Local regression evidence alone does not enforce future release quality | Add controlled CI checks, reviewed changes, staging and a rollback procedure. This release's tests were executed locally and the published release is separately probed. |

Render documents that Free instances sleep after 15 idle minutes and advises
against using them for production: https://render.com/docs/free . Supabase's
backup documentation recommends offsite exports on Free and states database
backups exclude Storage objects:
https://supabase.com/docs/guides/platform/backups . A zero-cost evaluation build
is feasible; guaranteed company availability and recovery cannot be promised by
this deployment.

Google's current Gemini API terms (effective March 23, 2026), checked during this
assessment: https://ai.google.dev/gemini-api/terms . Synthetic samples can keep
this evaluation free; do not treat the current unpaid model configuration as an
approved confidential processing channel. Local OCR does not change that the
extracted page text is sent to Gemini.

## Improvements that depend on actual workflow

Email intake, supplier notifications, ERP export, case/SLA escalation and links
between a replacement invoice and the original case are useful when a company
needs them. An in-app clearer-source request currently sends no email. None is a
substitute for the controls above. A single-company workspace does not inherently
need multi-tenant SaaS, microservices, a second queue service or another LLM.
Generating/stamping an output invoice is not necessary to verify the original.

## Verification boundaries

Component tests validate extraction/rules/API boundaries. The native suite uses
an isolated real Postgres 16 and real fixture PDFs/OCR, with external services
simulated explicitly. Hosted checks use actual Auth/Storage/Gemini/Sheets and are
reported separately. Fixtures, cached extraction and historical decisions must
never be described as a fresh live provider run. Only a measured idle start can
support a cold-start time claim.

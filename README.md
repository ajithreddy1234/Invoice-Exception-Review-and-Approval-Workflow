# Invoice Exception Review and Approval Workflow

An AI-assisted workflow for extracting invoice data, checking it against purchase orders, and helping a reviewer resolve exceptions with an auditable decision history.

> **Documentation status:** This README is a proposed implementation specification based on the project description. Repository code and evaluation logs were not supplied for verification. Components, endpoint contracts, commands, and directory names below are proposed conventions, not proof of implemented functionality. Performance figures are explicitly labelled targets.

## 1. Problem and scope

Invoice review requires more than extracting text. A reviewer must establish whether an invoice refers to a known purchase order, belongs to the correct supplier, has already been submitted, and requests an acceptable amount. An LLM can help interpret document text, but it cannot independently establish those business facts.

This project separates three responsibilities:

1. **Extraction:** Convert invoice text into structured candidate fields.
2. **Validation:** Apply deterministic rules and compare candidates with stored purchase-order data.
3. **Review:** Present evidence and exceptions so a human can approve, reject, or correct an invoice.

**MVP boundary:** Single-tenant demonstration using synthetic invoices, text-based PDFs, and purchase orders imported from CSV. All invoices require a human approval decision, including invoices with no detected exceptions. Approval updates application state; it does not initiate payment.

Scanned-document OCR, line-item matching, partial invoicing, tax-law validation, multi-currency conversion, and ERP payment execution are outside the MVP.

## 2. Example

A purchase order records supplier `SUP-001`, currency `INR`, and an agreed invoice total of `10000.00`. A submitted invoice references the same purchase order but requests `10350.00`.

- The extraction service identifies the purchase-order number and invoice total.
- The rule engine calculates an absolute discrepancy of `350 / 10000 = 3.5%`.
- Because 3.5% exceeds the configured 1% tolerance, it creates an `AMOUNT_MISMATCH` exception.
- The reviewer sees the invoice value, purchase-order value, discrepancy, and source document.
- The reviewer rejects the invoice or records a justified override. A correction creates a new revision and triggers validation again.

## 3. Technology choices

| Component | Proposed technology | Responsibility |
| --- | --- | --- |
| User interface | Streamlit | Upload documents, inspect exceptions, record review decisions |
| Backend | FastAPI | Own workflow state, validation orchestration, and API contracts |
| Extraction provider | LLM through OpenRouter | Extract candidate fields from document text |
| Data contracts | Pydantic | Validate structure, types, and allowed values |
| Persistence | PostgreSQL | Store purchase orders, invoice revisions, exceptions, and audit events |
| Data preparation | Pandas | Validate PO imports and prepare evaluation fixtures |
| Duplicate candidates | RapidFuzz | Identify similar invoice numbers within a restricted candidate set |
| Business rules | Python | Compare values, calculate discrepancies, and assign exceptions |

An additional PDF text-extraction dependency is needed for PDF input. Select and document that parser in the implementation. The MVP does not claim OCR support.

## 4. Architecture

```mermaid
flowchart TD
    UI["Streamlit reviewer UI"] --> API["FastAPI workflow service"]
    API --> EX["Document extraction service"]
    EX --> LLM["OpenRouter LLM API"]
    EX --> SCHEMA["Pydantic schema validation"]
    SCHEMA --> RULES["Python business-rule engine"]
    RULES --> DB[("PostgreSQL")]
    API --> DB
    API --> FILES["Private document storage"]
    RULES --> REVIEW["Review queue and evidence"]
    REVIEW --> UI
```

### Component responsibilities

**Streamlit:** Calls the backend instead of writing directly to the database. Displays extracted values alongside source evidence, exception explanations, prior corrections, and decision history.

**FastAPI:** Owns the invoice lifecycle. Checks uploads, enforces idempotency, coordinates extraction and validation, authorizes decisions, and commits state changes together with audit events.

**Extraction service:** Reads document text, applies input-size limits, submits an extraction request, parses the response, and records the model identifier, prompt version, duration, and failure category. Document text is untrusted data; it must not supply executable instructions or tools to the model.

**Rule engine:** Receives validated candidate fields and authoritative purchase-order records. Produces structured exceptions rather than asking an LLM whether an invoice should be approved.

**PostgreSQL:** Provides durable application state. Backend transactions and unique constraints protect exact duplicate checks and reviewer updates from concurrency races.

**Document storage:** Stores originals outside the public web root using generated object names. Database rows retain references and content hashes. Local private storage is sufficient for the demo; object storage is a later deployment option.

## 5. End-to-end processing

1. A user uploads an invoice and supplies or selects a known supplier identifier.
2. The API checks file type and size, calculates a content hash, and creates an invoice record with an idempotency key.
3. A parser extracts text. Empty or unreadable text produces a processing failure rather than an invented invoice.
4. The LLM returns a structured object containing eight requested fields. Missing values must be returned as `null`.
5. Pydantic checks the output contract. Required business fields remain nullable in the extraction contract so missing information can become a review exception.
6. The backend normalizes comparable values while preserving raw extracted values.
7. The rule engine checks completeness, duplicates, purchase-order existence, supplier identity, currency, and amount tolerance.
8. The backend stores the extraction revision and rule results, then marks the invoice ready for human review.
9. A reviewer approves, rejects, or submits a correction. Corrections trigger revalidation before approval is possible.
10. Every state-changing reviewer action is stored with the state update in one database transaction.

For the small local MVP, processing may run synchronously with a bounded request timeout. A production evolution should use a durable worker queue for processing beyond the web-request lifetime; in-process background tasks alone do not provide durable retries.

## 6. Eight-field extraction contract

| Field | Suggested type | Meaning |
| --- | --- | --- |
| `invoice_number` | nullable string | Supplier-issued invoice identifier |
| `supplier_name` | nullable string | Name printed on the invoice |
| `invoice_date` | nullable date | Issue date |
| `due_date` | nullable date | Payment due date, when present |
| `po_number` | nullable string | Referenced purchase order |
| `currency` | nullable string | Explicit invoice currency |
| `subtotal` | nullable decimal | Amount before tax and other additions |
| `total_amount` | nullable decimal | Final invoice amount |

The authenticated upload context supplies `supplier_id`; it is metadata, not a ninth extracted field. Supplier names are checked against stored aliases. A name similarity score alone must not establish supplier identity.

Example extraction result:

```json
{
  "invoice_number": "INV-2026-0042",
  "supplier_name": "Example Supplies Pvt Ltd",
  "invoice_date": "2026-10-01",
  "due_date": "2026-10-31",
  "po_number": "PO-1042",
  "currency": "INR",
  "subtotal": "10000.00",
  "total_amount": "10350.00"
}
```

Amounts are represented as decimal strings at the API boundary and stored with PostgreSQL `NUMERIC`; calculations use Python `Decimal`, not binary floating point. Dates use ISO format. Ambiguous currency or date values remain unresolved rather than being silently inferred.

**Schema validity does not establish extraction accuracy.** A correctly typed amount can still differ from the document. Keep source snippets or page references where supported and show the original document during review.

## 7. Validation rules

| Rule | Condition | Outcome |
| --- | --- | --- |
| `MISSING_REQUIRED_FIELD` | A business-required field is null or blank | Block ordinary approval until corrected or explicitly overridden |
| `INVALID_VALUE` | Negative amount, invalid currency, or inconsistent date | Require correction or justified review |
| `EXACT_DUPLICATE` | Same normalized invoice number and supplier, or repeated file hash | Flag existing record; prevent ordinary duplicate approval |
| `POSSIBLE_DUPLICATE` | Similar identifier among restricted supplier candidates | Show candidate records for review |
| `UNKNOWN_PO` | Referenced purchase order does not exist | Flag exception; do not calculate an amount match |
| `SUPPLIER_MISMATCH` | Invoice context/name conflicts with PO supplier | Flag exception |
| `CURRENCY_MISMATCH` | Invoice and PO currencies differ | Flag exception; do not compare raw amounts |
| `AMOUNT_MISMATCH` | Absolute total discrepancy exceeds 1% | Flag exception |

Suggested required fields are invoice number, supplier name, invoice date, PO number, currency, and total amount. Due date and subtotal may be absent without blocking the MVP workflow. Record this policy in configuration and tests.

### Amount comparison

```text
discrepancy_ratio = abs(invoice_total - po_expected_total) / po_expected_total
flag when discrepancy_ratio > Decimal("0.01")
```

Exactly 1% is within tolerance. Reject or flag zero/negative PO totals instead of dividing by zero. Compare amounts only when supplier, currency, and tax basis match. The MVP assumes one invoice per purchase order and compares against a stored `expected_invoice_total` on the same basis; it does not compare a tax-inclusive invoice total to an untaxed PO subtotal.

### Duplicate checks

Normalize case and whitespace but retain meaningful invoice-number characters and the original value. Search exact matches by supplier and normalized invoice number. Use a database uniqueness/reservation mechanism when accepting exact keys so concurrent submissions cannot both pass the check.

For fuzzy candidates, first restrict by supplier, currency, date window, and a reasonable amount range, then compare identifiers with RapidFuzz. A configurable starting threshold such as `90/100` is a tuning choice, not a measured optimum. Validate it on a development split. A fuzzy match creates a warning; it never automatically proves fraud or triggers rejection.

## 8. Workflow states and review behaviour

```mermaid
stateDiagram-v2
    [*] --> RECEIVED
    RECEIVED --> PROCESSING
    PROCESSING --> READY_FOR_REVIEW
    PROCESSING --> REVIEW_REQUIRED
    PROCESSING --> PROCESSING_FAILED
    PROCESSING_FAILED --> PROCESSING: Retry
    READY_FOR_REVIEW --> APPROVED: Human approval
    READY_FOR_REVIEW --> REJECTED: Human rejection
    REVIEW_REQUIRED --> APPROVED: Authorized override with reason
    REVIEW_REQUIRED --> REJECTED: Human rejection
    READY_FOR_REVIEW --> PROCESSING: Correct and revalidate
    REVIEW_REQUIRED --> PROCESSING: Correct and revalidate
```

`READY_FOR_REVIEW` means no configured exception was found; it does not mean approved. `REVIEW_REQUIRED` means one or more exceptions need attention. An unresolved exception requires an authorized override and reason, or a correction and revalidation.

Approval requests include the invoice version the reviewer inspected. If another reviewer has changed that version, return a conflict instead of overwriting the newer decision. Approvals and their audit events commit atomically. The demo performs no payment or external accounting mutation.

## 9. Proposed database design

| Table | Main fields | Purpose |
| --- | --- | --- |
| `suppliers` | `id`, `name`, `aliases` | Known supplier identities |
| `purchase_orders` | `id`, `po_number`, `supplier_id`, `currency`, `expected_invoice_total`, `status` | Authoritative comparison data |
| `invoices` | `id`, `supplier_id`, `document_ref`, `file_hash`, `status`, `version`, timestamps | Invoice lifecycle |
| `invoice_revisions` | `id`, `invoice_id`, `revision_number`, `fields_json`, `source`, `model_id`, `prompt_version` | Immutable extraction and correction versions |
| `validation_runs` | `id`, `invoice_id`, `revision_id`, `rules_version`, `status`, timestamps | One execution of the rule set |
| `invoice_exceptions` | `id`, `validation_run_id`, `rule_code`, `severity`, `evidence_json` | Rule outcomes tied to a particular revision |
| `audit_events` | `id`, `invoice_id`, `actor_id`, `action`, `before_json`, `after_json`, `reason`, timestamp | Review and lifecycle history |

Use foreign keys, unique PO numbers, unique revision numbers per invoice, and indexes on supplier/invoice lookup keys and queue status. Audit events should be append-only for the normal application role. An audit table alone is not tamper-proof against database administrators.

## 10. Proposed API contract

| Method | Endpoint | Behaviour |
| --- | --- | --- |
| `POST` | `/invoices` | Accept upload, supplier context, and idempotency key |
| `GET` | `/invoices` | Return a paginated queue with status filters |
| `GET` | `/invoices/{id}` | Return current fields, revision, exceptions, and status |
| `GET` | `/invoices/{id}/document` | Return an authorized source-document view |
| `PATCH` | `/invoices/{id}/fields` | Create a correction revision and revalidate |
| `POST` | `/invoices/{id}/decision` | Approve/reject with expected version and reason |
| `POST` | `/invoices/{id}/retry` | Retry a failed processing attempt |
| `GET` | `/invoices/{id}/audit` | Return authorized audit history |
| `POST` | `/purchase-orders/import` | Validate and import PO CSV data |
| `GET` | `/health` | Report service health without exposing secrets |

Example decision request:

```json
{
  "decision": "approve",
  "expected_version": 3,
  "override_exception_ids": [],
  "reason": "Verified invoice and purchase-order evidence."
}
```

An `actor_id` must come from trusted authentication context, not a caller-supplied JSON field. A local demonstration may use an explicitly configured test reviewer, but must not describe that as production authentication. Suggested error semantics: `404` for absent records, `409` for stale versions or state conflicts, `422` for malformed input, and a recoverable processing failure for provider errors.

## 11. Illustrative repository layout

The following files are proposed; they are not included with this README.

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI application and router registration |
| `app/api/` | Invoice, decision, and import endpoints |
| `app/schemas/` | Extraction, correction, and decision contracts |
| `app/services/extraction.py` | Parser and OpenRouter integration |
| `app/services/validation.py` | Deterministic validation rules |
| `app/services/duplicates.py` | Exact lookup and fuzzy candidates |
| `app/services/review.py` | State transitions and audit transactions |
| `app/models/` | Database models |
| `app/core/` | Configuration, authorization, logging |
| `ui/streamlit_app.py` | Review interface |
| `migrations/` | Versioned database migrations |
| `scripts/` | PO import and synthetic-data generation |
| `evaluation/` | Labels, manifests, evaluator, and measured reports |
| `tests/` | Rule, integration, and workflow tests |

## 12. Configuration and local setup plan

These are illustrative commands for the proposed structure. They become runnable only after the corresponding application files and dependency manifests exist. This README does not supply a working repository.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Example environment configuration:

```dotenv
DATABASE_URL=postgresql://invoice_app:local_password@localhost:5432/invoice_review
OPENROUTER_API_KEY=replace_with_your_key
OPENROUTER_MODEL=replace_with_a_verified_model_identifier
AMOUNT_TOLERANCE=0.01
FUZZY_DUPLICATE_THRESHOLD=90
UPLOAD_MAX_MB=10
PRIVATE_UPLOAD_DIR=./private_uploads
API_BASE_URL=http://localhost:8000
```

Do not commit a real `.env` file. Verify the selected provider model's current structured-output capabilities before implementation. The model identifier and provider client settings are deliberately unspecified here.

After creating the database, applying the implemented migrations, and importing sample POs:

```bash
uvicorn app.main:app --reload
streamlit run ui/streamlit_app.py
```

Run the two application commands in separate terminals. The Streamlit application calls FastAPI through `API_BASE_URL`. Provide exact migration and seed commands in the repository once their tooling exists.

## 13. Evaluation design

### Dataset

Plan a benchmark of **200 synthetic invoice submissions** containing 30 duplicate cases (15%), 30 amount-mismatch cases (15%), and 20 missing-field cases (10%). Decide and record whether categories overlap. Only a disjoint design implies 120 remaining submissions without these three injected error types.

Duplicate cases need earlier reference invoices in the seeded database. Missing-field cases should identify whether the missing field is required. Record document templates, expected fields, matching PO, exception labels, and reference-invoice relationships in a manifest. Use separate fixtures for unknown POs, supplier conflicts, and currency mismatches; do not imply those were evaluated by this 200-case distribution unless added and counted.

Hold out document templates and supplier layouts when possible. Tune prompts and fuzzy thresholds on development data, then freeze them for the final benchmark. Keep a random seed and versioned manifest. Synthetic results demonstrate performance on the test generator, not on arbitrary real supplier documents.

### Metrics

| Metric | Definition |
| --- | --- |
| Field-level extraction accuracy | Correct normalized field values divided by all labelled field slots, counting correct nulls |
| Present-field accuracy | Correct non-missing field values divided by labelled present fields |
| Exception precision | Correctly flagged invoices / all flagged invoices |
| Exception recall | Correctly flagged invoices / all invoices requiring an exception |
| Per-rule precision/recall | Compute the same measures independently for each exception label |
| Processing latency | Wall-clock time from accepted upload through persisted validation outcome, including retries |
| Failure rate | Failed processing attempts / accepted submissions |

Use predefined normalization rules for dates, case, whitespace, and decimal values. For 200 invoices and eight fields there are 1,600 labelled field slots if all documents have labels for all eight fields, including nulls. Do not treat the model's own answer as ground truth.

Run extraction and downstream exception detection end to end. Also test the rule engine separately with correct structured inputs to distinguish extraction failures from rule failures. Report latency mean and p95, sample size, model identifier, retries, concurrency, and test environment. Failed requests must appear in failure statistics instead of silently disappearing from evaluation.

### Proposed targets, not measured results

| Metric | Proposed target | Measured result |
| --- | --- | --- |
| Field-level extraction accuracy | At least 95% | Not measured |
| Invoice-level exception precision | At least 95% | Not measured |
| Invoice-level exception recall | At least 90% | Not measured |
| Mean processing time | At most 5 seconds | Not measured |

These are project goals, not generic benchmarks or achieved scores. Actual feasibility depends on input length, parser, model, provider latency, and retry behaviour. Publish only measured results as accomplishments.

## 14. Test plan

- Amount checks just below, at, and above 1%; zero PO total; currency mismatch; differing tax basis.
- Null required fields, absent optional fields, malformed dates, negative totals, invalid model JSON, and unreadable PDFs.
- Exact duplicates, fuzzy near-matches, legitimate similar invoice numbers, and concurrent duplicate submissions.
- Correction creates a new revision and invalidates prior validation results.
- Two reviewers attempt decisions against the same version; one receives a conflict.
- State changes and audit events succeed or roll back together.
- Provider timeout, throttling, bounded retries, upload-size limit, and missing API credentials.
- End-to-end upload, extraction, exception, correction, revalidation, approval, and audit-history retrieval.

Provider calls should be mocked for ordinary automated tests. Run a separate explicitly enabled live evaluation for model performance; mocked outputs cannot establish extraction accuracy.

## 15. Security and operational limits

- Keep provider keys on the backend. The UI receives no provider secrets.
- Use parameterized database access and least-privilege credentials.
- Restrict review, override, document viewing, and PO import through authorization checks before external deployment.
- Limit document size, parser resources, extraction tokens, provider timeouts, and retry counts.
- Treat invoice content as untrusted input; extraction has no payment or database-write tools.
- Avoid raw invoice text, credentials, and unnecessary personal information in application logs.
- Document retention/deletion policy and any external processing of invoice contents before using real business documents.
- Record correlation IDs, validation rules version, model identifier, and prompt version to support diagnosis.

The initial single-tenant demo does not provide tenant isolation, immutable compliance storage, production SSO, or ERP-grade reconciliation.

## 16. Demonstration script

1. Import a small set of known suppliers and purchase orders.
2. Upload a valid invoice and explain why it is ready for human review.
3. Upload an amount-mismatch invoice and inspect the discrepancy calculation.
4. Upload a duplicate and inspect the reference record.
5. Correct an extracted field, rerun validation, and inspect the new revision.
6. Approve or reject with a reason and show the resulting audit event.
7. Show the measured evaluation report if available, including failures and limitations.

## 17. Future improvements

Add OCR with page-level evidence, line-item and partial-invoice reconciliation, durable background workers, reviewer authentication, and evaluation on permitted real-world documents. Each addition requires its own acceptance criteria and evaluation; it should not appear as completed functionality until implemented.

## 18. Short explanation for interviews

The application uses an LLM to turn invoice text into structured candidate data. Pydantic validates that data's shape, and Python rules compare it with authoritative purchase-order records and existing invoices. Exceptions appear in a Streamlit queue, where a reviewer can correct or decide the case. PostgreSQL stores revisions, rule outcomes, and an audit trail. The important design choice is separating language interpretation from business validation and human authorization.

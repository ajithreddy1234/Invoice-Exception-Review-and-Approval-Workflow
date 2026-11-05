# ASA Invoice Review

A working same-origin FastAPI + React invoice review app. Postgres is the acceptance ledger; Google Sheets supplies versioned reference data and receives accepted-invoice reports. Gemini proposes structured fields from extracted page text; evidence and deterministic business checks decide eligibility.

## Implemented

The workspace opens on Upload, with Dashboard and Invoices navigation, a password eye, private page previews and evidenced admin correction/PO selection with immutable revisions. Correction never automatically accepts a document. No new migration is required beyond the existing schema and Step 3 migration.

- Supabase password login, HttpOnly/SameSite=Strict cookies, exact-Origin checks, current database roles, user ownership and admin access. Reused HTTP/database connections avoid repeated remote handshakes; every transaction still sets the restricted role and verifies grants. Read-only page queries batch protocol setup and data together; write transactions keep the existing pre-execution grant guard.
- Private PDF/JPEG/PNG intake (5 MiB, three pages), idempotent upload retries, durable processing leases, embedded text or isolated Tesseract OCR.
- Field-level page/quote evidence and nine checks: required fields, vendor, PO, source evidence, duplicate, currency, arithmetic, line allocation and PO balance.
- Atomic acceptance with reference/PO locks, unique invoice identity, cumulative quantity/balance rechecks and a durable publication task.
- Idempotent Sheets publication to a permanently assigned report row, confirmed read-back and retry states separate from the acceptance decision.
- Separate Dashboard, Upload and Invoices pages. Vendor accepted-value bars, currency/company filters, upload activity, review/duplicate/publication counts and admin-only PO balances use all ownership-visible records. The register shows the latest 200. Browser evidence, original download, live stages, decision/history and admin diagnostics/import/retry/reject. Admin acceptance requires eligible validation and cannot bypass failed checks.
- Seven-day source-file expiry. Audit, extracted evidence, file hash and financial ledger records remain. Expired originals cannot be processed again from storage.

## Run an existing configured project

```sh
uv sync
cd web
npm ci
npm run build
cd ..
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. Local `.env` must use this exact `APP_ORIGIN` and `COOKIE_SECURE=false`. Sign in using an app Auth user's email/password, not the database password. Login is required again when the access cookie expires; refresh-token rotation is outside this scope.

For new installations only, copy `.env.example` without overwriting an existing `.env`, fill private values locally and run the setup CLI. Apply `migrations/schema.sql`, then `migrations/step3.sql` as migration owner. Existing v1.1 databases require the documented upgrade to v1.2 before Step 3. The current development Supabase project already has both required migrations; do not recreate it. App transactions switch to the restricted `service_role`; the readiness gate refuses unsafe direct status-update privileges.

```sh
.venv/bin/python -m app.cli doctor --live
.venv/bin/python -m app.cli import-sheet
```

Use a private `invoice-originals` Storage bucket, 5,242,880-byte bucket limit and PDF/JPEG/PNG MIME allowlist. Store the Google service-account file in the project-owned `credentials/` folder. Neither secrets nor credentials are included in the source archive.

## Verify

```sh
.venv/bin/python -m pytest -q
npm install
npm run test:native-api
cd web
npm test
npm run build
```

The native runner creates and destroys an isolated local Postgres 16 cluster; it does not use the cloud database. The ordinary suite skips native tests, which are run by that separate runner. Native pipeline tests use simulated external providers and real PDF/OCR/database code. Separate live-cloud results accompany the delivery.

## Operations and limits

- Source/reference uncertainty goes to review. An unreadable total stays unknown; it cannot be inferred from subtotal, tax or PO balance. Correct the underlying source or master data, then retry/re-upload. Admin can correct supported fields and select only among exact ambiguous PO candidates, then revalidate. A separate explicit approval is required. Requesting a clearer original is an in-app record; no email is sent.
- Jobs and export tasks survive process restart. Expired leases can take five minutes to recover. Workers run inside the active web process; a sleeping host pauses progress until it resumes. Do not run an in-memory queue as the source of truth.
- Invalid Sheet imports leave the last valid reference intact. Stale reference data pauses eligibility. Admin can import current data from the dashboard.
- Do not insert/delete/sort report rows or overwrite assigned `AcceptedInvoices` cells. A conflicting row is held for reconciliation, never blindly overwritten. Fix the report row then retry publication. Report edits never change Postgres balances.
- Uploaded data is untrusted input; extraction does not authenticate an invoice. English OCR, supported monetary/date formats and explicit vendor/currency rules are required. No email intake, output-invoice generation, payment execution or ERP integration.
- Test acceptances in the development project are genuine ledger rows. Re-uploading their invoices correctly returns duplicate; no destructive reset is provided.

## Deployment and submission

The multi-stage Dockerfile builds React, installs Tesseract and serves UI/API/workers in one process. `render.yaml` lists environment variables, including the server-only Supabase secret. Configure the Google credential as a Render secret file at `/etc/secrets/Sheet_Service.json`; set the public HTTPS `APP_ORIGIN` and `COOKIE_SECURE=true`. Secrets remain outside the image and browser bundle.

The app is deployed at [asa-invoice-review.onrender.com](https://asa-invoice-review.onrender.com) on Render Free in Singapore. Dedicated recruiter admin/user credentials are supplied privately. The repository contains the real application and reproducible tests; credentials are excluded.

The Linux AMD64 image built successfully. A local container limited to 512 MiB and 1 CPU passed app/OCR/restart checks with a measured cgroup peak of about 247 MiB. This is not a measurement of Render's smaller Free CPU allocation or its unavailable free-plan memory metrics. Hosted password logins, cookie flags, role boundaries and the deployment smoke passed. A genuine 15-minute idle wake-up is a separate check, not claimed by the local restart rehearsal. See [deployment instructions](docs/DEPLOYMENT.md) and the [five-minute demo](docs/DEMO.md).

The configured model was moved to free-tier Gemini 3.1 Flash-Lite after the 3.5 model returned transient HTTP 503 high-demand errors. Source evidence and all deterministic/SQL gates remain mandatory. Prompt revision `invoice-text-v2` explicitly distinguishes separately added tax, printed zero tax and explicitly inclusive wording; extraction revisions record the model and prompt version.

The safe deployment probe makes no ledger writes:

```sh
.venv/bin/python scripts/check_deployment.py http://127.0.0.1:8000 --output data/deployment-smoke.json
```

Create a source archive only after the credential audit passes. This excludes local credentials, runtime data, caches, dependencies and built assets, includes fixture-generation tools, and creates a SHA-256 manifest:

```sh
.venv/bin/python scripts/release.py
.venv/bin/python scripts/release.py --output ../outputs/invoice-review-release.zip
```

The source repository contains synthetic fixtures only. Demo login passwords and provider credentials are supplied privately, never in this README. Free-tier hosting/model allowances can expire or throttle; this is a demonstration, not a production availability commitment.

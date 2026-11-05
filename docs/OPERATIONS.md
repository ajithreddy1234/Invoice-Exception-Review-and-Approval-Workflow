# Operating the invoice workspace

The deployed app provides upload, invoice history, vendor/commitment dashboards
and administrator review. It has one procurement workspace. Ordinary users can
see only their own records; administrators have workspace-wide access.

## Service checks

`/health/live` reports the application version and uptime without contacting
external providers. `/health/ready` returns 503 during initialization or when the
reference/database checks fail. Inspect **Procurement & service health** on the
administrator dashboard for startup, worker, configuration and reference status.
A configured key is not proof that a provider currently has quota or availability.

DB permission checks complete before processing workers start. Startup failures
retry; an invalid/unavailable Sheet import preserves the last valid reference.
Stale references prevent acceptance. Import network calls do not hold PO locks.

## Invoice decisions and recovery

Postgres is authoritative for acceptances and remaining commitments. Do not edit
an acceptance to undo a UI outcome. SQL transactions recheck current references,
duplicate identity and cumulative quantity/value while locking the PO.

An accepted decision may have pending spreadsheet publication. Retry publication
from the admin dashboard; do not upload or accept the invoice again to repair its
report. Assigned report rows must not be manually sorted, inserted or deleted.
Investigate a reconciliation warning rather than overwriting another record.

Uncertain source fields stay unknown. Request a clearer original or make an
evidenced admin correction with a reason. Corrections create a new revision and
require revalidation plus explicit acceptance; they cannot bypass failed checks.

Durable jobs survive a host restart. Recovery of an expired lease can take five
minutes. Check existing processing state before retrying. The client preserves
an upload request key for safe retries and never automatically replays writes.

## Stored data and extraction reuse

Originals are private and expire after seven days. Extracted evidence, hashes,
validation and audit/ledger records remain. Reuse of original provider extraction
is scoped to the same uploader, identical bytes/MIME/size and matching versions
for seven days. All current checks still run; decisions are never cached.

Choose an approved retention/backup procedure before using live company records.
The current seven-day source policy and synthetic dataset are evaluation choices;
removing sample navigation does not change either policy or the audit history.
Fixtures/operator tools are source-only and are excluded from the server image.

## Credentials and deployment limits

Server-only Supabase/database/Gemini/Google credentials belong in the hosting
secret environment/file configuration. Never use `VITE_` variables for secrets.
Keep evaluator passwords separate from source archives. Rotate shared or compromised database passwords, then update local and Render
`DATABASE_URL`. Credential changes are performed by the account owner.

The code has authenticated role checks, same-origin mutations, Secure/HttpOnly/
SameSite cookies for HTTPS, private originals, immutable financial history,
bounded uploads/OCR/provider attempts and sanitized diagnostics. HTTPS responses
also send HSTS, frame protections and restrictive browser permissions.

The current Free Render host sleeps after inactivity. This deployment is suitable
for evaluation; it is not an always-on production service. Render explicitly
advises against production use of Free instances:
https://render.com/docs/free

Before accepting live business traffic, arrange an availability plan, database
backup/restore testing and dependency/quota monitoring appropriate to the
business, verify credential custody and replace evaluation identities/reference
data through a separate controlled workspace setup. No paid resource, account
permission or financial history is changed by this UI release.

# Deploy the invoice app on Render Free

Use this repository as the service root. The Dockerfile builds React and installs
English Tesseract. FastAPI serves the UI/API and runs the durable workers.
Postgres and private originals stay in the existing Supabase project.

## Service configuration

1. Render → New → Web Service → select this invoice repository and `main`.
2. Language **Docker**, Dockerfile `./Dockerfile`, root directory blank.
3. Select **Free** explicitly. Use one instance; do not add a paid disk/database.
4. Health check `/health/live`. Leave Docker command blank (use the image CMD).
5. Set the following environment variables. Copy private values from the local
   project `.env` into Render's Environment screen; never commit them.

| Variable | Value |
| --- | --- |
| `APP_ORIGIN` | Exact assigned `https://…onrender.com` origin, no path/hash |
| `COOKIE_SECURE` | `true` |
| `DATABASE_URL` | Existing Supabase transaction-pooler URI, SSL required |
| `SUPABASE_URL` | Existing project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Existing project publishable key |
| `SUPABASE_SECRET_KEY` | Existing server secret key |
| `GOOGLE_SPREADSHEET_ID` | Existing invoice reference/report Sheet |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/etc/secrets/Sheet_Service.json` |
| `GEMINI_API_KEY` | Existing AI Studio project key |
| `GEMINI_MODEL` | Exact currently working free-tier model from local `.env` |
| `AUTO_IMPORT_ON_STARTUP` | `true` |
| `REFERENCE_TTL_HOURS` | `24` |
| `WORKER_ENABLED` | `true` |
| `STORAGE_BUCKET` | `invoice-originals` |

6. Add a **Secret File** named `Sheet_Service.json`, with the contents of the
   project-owned `credentials/Sheet_Service.json`. Do not paste it into source
   code, a GitHub issue or a normal repository file. Render mounts it at the
   absolute path above. This is required in addition to setting its path variable.
7. Deploy, wait for a successful build/live instance, and correct `APP_ORIGIN` if
   Render assigned a different URL. Save and deploy environment changes.
8. Keep the Supabase bucket private. For an existing deployment, preserve its ledger and profiles. For a new project,
   apply `migrations/schema.sql`, then `migrations/step3.sql`, and provision the
   dedicated Auth users/profiles before testing.

`render.yaml` is an alternative Blueprint configuration. Its `sync: false`
entries prompt for secrets on initial creation; the Google secret file still
needs configuring. Use one configuration method consistently for later changes.

## Verify the actual hosted instance

From the configured local project:

```sh
.venv/bin/python scripts/check_deployment.py https://YOUR-ACTUAL-URL.onrender.com --output data/hosted-smoke.json
```

The script checks built assets, readiness, security headers, unauthenticated API
denial and cross-origin denial. It does not log in, upload, spend PO balance,
send invoice text or make a model request. A pass is a deployment smoke test,
not proof that a fresh extraction succeeds.

Then verify in the hosted browser: actual admin login; source preview; dashboard;
normal-user isolation/admin denial; one fresh extraction; source uncertainty;
acceptance/report publication using synthetic documents with available budget.
Confirm the cookie is HttpOnly, Secure and SameSite=Strict. Never put server
secrets in `VITE_…` variables or client code.

Restart the service and verify readiness/retained records again. Expired durable
job leases can take five minutes to recover. For a genuine free-host cold start,
close app tabs (polling is traffic), allow at least 15 minutes without requests,
then probe once and record the first request duration. Do not label a warm local
restart as a hosted cold-start measurement.

## Cost and operational limits

The plan uses existing free-tier accounts, one Free Render service and local
Tesseract. This is a demo within provider allowances, not a guarantee of unlimited
free usage or production availability. Do not enable paid model billing/upgrades
as a workaround. Check account quotas and spend controls before the demo.

Render Free sleeps after 15 minutes without traffic and can take about one minute
to wake. Its filesystem is ephemeral; our ledger and originals use Supabase.
Workers pause while the host sleeps. Open the app before the interview; do not
promise an always-on service. No keep-alive automation is installed.

The local Linux memory report is a constrained-container observation. It does not
replace Render metrics, a fresh hosted OCR run or hosted concurrency measurement.
The app bounds OCR and preview concurrency/timeouts; an unavailable extraction
must remain held rather than being approved from guessed data.

Official references: [Docker builds](https://render.com/docs/docker),
[environment variables and secret files](https://render.com/docs/configure-environment-variables),
[Free instance limits](https://render.com/docs/free).

## Interpreting the allocation/loading page

Render's allocation page precedes application code while a sleeping Free instance
starts. It cannot be restyled or disabled by React/FastAPI. Keeping Free hosting
means retaining that occasional delay. The app now serves its UI before its
bounded DB/Sheets initialization; processing workers wait for DB permission
verification. Startup retry never grants broader permissions.

Use `/health/live` for dependency-free version/uptime. `/health/ready` returns
`starting` and `Retry-After: 2` during initialization, and reports reference
freshness after it finishes. Inspect **Procurement & service health** as admin for
worker/startup state. A configured key alone is not a successful provider probe.

Existing immutable extraction evidence provides a seven-day cache for the same
uploader/file/version; Render's ephemeral filesystem is not used for it. A source
hash mismatch or current reference/financial failure still prevents acceptance.
No migration or new environment variable is required for this release.

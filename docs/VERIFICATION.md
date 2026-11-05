# Verification and practical limits

Current v0.9.0 regression checks on 6 November 2026 (India time):

- 260 component tests plus 37 subtests passed; 54 isolated-native tests are
  skipped by this command and are run separately.
- All 54 native Postgres 16 tests passed with real transactions, separate
  connections and real fixture PDF/OCR reading. External provider calls are
  simulated, not evidence of live Gemini availability.
- 19 frontend tests and the production build passed. A temporary browser harness
  using the actual register hook verified next/previous pages, stale in-flight
  search suppression, error recovery and page reset across identities. The
  harness used a simulated API and is removed from the source release.
- New native cases prove incorrect PO-as-invoice identity cannot consume a
  partial PO a second time, original corruption blocks download without changing
  acceptance, queue limits remain atomic, expired work avoids provider calls,
  and full-history search/pagination stays ownership-scoped past 200 records.

Current hosted v0.9.0 verification also passed:

- Deployed version and every JS/CSS/logo asset byte-match the local build.
- Actual admin/user logins, restricted DB permission gate, running workers,
  configured queue bounds, malformed-cursor rejection and owner/admin isolation.
- Full-history paging traversed five pages (21 records before verification upload).
- Downloaded original matched its recorded SHA-256. A changed-byte synthetic
  re-export invoked fresh Gemini extraction, passed the new invoice-ID evidence
  guard and was blocked as a duplicate. No new acceptance was created; the seven
  accepted records and commitments remained unchanged.
- One polling connection disconnected; verification resumed the existing run,
  without replaying the upload. This is not a claim of uninterrupted availability
  or a new cold-start measurement. Provider dependencies remain external.
- Unauthenticated deployment/security checks passed separately. These hosted
  results do not constitute an authenticated browser walkthrough of every screen.

Earlier v0.6–v0.8 infrastructure and live workflow observations follow. They are
not new measurements of v0.9.0:


- Python components: 242 tests plus 37 subtests passed. Native tests are skipped
  in this command and executed separately.
- Isolated native Postgres: 46 tests passed after a clean dependency install.
  Real separate DB connections exercise financial locks, uniqueness, rollback,
  correction/review permissions and publication recovery; providers are simulated.
- Frontend: 19 tests and the current production build passed. Request-boundary
  tests cover host HTML, bounded body reads and no automatic mutation replay.
- A Linux AMD64 Docker image built with pinned Python/JS dependencies. A local
  512 MiB / 1 CPU container passed app/readiness/access checks, four PDF/JPEG/PNG
  OCR fixtures, and restart readiness. Cgroup peak: 259,416,064 bytes (247.4 MiB).
  Initial/restart readiness: about 8.2 / 14.8 seconds in that local rehearsal.
- Hosted HTTPS readiness, built assets, unauthenticated denial and cross-origin
  denial passed on Render Free. Actual password-grant admin/user sessions passed,
  with HttpOnly/Secure/SameSite=Strict cookies and owner/admin access boundaries.
- Google returned HTTP 503 high-demand errors for the previously used 3.5 model.
  A real 3.1 Flash-Lite structured extraction succeeded without evidence issues;
  the operator changed the configured model to that free-tier eligible model.

The live hosted acceptance/report, duplicate and uncertain-source results belong
to the separately supplied Step 5 live report. Do not replace those observations
with the expected outcomes in the synthetic fixture manifest.

One Starlette/httpx test-client deprecation warning remains. Render Free does not
expose memory/CPU charts for this service without upgrading; no upgrade was made.
The local memory observation is not a hosted concurrency or guaranteed capacity
claim. A genuinely idle Free-host wake-up and an interview recording are not
established by deployment or the local restart check.

Free hosts sleep, model availability/quotas can change, English OCR can be
uncertain, and references can expire. Held/failed processing does not become an
acceptance. There is no forced financial approval, payment, guessed total,
destructive demo reset, retained output-invoice PDF or fixture-output shortcut.

Fresh-pack tests also cover independent identities, exact within-pack duplicates, cross-pack ambiguous-PO isolation, offline sample preparation and removal of hosted sample routes, immutable preparation conflicts, validation preservation and at-most-two provider attempts.

Startup/reuse hardening verifies that delayed DB/Sheets initialization cannot
block the HTTP listener, workers wait for the permission check, a DB outage can
recover without redeployment and shutdown interrupts startup backoff. Real local
Postgres tests cover owner/model/prompt/reader/pipeline cache isolation, the
seven-day expiry, hash verification before reuse and current-reference checks.
A stale-reference read is explicitly simulated in its cache-gate test; native SQL
financial/uniqueness/locking checks continue to run in the separate suite.

Pool logging is sanitized before propagation: driver connection URI arguments and exception tracebacks are omitted. A regression test exercises a credential-bearing synthetic driver error.

The workspace release removes the guide route, sample prompts and evaluation
branding. Synthetic PDFs move to `tests/fixtures/demo_packs/`; only offline tools
import their catalog. API tests verify 404 sample endpoints for unauthenticated,
user and admin access. Security-header tests cover HTTPS/local HTTP, successful
pages, unauthorized APIs, removed routes and cross-origin mutation denials.
Database errors no longer return internal SQL state to clients.

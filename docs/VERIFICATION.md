# Verification and practical limits

Local v0.12 review candidate, 7 November 2026 (India time): see
[case-study update and evidence](CASE-STUDY-UPDATE.md). It adds business explanations,
recorded timings, read-only revision inspection, scoped database metrics and
varied synthetic inputs. All local checks passed; eight fresh Gemini extractions
produced four eligible/four review outcomes without cloud ledger writes. The
hosted results below remain v0.11 evidence, not hosted verification of v0.12.

Hosted v0.11.0, 6 November 2026 (India time), application commit
`b5edb8b839bf7d1867203e19e0a1ab14f966d1c9`:

- 26 authenticated workflow checks and 12 unauthenticated deployment checks passed.
  Public version/readiness and every built JS/CSS/logo asset match the tested
  application. Real administrator/user logins, restricted database gate, admin
  denial for a normal user and private source access were verified.
- One authorized synthetic invoice, INV-1001 / PO-FULL / INR 10,000, used fresh
  Gemini extraction, passed all nine checks and was accepted automatically.
  Extraction-through-publication observation took 25.255 seconds including polling;
  this is one run, not a latency guarantee. It was not a cached/provider-simulated run.
- Download bytes matched the uploaded SHA-256; private PNG preview succeeded.
  Logged-out access was denied. The accepted decision was published, and an
  independent service-account read of AcceptedInvoices!A4:K4 confirmed the exact
  acceptance/submission identity, PO, invoice number and amount.
- All three pre-existing invoice states/acceptance/report links were preserved.
  Exactly one invoice and INR 10,000 commitment were added. Pack B's five imported
  POs remain unused; its seven fixture hashes were checked separately. This is a
  dated observation; future uploads can consume those identities/budgets.
- Render initially reported the deployment live while the public endpoint still
  served v0.9. Restarting did not resolve it. A clean build with cache cleared
  served v0.11 and matching assets, after which verification proceeded. No test
  upload was made against the mismatched version. The cache/routing cause was
  not established, and this is not a measured idle cold-start result.
- The prior v0.9 commit remains available on the rollback/v0.9-live-20261106 branch
  and as its retained Render deployment. No database migration, ledger reset,
  new reference rows, paid service or credential rotation was performed.
  Rotation of the previously disclosed database credential remains owner work.

The local-candidate statements below describe the earlier verification boundary,
before this hosted release. They do not override the results above.

Local candidate v0.11.0, 6 November 2026 (India time):

- 306 component tests and 45 subtests passed. The 65 isolated native tests are
  skipped by that command and all passed in their separate Postgres 16 run.
  Those tests exercise actual PDF/OCR and transactions, with external providers
  explicitly simulated. Existing duplicate, balance and admin-review guarantees
  continue to pass; no SQL acceptance/schema change is introduced.
- 26 frontend tests and the production build passed. A temporary local browser
  harness using the actual check-list component confirmed nine checks, four
  neutral waiting states, PO-specific guidance and no horizontal overflow at the
  observed viewport. Its synthetic display data was labelled; this was not a
  hosted login or financial operation. The harness is removed and not released.
- Runtime Python audit initially reported advisories against Pillow 12.3.0.
  Upgrading to 13.0.0 and regenerating the lock/export cleared the audit. On this
  date, pip-audit found no known vulnerabilities in the runtime export and npm
  audit found zero in the web dependency tree (including development packages).
  This covers known package advisories, not all application/OS risks. Upstream
  patch evidence: https://github.com/python-pillow/Pillow/security/advisories/GHSA-4558-3h8r-v8xp
  and https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html .
- Real GIF/TIFF/BMP inputs declared as JPEG/PNG are rejected before OCR or preview;
  preview rejects the wrong declared supported type too. Valid supported-image
  and scanned-PDF tests pass with the patched library.
- The Linux AMD64 Docker image builds. An unconfigured, network-disabled container
  with no credentials passes UI/liveness 200, readiness 503 and unauthenticated
  admin denial 401. Four serial real OCR inputs (clean/blurred scan PDFs, JPEG and
  PNG) complete under a 512 MiB / 1 CPU limit; cgroup peak is 252,600,320 bytes.
  This is a local serial packaging/OCR check, not hosted concurrent capacity or
  an idle Render cold-start measurement. An initial operator check used a
  nonexistent diagnostics URL; it was corrected to the actual admin health route.
- New regression cases cover missing/closed/wrong-vendor PO explanations,
  dependency waiting without approval, independent currency errors, readiness
  with missing or stopped processing dependencies, and bounded JSON-wrapped
  Storage missing-object responses. Other provider errors stay errors.
- Only unauthenticated hosted liveness was checked this turn: it still reports
  v0.9.0. No cloud invoice, acceptance, reference import or report row was changed.
  No push/deployment was performed. Hosted testing of v0.11 remains a release gate.

The v0.10 and deployed observations below are historical, not additional v0.11
measurements.

Local candidate v0.10.0, 6 November 2026 (India time):

- 283 components and 37 subtests passed. The 65 isolated native tests are skipped
  by this component command and executed separately.
- All 65 native Postgres 16 tests passed, including the complete new-pack story,
  auditable line mapping, grounded OCR confirmation, explicit admin-only
  acceptance, stale-reference/invalid-choice rejection, balance protection and
  reprocessing without inherited manual permissions. External services are
  simulated; fixture PDFs and scan OCR are real.
- 21 frontend tests and the production build passed. The actual review components
  were checked in a temporary simulated-API browser harness for request payload,
  unchanged source wording, role restrictions, edit/cancel/reopen resets and
  recorded resolution. This harness is excluded and removed.
- A Linux AMD64 Docker image builds. An unconfigured container started with
  networking disabled and a 512 MiB/1 CPU limit: liveness 200, unauthenticated
  admin access 401, missing-configuration readiness 503, and new review schema
  loaded. This checks packaging/startup, not configured provider load or OCR memory.
- No push, deployment, hosted reference import or cloud ledger change is part of
  this candidate. Live provider/Sheet and idle-start checks remain post-approval
  release gates. No numeric case-study score or uptime guarantee is claimed.

The following are historical deployed v0.9 and earlier results, not hosted tests
of this candidate.

Previously deployed v0.9.0 regression checks on 6 November 2026 (India time):

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

Previously deployed v0.9.0 verification also passed:

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

# Verification and practical limits

Release checks on 5 November 2026 (India time):

- Python components: 214 tests plus 37 subtests passed. Native tests are skipped
  in this command and executed separately.
- Isolated native Postgres: 36 tests passed after a clean dependency install.
  Real separate DB connections exercise financial locks, uniqueness, rollback,
  correction/review permissions and publication recovery; providers are simulated.
- The existing frontend's 12 tests and production build passed in Step 4. The
  release Docker build independently rebuilt that same frontend on Linux.
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

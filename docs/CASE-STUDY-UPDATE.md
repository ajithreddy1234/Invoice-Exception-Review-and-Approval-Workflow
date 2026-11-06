# v0.12 case-study update — local review candidate

The update makes existing invoice decisions easier to explain and verify. It
does not change financial rules, the acceptance transaction or the database
schema. The hosted release last verified is v0.11; v0.12 is not deployed by this
change. No cloud invoice, reference, commitment or spreadsheet row was changed.

## What the evaluator can now inspect

- Decision, actual PO commitment and spreadsheet publication as three separate
  facts. A primary reason, next action and financial effect precede the checks.
- Saved stage timestamps and elapsed intervals for the selected run. Missing
  events stay missing; active stages have no invented duration.
- Exact validation policy from its immutable snapshot, with actual tolerance,
  currency, billing mode and authorized amount. Stale/inactive references clearly
  pause new acceptance, including admin acceptance.
- An ownership-scoped prior accepted-record link for duplicates, and a read-only
  historical revision view with reviewer, reason, prior/saved values and quotes.
  Mapping preserves the printed description. Saving still does not accept.
- Dashboard outcomes, strictly defined straight-through acceptance and the exact
  database median processing time with sample count. These are scoped to the user
  and filters; they are not computed from the recent-activity list.
- Buyer-oriented overview plus short [decisions](DESIGN-DECISIONS.md),
  [assumptions](ASSUMPTIONS.md), [AI-use](AI-USE.md) and
  [metrics](METRICS.md) notes. No in-app demo guide was added.

## Varied input evidence

Eight new synthetic inputs use ReportLab card/table layouts, real LibreOffice
Writer exports, two slash-date formats, a rasterized scan, a simulated rotated
photograph and an inconsistent payable. See the
[fixture provenance](../tests/fixtures/layouts/README.md).

All eight received fresh Gemini extraction using page text only. Four were
eligible and four were held: both slash dates, uncertain/mismatched photo amounts
and the inconsistent payable. There were no provider/processing failures in this
sample. Each case used an independent empty local ledger and synthetic reference
data. **Eligibility is not an acceptance.** No model input contained expected
outcomes, PO reference data or canned candidates.

The [saved evaluation](evidence/v0.12-layout-evaluation.json) retains those actual
candidates/timings and identifies the later local explanation recheck. These are
eight observations, not an accuracy guarantee, branded supplier exports or a real
camera-photo test.

## Verification

| Check | Observed result |
| --- | --- |
| Python components | 325 passed plus 45 subtests; 70 native tests skipped here and executed separately |
| Isolated native Postgres 16 | 70 passed, including new actor-scoped history, snapshot policy, duplicate link and exact metric aggregates |
| Web tests / production build | 31 passed / build passed |
| Browser walkthrough | Actual React/API plus disposable Postgres/PDF/OCR; external Auth/model/report explicitly simulated |
| Browser review boundary | Save mapping → nine checks pass → no commitment → separate reasoned accept → recorded commitment / report pending |
| Browser second resolution | Exact ambiguous PO selection preserves absent printed PO; one history control after revalidation |
| Browser other states | Missing total held, accessible prior duplicate link, filtered zero outcomes; dashboard and detail page width equals 390 px at mobile breakpoint |
| Linux AMD64 Docker | UI/live 200, unconfigured readiness 503, unauthenticated admin 401 |
| Serial document reading in Docker | 12 real PDF/JPEG/PNG inputs under 512 MiB / 1 CPU; cgroup peak 237,764,608 bytes (226.8 MiB) |
| Dated dependency audit | No known runtime Python or web-tree vulnerabilities reported |

The browser walkthrough found and fixed a duplicate-key rerender bug and
misleading downstream balance guidance for missing totals. The Docker probe was
initially aimed at port 8000; it was corrected to the configured port 10000 before
the recorded successful check. One Starlette/httpx test-client deprecation warning
remains. Package audits are not a complete security review.

## Remaining submission work

After owner review/approval, release the complete frontend/backend together and
verify v0.12 on the actual hosted service: version/assets, both roles, source
privacy, one fresh extraction, one exact acceptance and matching Sheet row.
Preserve existing records and reserve a genuinely unused approved pack. Measure
an idle-host wake-up separately; local Docker timings do not prove hosted capacity
or Render cold-start performance.

Rehearse the [five-minute script](DEMO.md). A missing blurred total stays held;
use an exact ambiguous PO or source-supported line mapping as the resolvable admin
example. Record and submit before Wednesday, 11 November 2026, 12:00 IST; target a
Tuesday release freeze. Recording, delivery and owner-controlled credential
rotation are not completed by automated tests.

Receipt matching, ERP/payment integration, SSO/MFA, multi-tenancy and email intake
remain outside the case-study build. No numerical score or uninterrupted Free
hosting guarantee is claimed.

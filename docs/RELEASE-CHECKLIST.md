# Case-study release gate

Candidate v0.11.0 is local only. Do not push main, deploy, import reference rows or
run a worker against the hosted database until the owner approves the completed
candidate. A local server with the normal .env may point at hosted data; it is
not an isolated staging environment.

## Claims from the external reviews

| Review concern | Current evidence/status |
| --- | --- |
| No repeatable fresh happy path | Pack generator and additive preparation already exist. B/C are shipped; local pack D adds an independent admin-review PO and eighth PDF. New packs use independent identities and budgets. Never delete ledger entries to rehearse. |
| Hosted flow unverified | v0.9 hosted Auth, evidence/hash, paging, fresh provider extraction and duplicate protection were verified separately. Earlier hosted acceptance and Sheets publication evidence exists. This is not hosted verification of v0.11. |
| No extraction cache/retry | Implemented before v0.10: one bounded transient retry, visible cache origin, uploader/hash/version-scoped provider evidence reuse, and all checks rerun. Admin review permissions are never cached or inherited. |
| README/DEMO cleanup | Product README and source-only operator walkthrough are already in place. No in-app demo guide or sample API is reintroduced. |
| Weak admin discretion | v0.10 adds auditable description-to-PO-line mapping and grounded OCR-confidence confirmation. Financial/source constraints remain enforced. |
| Misleading dependent warnings | v0.11 identifies the PO blocker and marks dependent checks as waiting. Missing procurement data cannot be bypassed by selecting an unrelated PO. |
| False readiness and imaging advisories | v0.11 requires complete/running processing, upgrades Pillow to 13.0.0 and restricts image decoder selection. Package audit and OCR tests pass locally. |

## Local verification

Run the Python components, isolated native Postgres suite, web tests and build:

```sh
.venv/bin/python -m pytest -q
npm run test:native-api
npm --prefix web test
npm --prefix web run build
uvx --from pip-audit pip-audit --disable-pip --no-deps -r requirements.txt
npm --prefix web audit
```

The native runner creates/destroys its own Postgres 16. It runs real PDF/OCR,
transactions and locks, while explicitly simulating Auth/model/Storage/Sheets.
Its complete fresh-pack story exercises acceptance, duplicate, partial/overbilling,
ambiguous PO, unreadable source, admin correction, explicit acceptance and report
publication. This is local integration evidence, not live provider evidence.

The actual review React components were checked in a temporary simulated-API
harness for permissions, payload, reset/cancel behavior and the audit summary.
No harness ships in the application or source archive.

## After explicit release approval

1. Review the complete local diff and credential scan; release the complete
   frontend/backend together. No schema migration is required.
2. Choose a truly unused pack. Check existing references and commitments first.
   Pack D's matching rows have NOT been imported into the hosted Sheet/database
   by this local work. Plan the additive import, inspect it, then apply only as
   part of the approved release/rehearsal. Existing rows/acceptances are preserved.
3. Verify deployed version and exact assets, real admin/user login and role/owner
   boundaries, dependency readiness, fresh reference import and private source.
4. Run one fresh clean extraction and actual acceptance, verify one exact Sheet
   report row and matching acceptance ID. Label any saved extraction honestly.
5. Show a duplicate, partial-PO overbilling and one admin resolution. Saving review
   must leave acceptance empty until explicit acceptance. Check audit evidence,
   final commitment and separate publication status.
6. Measure an actual idle/cold start separately from warm requests. Do not use
   historical local timings as a new hosted cold-start claim. Document any provider
   quota/failure and safe recovery; do not promise uninterrupted Free hosting.
7. Record the <=5-minute walkthrough and deliver the live link/private evaluator
   credentials. Recording/submission are not automatically completed by tests.

Production features such as receipts/three-way matching, ERP/payment integration,
SSO/MFA, multi-tenancy and email intake remain a roadmap. They are not required to
complete this case-study workflow. See PRODUCTION-READINESS.md for company gates.

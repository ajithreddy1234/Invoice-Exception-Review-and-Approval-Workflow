# Why the workflow behaves this way

The buyer is an AP reviewer who needs a supported invoice decision, an accurate
PO commitment and a clear next action. Acceptance here is not payment execution.

| Decision | Choice | Alternative considered and tradeoff |
| --- | --- | --- |
| Decision authority | Deterministic checks, then a transactional SQL gate | LLM approval would make a financial decision depend on variable model output. The model proposes evidenced fields only. |
| Vendor and PO matching | Exact approved name/alias; explicit PO or exact inferred candidates | Broad fuzzy automatic matches could select the wrong supplier/authorization. Ambiguity holds for a reasoned selection. |
| Close amounts | Explicit minor-unit arithmetic tolerance and evidenced rounding; hard cumulative PO/quantity caps | A percentage allowance on the remaining cap could approve more than procurement authorized. |
| Missing payable | Hold and request a clearer original | Computing the payable from subtotal, tax or PO balance would replace source evidence with an assumption. |
| Accounting authority | Postgres accepted ledger; Sheets references in and report out | Sheets-only balances lack the transaction/locking guarantees used to prevent concurrent over-consumption. Two-way sync would create a second financial authority. |
| Admin judgment | Source-grounded revisions, bounded interpretation mappings, all checks rerun, separate explicit acceptance | A generic override would bypass duplicate/source/authorization protections and obscure who changed what. |
| Model failures | Bounded retry, explicit failure and safe recovery; scoped extraction reuse | Unlimited retries risk duplicated work and quota use; a canned fixture result would not demonstrate real execution. |
| Status clarity | Decision, commitment and report publication are separate facts | Treating a report outage as a new financial decision encourages duplicate uploads or acceptances. |
| History | Preserve original evidence, revisions and ledger entries | Editing an acceptance or resetting history to replay a demo would undermine duplicate and balance guarantees. Fresh packs use new authorized identities. |

The four primary edge-case families are duplicates, partial PO/overbilling,
ambiguous matching and unreadable critical fields. Tax/rounding, different layouts,
bundled charges, missing fields and service failures support these families.
Business controls such as procurement ownership, opening commitments and approval
authority remain explicit assumptions rather than invented company policies.

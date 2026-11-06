# Controlled invoice exception review

This feature resolves uncertainty in an invoice's interpretation. Acceptance
records a verified invoice/PO commitment; it does not authorize or execute payment.

## Role permissions

| Capability | Normal user | Admin |
| --- | --- | --- |
| Upload and inspect source/checks | Own submissions | Workspace submissions |
| Retry supported unaccepted processing | Own submissions | Workspace submissions |
| Correct extraction from source quotes | No | Yes |
| Select among exact inferred PO candidates | No | Yes, with reason |
| Map a differently worded service to a PO line | No | Yes, within matched vendor/PO/currency |
| Confirm an existing grounded OCR confidence warning | No | Yes, specific fields only |
| Accept after every check passes | Automatic policy only; no manual acceptance | Explicit acceptance with reason |
| Reject or record a clearer-source request | No | Yes |
| Override duplicates, missing evidence or financial limits | No | No |
| Change accepted financial history | No | No |

## Description mapping

An invoice might say **Consulting support hours** while the PO says **Consulting
services**. Changing the extracted description to the PO wording would falsify
the source. Instead, an admin chooses an authorized line of the matched PO and
records why the wording refers to that line.

The printed description and source quote remain unchanged. Quantity, unit, unit
price, tax, arithmetic, cumulative quantity and remaining PO value still pass the
normal checks. Mapping cannot create missing quantities/prices/descriptions,
convert units, select another vendor's PO, contradict a printed PO, or permit a
closed PO. Unit/price differences need an applicable reference policy or a
corrected invoice; a mapping does not create a new tolerance.

Only a printed matching PO or an exact inferred PO candidate is usable. Mapping
does not broaden PO inference or enable automatic fuzzy matching. The reference
version from the review choices must match at save time; a changed reference
requires reload and review.

## OCR confidence confirmation

Low OCR confidence is different from no readable source value. When the exact
quoted value already exists in the server-read page text and its only evidence
issue is LOW_OCR_CONFIDENCE, the admin may confirm it against the readable original.
The confirmation is field-specific. Raw OCR warnings remain stored.

The admin cannot supply a missing blurred total, invent a value absent from the
quote, acknowledge an unsupported invoice ID, remove conflicting totals/IDs or
ignore an unpaired identifier layout. These require a clearer/corrected source.
This feature does not implement free-form visual transcription when OCR failed.

## Save, revalidate, then explicitly accept

1. Open the source and checks. Correct extraction fields using exact page quotes
   if required. Save corrections first; reopen review for fresh choices.
2. Select a line mapping or check a supported OCR confirmation only after viewing
   the source. Explain the interpretation and evidence in the review reason.
3. Save. The server re-downloads and hashes the original, re-reads evidence,
   checks role, revision, reference freshness and processing state, and reruns all
   nine checks against the current ledger. It writes a new immutable revision.
4. An eligible result remains **Needs review**, with **admin_required** acceptance.
   Saving a review never accepts. A separate **Accept with reason** action invokes
   the SQL transaction, which rechecks current reference, duplicate identity and
   available value/quantity. A competing acceptance can still make it fail safely.
5. An acceptance creates one durable publication task. Spreadsheet retry never
   accepts again. Failed/unresolved reviews consume no PO balance.

Editing source fields clears current mapping/confirmation choices. Reopening
review loads fresh options and requires choices again. Reprocessing never
inherits manual permissions, and admin-corrected evidence cannot seed extraction
reuse. Previous manual interpretations remain in immutable history.

## Recorded proof

The revision and review action record actor, reason, base revision, source hash,
reference version, original wording, selected PO/line and specifically confirmed
OCR fields. Raw warnings and effective checks are stored separately. Explicit
acceptance records its own actor/reason/validation and acceptance ID. The invoice
view displays the recorded resolution; detail API retains complete evidence.

No new database migration or Sheet columns are needed. These records use existing
immutable evidence, validation, review and acceptance tables.

# Synthetic invoice fixtures — Step 1

These are real source documents for building the application: 27 PDFs and 3 standalone input images. They contain synthetic company information, realistic amounts and source variations. Expected decisions are **not embedded in the invoices**.

Use `manifest.json` for the expected outcome and, critically, its precondition. Do not send the manifest or an expected decision to the LLM or use filenames to shortcut the rule engine. The application must process actual document content.

## Recommended first runs

| Scenario | Files and order | Expected |
|---|---|---|
| Happy path | `pdfs/happy_full.pdf` on fresh PO-FULL | Accepted if extraction/evidence/checks pass |
| Duplicate | Happy path, then renamed/re-exported PDF or `images/duplicate_screenshot.png` | No second commitment |
| Different vendor | After happy path, `pdfs/other_vendor_same_number.pdf` on unused PO-BETA | Same number does not create a false duplicate across vendors |
| Approved vendor alias | Fresh PO-FULL: `pdfs/vendor_alias_only.pdf` | Acme Services matches an approved alias; accepted only if all other checks pass |
| Unknown vendor name | Fresh PO-FULL: `pdfs/vendor_unknown_name.pdf` | Review: Northstar Office Services has no approved vendor match |
| Partial fits | Fresh PO-PARTIAL: `split_6000.pdf`, then `split_4000.pdf` | Accepted 6,000 + 4,000 |
| Partial overbills | Reset PO-PARTIAL: `split_6000.pdf`, then `split_4500.pdf` | Second invoice needs review: only 4,000 remains |
| Ambiguous match | Fresh scenario: `ambiguous_no_po.pdf` | Candidates PO-AMBIG-A and PO-AMBIG-B; admin review |
| Clean scan | Fresh PO-FULL: `scan_clean.pdf` OR `images/scan_clean.jpg` | OCR runs and can support acceptance |
| Unreadable amount | Fresh PO-FULL: `scan_blurred_total.pdf` | Review; payable value unreadable |
| Bundled charge / V12 | Fresh PO-PARTIAL: `bundled_charges.pdf` | Review; no supported hours/quantity allocation |
| Concurrency | Fresh PO-RACE: submit `race_a_6000.pdf` and `race_b_6000.pdf` together | Either wins; only one 6,000 acceptance |

## Important branch rules

- Reset between independent scenarios using the same PO. Accepting the happy path consumes PO-FULL; do not then expect another independent full-PO fixture to pass.
- Do not run the 4,500 overbilling branch after accepting both 6,000 and 4,000. It is designed to show 4,000 remaining, not zero.
- Clean and blurred scans intentionally share an invoice identity and are alternative source-quality branches. If the clean counterpart was already accepted, the blurred version would correctly be a duplicate instead of demonstrating uncertainty.
- A PDF and JPEG of the same scan can deliberately test cross-format duplicate detection. Run either alone on reset data for the clean OCR test.
- The clean scan manifest IDs are `scan_clean_pdf` and `scan_clean_jpg`; paths remain `pdfs/scan_clean.pdf` and `images/scan_clean.jpg`. All 30 IDs are unique.
- Alias-only and unknown-name PDFs omit the vendor code and tax registration entirely, including the account email and author metadata. They have independent invoice numbers, `INV-ALIAS-01` and `INV-UNKNOWN-01`. The unknown vendor must not become a match merely because its printed PO belongs to Acme.
- Separate-tax, inclusive-tax and tax-mismatch cases each need a reset PO-TAX.
- Tolerance examples use explicit rounding; the hard PO ceiling remains strict.
- `vendor_unapproved.pdf` has a matching PO-HOLD, so its vendor-status issue is not confused with a missing PO.
- Currency-mismatch input explicitly says USD against an INR PO; no FX conversion is supported.
- `missing_total.pdf` still exposes line/subtotal amounts, but no printed payable total. Calculating an expected amount does not resolve the missing critical source field.

## Regenerate

From the package root:

```sh
python -m pip install -r tools/requirements-fixtures.txt
python tools/generate_fixtures.py
python tools/verify_fixture_ocr.py
```

The last command additionally requires local Tesseract. Generating invoices does not require API keys or cloud services. PDF creation uses deterministic metadata and scan noise under the pinned library versions; exact duplicates keep identical bytes, while re-export/screenshot variants deliberately change their hashes.

`VERIFICATION.md` covers structure/hashes. `OCR-SMOKE.md` is a local cropped-source check when run. `QA-REPORT.md` records the visual/reproducibility checks performed for the delivered package. None proves the still-unbuilt backend's decisions or real Gemini extraction.

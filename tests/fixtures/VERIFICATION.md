# Fixture verification

27 PDFs and 3 images generated and structurally checked. All 30 fixture IDs and paths are unique, and scenario sequences reference existing IDs. This is not an end-to-end extraction/decision result.

- PASS: pdfs/happy_full.pdf — 2733 bytes, SHA-256 verified
- PASS: pdfs/vendor_alias_only.pdf — 2667 bytes, SHA-256 verified
- PASS: pdfs/vendor_unknown_name.pdf — 2694 bytes, SHA-256 verified
- PASS: pdfs/duplicate_same_renamed.pdf — 2733 bytes, SHA-256 verified
- PASS: pdfs/duplicate_reexported.pdf — 2785 bytes, SHA-256 verified
- PASS: pdfs/other_vendor_same_number.pdf — 2720 bytes, SHA-256 verified
- PASS: pdfs/conflicting_revision.pdf — 2735 bytes, SHA-256 verified
- PASS: pdfs/split_6000.pdf — 2732 bytes, SHA-256 verified
- PASS: pdfs/split_4000.pdf — 2733 bytes, SHA-256 verified
- PASS: pdfs/split_4500.pdf — 2736 bytes, SHA-256 verified
- PASS: pdfs/ambiguous_no_po.pdf — 2707 bytes, SHA-256 verified
- PASS: pdfs/scan_clean.pdf — 117737 bytes, SHA-256 verified
- PASS: pdfs/scan_blurred_total.pdf — 115136 bytes, SHA-256 verified
- PASS: pdfs/missing_number.pdf — 2704 bytes, SHA-256 verified
- PASS: pdfs/missing_date.pdf — 2716 bytes, SHA-256 verified
- PASS: pdfs/missing_total.pdf — 2720 bytes, SHA-256 verified
- PASS: pdfs/rounding_within.pdf — 2787 bytes, SHA-256 verified
- PASS: pdfs/rounding_outside.pdf — 2784 bytes, SHA-256 verified
- PASS: pdfs/cap_over_by_050.pdf — 2773 bytes, SHA-256 verified
- PASS: pdfs/tax_separate.pdf — 2728 bytes, SHA-256 verified
- PASS: pdfs/tax_inclusive.pdf — 2683 bytes, SHA-256 verified
- PASS: pdfs/tax_mismatch.pdf — 2730 bytes, SHA-256 verified
- PASS: pdfs/bundled_charges.pdf — 2728 bytes, SHA-256 verified
- PASS: pdfs/race_a_6000.pdf — 2737 bytes, SHA-256 verified
- PASS: pdfs/race_b_6000.pdf — 2738 bytes, SHA-256 verified
- PASS: pdfs/vendor_unapproved.pdf — 2726 bytes, SHA-256 verified
- PASS: pdfs/currency_mismatch.pdf — 2740 bytes, SHA-256 verified
- PASS: images/duplicate_screenshot.png — 131688 bytes, SHA-256 verified
- PASS: images/scan_clean.jpg — 101845 bytes, SHA-256 verified
- PASS: images/clean_invoice.png — 133125 bytes, SHA-256 verified

Exact renamed duplicate has identical bytes; re-export and screenshot have different hashes. Scan PDFs contain images only, with no hidden text. Alias-only and unknown-name PDFs print neither a vendor code nor tax identifier, and use the printed vendor name in their author metadata. Scenario outcomes require the stated initial conditions; reset between independent branches.

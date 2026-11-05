# Fixture QA — delivered Step 1

Updated 1 November 2026 with the pinned fixture dependencies. Original 28 sources retain their bytes; the two name-only vendor cases are new.

| Check | Result |
|---|---|
| Count and types | PASS: 27 one-page PDFs, 3 JPEG/PNG input images |
| Unique fixture IDs | PASS: all 30 unique; clean scan IDs are scan_clean_pdf and scan_clean_jpg |
| Upload size | PASS: every source is below the 5 MiB application limit |
| Image-only scans | PASS: clean and blurred scanned PDFs have no hidden text layer |
| Exact renamed duplicate | PASS: identical bytes/SHA-256 to happy_full.pdf |
| Re-export and screenshot | PASS: different bytes/SHA-256, same intended invoice identity |
| Reproducibility | PASS: independent regeneration reproduced all 30 source bytes and the manifest byte for byte |
| Spreadsheet consistency | PASS: all 8 PO budgets equal their line-derived gross amounts; 18% converts to 1800 basis points |
| Visual review | PASS: original 25 PDF pages and 3 image inputs reviewed through rendered contact sheets on 31 October; both newly generated vendor-name PDFs rendered and inspected at larger size on 1 November |
| Name-only vendor sources | PASS: both PDFs omit vendor code and tax registration in extracted text and use the printed vendor name as author metadata; unique invoice numbers are INV-ALIAS-01 and INV-UNKNOWN-01 |
| Clean payable OCR crop | PASS: local Tesseract reads INR 10,000.00 |
| Blurred payable OCR crop | PASS: no numeric text returned from the obscured payable value |
| Expected outcomes kept out of source | PASS: scenario decisions/preconditions are separate manifest data, not printed on source invoices |

Deliberate missing/blurred fields and inconsistent totals are test inputs, not formatting defects. The blurred case still contains other values from which a mathematical amount might be inferred; the application must distinguish an inferred calculation from a supported printed payable amount.

These checks do not demonstrate Gemini field extraction, application evidence verification, admin review, actual Sheets API integration, or invoice acceptance end to end. Those are subsequent build steps. The existing schema/native SQL reports remain separate evidence and were not unnecessarily rerun for this fixture-only change.

# Varied synthetic invoice inputs

These eight files exercise different source layouts and document readers. They
are not a fresh hosted demo pack: they use `tests/reference_data/` PO codes.
Evaluate each independent case against a fresh isolated ledger. Uploading all of
them into an already-used workspace can correctly produce duplicate/balance holds.
`06_scan_statement.pdf` deliberately has the same identity as `03_writer_tax.pdf`.

| File | Source | Intended safe behavior |
| --- | --- | --- |
| 01 card | ReportLab canvas, boxed summary | Eligible when all extracted fields are grounded and the PO is unused |
| 02 table | ReportLab Platypus, tabular lines | Partial allocation; eligible for six of ten hours |
| 03 Writer tax | Actual LibreOffice Writer ODT-to-PDF export | Explicit 18% tax; eligible when grounded |
| 04 slash date | Writer, `13/10/2026` | Held by current supported-date policy |
| 05 ambiguous date | Writer, `05/06/2026` | Held; no silent locale guess |
| 06 scan | Rasterized Writer PDF with no text layer | OCR required; grounded eligibility or an explained hold |
| 07 photo-like | Rotated synthetic JPEG with altered brightness/contrast | OCR required; unsupported fields remain held |
| 08 inconsistent payable | Card with contradictory payable values | Held; no inferred repair |

All company/invoice data is synthetic. The JPEG simulates a photograph; it is not
a camera capture. The Writer exports are not Microsoft Word, Canva, Zoho or
Stripe exports. The manifest records generation provenance, identities and hashes.
Its expectations are test data only; production extraction/rules never read them.

Regenerate with the existing Python development dependencies and LibreOffice
(`soffice` on PATH):

```sh
.venv/bin/python tools/generate_layout_fixtures.py --help
.venv/bin/python tools/generate_layout_fixtures.py
.venv/bin/python -m pytest tests/test_layout_inputs.py
```

The offline tests use real PDF/OCR reading and explicit grounded candidate fields;
they verify reading/rule behavior, not provider accuracy. For a separate opt-in
real-model evaluation with the configured Gemini key:

```sh
.venv/bin/python scripts/evaluate_layouts.py --live-model --output /tmp/invoice-layout-evaluation.json
```

That script sends page text only. It does not send expected outcomes, reference
records or candidate fixtures to the model. It runs read-only in-memory reference
checks with an isolated empty ledger per file; it never accepts an invoice or
writes a Sheet row. Model results can vary. Inspect each saved candidate, source
issue and check rather than promising automatic acceptance for a file name.

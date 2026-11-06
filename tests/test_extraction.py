"""Source-backed extraction tests; no model or reference-data fixture shortcut."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pydantic import ValidationError
from PIL import Image

from app.extraction import (
    CandidateField, DocumentText, ExtractionError, GeminiExtractor, InvoiceCandidate,
    MAX_BYTES, PageText, Source, generation_schema, read_document, validate_evidence,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def field(value, quote=None, page=1):
    return CandidateField(value=value, source=Source(page=page, quote=quote or value) if value else None)


def candidate(total="10000.00", quote="TOTAL PAYABLE\nINR 10,000.00"):
    return InvoiceCandidate(
        vendor_name=field("Acme Services Pvt Ltd"), invoice_number=field("INV-1001"),
        invoice_date=field("2026-10-31"), po_reference=field("PO-FULL"),
        currency=field("INR"), subtotal_net=field(None), tax_amount=field(None),
        total_gross=field(total, quote), tax_presentation="none", line_items=[], uncertainties=[],
    )


def issues_for(value, document):
    return {(issue.field, issue.code) for issue in validate_evidence(value, document)}


class DocumentTests(unittest.TestCase):
    def test_text_pdf_without_ocr_or_filename(self):
        data = (FIXTURES / "pdfs/happy_full.pdf").read_bytes()
        with patch("app.extraction._ocr", side_effect=AssertionError("embedded PDF must not need OCR")):
            doc = read_document(data, "application/pdf")
        self.assertEqual(doc.pages[0].method, "embedded")
        self.assertIn("INV-1001", doc.pages[0].text)
        self.assertEqual(validate_evidence(candidate(), doc), [])

    def test_clean_scan_reads_payable(self):
        doc = read_document((FIXTURES / "pdfs/scan_clean.pdf").read_bytes(), "application/pdf")
        self.assertEqual(doc.pages[0].method, "ocr")
        self.assertIn("INV-SCAN-01", doc.pages[0].text)
        value = candidate()
        value.invoice_number = field("INV-SCAN-01")
        self.assertEqual(validate_evidence(value, doc), [])

    def test_blurred_scan_cannot_use_visible_subtotal(self):
        doc = read_document((FIXTURES / "pdfs/scan_blurred_total.pdf").read_bytes(), "application/pdf")
        self.assertEqual(doc.pages[0].method, "ocr")
        self.assertIn("INV-SCAN-01", doc.pages[0].text)
        # Even an adversarial model citing a real subtotal gets blocked.
        value = candidate(quote="Subtotal (net) INR 10,000.00")
        value.invoice_number = field("INV-SCAN-01")
        self.assertIn(("total_gross", "PAYABLE_EVIDENCE_REQUIRED"), issues_for(value, doc))
        value.total_gross = field(None)
        self.assertIn(("total_gross", "MISSING_CRITICAL_FIELD"), issues_for(value, doc))

    def test_png_and_jpeg_are_ocr_inputs(self):
        for filename, mime, invoice_number in [("clean_invoice.png", "image/png", "INV-IMAGE-01"),
                                                ("scan_clean.jpg", "image/jpeg", "INV-SCAN-01")]:
            with self.subTest(filename=filename):
                doc = read_document((FIXTURES / "images" / filename).read_bytes(), mime)
                self.assertEqual(doc.pages[0].method, "ocr")
                self.assertIn(invoice_number, doc.pages[0].text)

    def test_size_type_and_corrupt_inputs_fail_closed(self):
        for data, mime, code in [(b"", "application/pdf", "EMPTY_DOCUMENT"),
                                 (b"x" * (MAX_BYTES + 1), "application/pdf", "DOCUMENT_TOO_LARGE"),
                                 (b"hello", "text/plain", "UNSUPPORTED_DOCUMENT_TYPE"),
                                 (b"hello", "application/pdf", "INVALID_PDF"),
                                 (b"%PDF-not-a-pdf", "application/pdf", "DOCUMENT_UNREADABLE")]:
            with self.subTest(code=code), self.assertRaises(ExtractionError) as error:
                read_document(data, mime)
            self.assertEqual(error.exception.code, code)

    def test_image_signature_is_checked_and_ocr_timeout_is_bounded(self):
        image = Image.new("RGB", (20, 20), "white")
        data = io.BytesIO()
        image.save(data, format="PNG")
        with self.assertRaises(ExtractionError) as error:
            read_document(data.getvalue(), "image/jpeg")
        self.assertEqual(error.exception.code, "DOCUMENT_TYPE_MISMATCH")
        import subprocess
        with patch("app.extraction.subprocess.run", side_effect=subprocess.TimeoutExpired("tesseract", 25)):
            with self.assertRaises(ExtractionError) as error:
                read_document(data.getvalue(), "image/png")
        self.assertEqual(error.exception.code, "OCR_TIMEOUT")

    def test_unapproved_image_decoders_are_not_used_for_declared_upload_types(self):
        from app.preview_worker import render
        from PIL import UnidentifiedImageError
        for format_name in ("GIF", "TIFF", "BMP"):
            data = io.BytesIO()
            Image.new("RGB", (20, 20), "white").save(data, format=format_name)
            for mime in ("image/png", "image/jpeg"):
                with self.subTest(format=format_name, mime=mime):
                    with patch("app.extraction._ocr", side_effect=AssertionError("must reject before OCR")):
                        with self.assertRaises(ExtractionError) as error:
                            read_document(data.getvalue(), mime)
                    self.assertEqual(error.exception.code, "DOCUMENT_UNREADABLE")
                    with self.assertRaises(UnidentifiedImageError):
                        render(data.getvalue(), mime, 1)

    def test_preview_rejects_a_valid_image_with_the_wrong_declared_type(self):
        from app.preview_worker import render
        from PIL import UnidentifiedImageError
        for format_name, mime in (("PNG", "image/jpeg"), ("JPEG", "image/png")):
            data = io.BytesIO()
            Image.new("RGB", (20, 20), "white").save(data, format=format_name)
            with self.subTest(format=format_name), self.assertRaises(UnidentifiedImageError):
                render(data.getvalue(), mime, 1)


class EvidenceTests(unittest.TestCase):
    def doc(self, extra=""):
        return DocumentText(pages=[PageText(number=1, method="embedded", text=(
            "Acme Services Pvt Ltd\nInvoice number: INV-1001\n2026-10-31\nPO-FULL\nINR\n"
            "Subtotal INR 10,000.00\nTOTAL PAYABLE INR 10,000.00\n" + extra))])

    def test_unknown_layout_can_pass_with_actual_evidence(self):
        # Model candidates are not selected by file name, template or invoice ID.
        doc = self.doc()
        value = candidate(quote="TOTAL PAYABLE INR 10,000.00")
        self.assertEqual(validate_evidence(value, doc), [])

    def test_forged_quote_and_changed_value_are_rejected(self):
        value = candidate(quote="TOTAL PAYABLE INR 99,999.00")
        self.assertIn(("total_gross", "QUOTE_NOT_FOUND"), issues_for(value, self.doc()))
        value.total_gross = field("99999.00", "TOTAL PAYABLE INR 10,000.00")
        self.assertIn(("total_gross", "VALUE_NOT_SUPPORTED"), issues_for(value, self.doc()))

    def test_invoice_identity_is_not_a_substring_match(self):
        doc = self.doc()
        doc.pages[0].text = doc.pages[0].text.replace("INV-1001", "INV-10010")
        value = candidate(quote="TOTAL PAYABLE INR 10,000.00")
        value.invoice_number = field("INV-1001", "INV-10010")
        self.assertIn(("invoice_number", "VALUE_NOT_SUPPORTED"), issues_for(value, doc))

    def test_invoice_punctuation_and_leading_zeros_are_identity(self):
        for printed, extracted, expected_supported in [
            ("INV-1001-A", "INV-1001", False),
            ("INV-1001/2026", "INV-1001", False),
            ("INV-1001.A", "INV-1001", False),
            ("INV-1001_A", "INV-1001", False),
            ("INV-001/2026-A", "INV-001/2026-A", True),
            ("INV-001/2026-A", "INV-1/2026-A", False),
            ("0001001", "1001", False),
            ("0001001", "0001001", True),
        ]:
            with self.subTest(printed=printed, extracted=extracted):
                doc = self.doc()
                doc.pages[0].text = doc.pages[0].text.replace("INV-1001", f"Invoice number: {printed}")
                value = candidate(quote="TOTAL PAYABLE INR 10,000.00")
                value.invoice_number = field(extracted, f"Invoice number: {printed}")
                issues = issues_for(value, doc)
                self.assertEqual(("invoice_number", "VALUE_NOT_SUPPORTED") not in issues, expected_supported)

    def test_conflicting_totals_across_pages_are_rejected(self):
        doc = self.doc()
        doc.pages.append(PageText(number=2, method="embedded", text="GRAND TOTAL INR 12,000.00"))
        value = candidate(quote="TOTAL PAYABLE INR 10,000.00")
        self.assertIn(("total_gross", "CONFLICTING_PAYABLE_VALUES"), issues_for(value, doc))

    def test_payment_terms_number_is_not_a_payable_amount(self):
        doc = self.doc()
        doc.pages[0].text = doc.pages[0].text.replace("TOTAL PAYABLE INR 10,000.00", "Amount due within 14 days")
        value = candidate("14", "Amount due within 14 days")
        self.assertIn(("total_gross", "PAYABLE_EVIDENCE_REQUIRED"), issues_for(value, doc))

    def test_low_confidence_critical_evidence_requires_review(self):
        doc = self.doc()
        doc.pages[0].method = "ocr"
        doc.pages[0].low_confidence_tokens = ["10,000.00"]
        value = candidate(quote="TOTAL PAYABLE INR 10,000.00")
        self.assertIn(("total_gross", "LOW_OCR_CONFIDENCE"), issues_for(value, doc))

    def test_no_silent_schema_coercion_or_extra_decision_fields(self):
        raw = candidate().model_dump()
        raw["approved"] = True
        with self.assertRaises(ValidationError):
            InvoiceCandidate.model_validate(raw)
        with self.assertRaises(ValidationError):
            Source(page="1", quote="invoice")


class GeminiContractTests(unittest.TestCase):
    def test_text_only_request_and_local_validation(self):
        calls = []

        class Client:
            def __init__(self, **kwargs):
                self.models = self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def generate_content(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(text=candidate().model_dump_json())

        fake_types = SimpleNamespace(HttpOptions=lambda **kw: kw, GenerateContentConfig=lambda **kw: kw)
        fake_genai = SimpleNamespace(Client=Client, types=fake_types)
        fake_google = SimpleNamespace(genai=fake_genai)
        with patch.dict("sys.modules", {"google": fake_google, "google.genai": fake_genai}):
            doc = DocumentText(pages=[PageText(number=1, method="embedded", text="arbitrary invoice")])
            result = GeminiExtractor("not-a-real-key", "configured-model").extract(doc)
        self.assertEqual(result.invoice_number.value, "INV-1001")
        self.assertIsInstance(calls[0]["contents"], str)
        self.assertEqual(calls[0]["contents"], "PAGE 1\narbitrary invoice")
        self.assertNotIn('response_schema', calls[0]['config'])
        self.assertEqual(calls[0]['config']['response_json_schema'], generation_schema())
        self.assertFalse(calls[0]['config']['response_json_schema']['additionalProperties'])

    def test_provider_schema_keeps_shape_and_local_bounds_remain_strict(self):
        schema = generation_schema()
        self.assertEqual(schema['required'], InvoiceCandidate.model_json_schema()['required'])
        self.assertNotIn('maxItems', schema['properties']['line_items'])
        self.assertEqual(InvoiceCandidate.model_json_schema()['properties']['line_items']['maxItems'], 100)
        self.assertFalse(schema['additionalProperties'])


if __name__ == "__main__":
    unittest.main()

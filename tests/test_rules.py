"""Business-rule tests use real text sources and separately constructed candidates.

Fixture manifests/expected decisions are never inputs to production evaluation.
"""
import csv
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from app.extraction import (CandidateField, CandidateLine, DocumentText, InvoiceCandidate,
                            PageText, Source, read_document)
from app.procurement import parse_reference
from app.rules import CHECK_CODES, evaluate

ROOT = Path(__file__).resolve().parent


def reference():
    tabs = {}
    for name in ("Vendors", "PurchaseOrders", "POLines", "Rules"):
        with (ROOT / "reference_data" / f"{name}.csv").open() as stream:
            tabs[name] = list(csv.reader(stream))
    parsed = parse_reference(tabs)
    return {"id": "reference-1", "fresh": True,
            **{name: [asdict(row) for row in getattr(parsed, name)]
               for name in ("vendors", "pos", "lines", "rules")}}


def field(value, quote=None):
    return CandidateField(value=value, source=Source(page=1, quote=quote or value) if value else None)


def money(value):
    return field(str(value), f"{Decimal(value):,.2f}") if value is not None else field(None)


def invoice(*, number="INV-1001", po="PO-FULL", vendor="Acme Services Pvt Ltd",
            description="Office support package", quantity="10", unit="1000.00",
            net="10000.00", tax="0.00", total="10000.00", presentation="none",
            inclusive=False):
    line = CandidateLine(description=field(description), quantity=field(quantity), unit=field("hour"),
                         unit_price=money(unit), net_amount=field(None) if inclusive else money(net),
                         tax_amount=field(None), gross_amount=money(total) if inclusive else field(None))
    return InvoiceCandidate(vendor_name=field(vendor), invoice_number=field(number),
        invoice_date=field("2026-10-31"), po_reference=field(po), currency=field("INR"),
        subtotal_net=field(None) if inclusive else money(net),
        tax_amount=field(None) if inclusive else money(tax),
        total_gross=field(total, "TOTAL PAYABLE\nINR " + f"{Decimal(total):,.2f}") if total else field(None),
        tax_presentation=presentation, line_items=[line], uncertainties=[])


def source(filename):
    return read_document((ROOT / "fixtures/pdfs" / filename).read_bytes(), "application/pdf")


def ledger(**updates):
    return {"accepted_amounts": {}, "accepted_quantities": {}, "duplicate": False, **updates}


def checks(decision):
    return {row["code"]: row["status"] for row in decision.checks}


def synthetic(candidate, extra=""):
    # Independent rule-unit source containing the candidate's exact visible quotes;
    # actual fixture-backed tests below separately exercise source evidence/OCR.
    quotes = []
    for name in InvoiceCandidate.model_fields:
        value = getattr(candidate, name)
        if isinstance(value, CandidateField) and value.source:
            quotes.append(("Invoice number: " if name == "invoice_number" else "") + value.source.quote)
    for line in candidate.line_items:
        for name in CandidateLine.model_fields:
            value = getattr(line, name)
            if value.source:
                quotes.append(value.source.quote)
    return DocumentText(pages=[PageText(number=1, method="embedded", text="\n".join(quotes) + "\n" + extra)])


class RuleTests(unittest.TestCase):
    def test_happy_full_emits_exactly_nine_checks_and_schema_fields(self):
        decision = evaluate(invoice(), source("happy_full.pdf"), reference(), ledger())
        self.assertEqual(decision.verdict, "eligible", decision.checks)
        self.assertEqual(decision.acceptance_mode, "automatic")
        self.assertEqual([row["code"] for row in decision.checks], list(CHECK_CODES))
        self.assertTrue(all(row["status"] == "pass" for row in decision.checks))
        self.assertEqual(decision.revision["invoice_date"], date(2026, 10, 31))
        self.assertEqual(decision.revision["total_gross_minor"], 1_000_000)
        self.assertEqual(decision.revision["unresolved_critical_fields"], [])
        self.assertEqual(decision.allocations, [{"line_code": "SERVICE", "quantity": Decimal(10),
            "net_minor": 1_000_000, "tax_minor": 0, "gross_minor": 1_000_000}])

    def test_partial_six_then_four_and_four_point_five_branch(self):
        first = invoice(number="INV-PART-01", po="PO-PARTIAL", description="Consulting services",
                        quantity="6", net="6000.00", total="6000.00")
        result = evaluate(first, source("split_6000.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)
        committed = ledger(accepted_amounts={"PO-PARTIAL": 600_000},
                           accepted_quantities={("PO-PARTIAL", "SERVICE"): Decimal(6)})
        second = invoice(number="INV-PART-02", po="PO-PARTIAL", description="Consulting services",
                         quantity="4", net="4000.00", total="4000.00")
        result = evaluate(second, source("split_4000.pdf"), reference(), committed)
        self.assertEqual(result.verdict, "eligible", result.checks)
        too_much = invoice(number="INV-PART-03", po="PO-PARTIAL", description="Consulting services",
                           quantity="4.5", net="4500.00", total="4500.00")
        result = evaluate(too_much, source("split_4500.pdf"), reference(), committed)
        self.assertEqual(result.verdict, "needs_review")
        self.assertEqual(checks(result)["po_balance"], "review")
        self.assertIn("INR 500.00", next(row["detail"] for row in result.checks if row["code"] == "po_balance"))

    def test_duplicate_blocks_but_same_number_other_vendor_is_not_intrinsically_duplicate(self):
        result = evaluate(invoice(), source("happy_full.pdf"), reference(), ledger(duplicate=True))
        self.assertEqual(result.verdict, "blocked")
        self.assertEqual(result.acceptance_mode, "not_allowed")
        other = invoice(po="PO-BETA", vendor="Beta Consulting Pvt Ltd", description="Consulting services")
        result = evaluate(other, synthetic(other), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)

    def test_alias_passes_unknown_and_unapproved_vendor_do_not(self):
        alias = invoice(number="INV-ALIAS-01", vendor="Acme Services")
        result = evaluate(alias, source("vendor_alias_only.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)
        unknown = invoice(number="INV-UNKNOWN-01", vendor="Northstar Office Services")
        result = evaluate(unknown, source("vendor_unknown_name.pdf"), reference(), ledger())
        self.assertEqual(checks(result)["source_evidence"], "pass")
        self.assertEqual(checks(result)["vendor_match"], "review")
        unapproved = invoice(number="INV-HOLD-01", po="PO-HOLD", vendor="Hold Vendor Pvt Ltd",
                             description="Unapproved vendor services")
        result = evaluate(unapproved, source("vendor_unapproved.pdf"), reference(), ledger())
        self.assertEqual(checks(result)["source_evidence"], "pass")
        self.assertEqual(checks(result)["vendor_match"], "review")
        for vendor in ("Acme Service", "Unknown Services", "Hold Vendor Pvt Ltd"):
            with self.subTest(vendor=vendor):
                value = invoice(vendor=vendor)
                result = evaluate(value, synthetic(value), reference(), ledger())
                self.assertEqual(checks(result)["vendor_match"], "review")

    def test_ambiguous_po_is_not_array_order_selection(self):
        value = invoice(number="INV-AMB-01", po=None, description="Website design milestones",
                        quantity="5", net="5000.00", total="5000.00")
        result = evaluate(value, source("ambiguous_no_po.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "needs_review")
        self.assertIsNone(result.po_code)
        self.assertEqual({row["po_code"] for row in result.po_candidates}, {"PO-AMBIG-A", "PO-AMBIG-B"})
        unique = invoice(po=None)
        result = evaluate(unique, synthetic(unique), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)
        self.assertEqual(result.po_code, "PO-FULL")

    def test_clean_scan_can_pass_but_blurred_or_missing_total_does_not(self):
        value = invoice(number="INV-SCAN-01")
        result = evaluate(value, source("scan_clean.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)
        value.total_gross = field(None)
        result = evaluate(value, source("scan_blurred_total.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "needs_review")
        self.assertIn("total_gross", result.revision["unresolved_critical_fields"])
        # A fabricated readable total is also blocked against the same blurred PDF.
        value = invoice(number="INV-SCAN-01")
        result = evaluate(value, source("scan_blurred_total.pdf"), reference(), ledger())
        self.assertEqual(checks(result)["source_evidence"], "review")

    def test_tax_exclusive_inclusive_and_mismatch(self):
        exclusive = invoice(number="INV-TAX-01", po="PO-TAX", description="Tax advisory services",
                            tax="1800.00", total="11800.00", presentation="exclusive")
        result = evaluate(exclusive, source("tax_separate.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)
        inclusive = invoice(number="INV-TAX-02", po="PO-TAX", description="Tax advisory services",
                            unit="1180.00", total="11800.00", presentation="inclusive", inclusive=True)
        result = evaluate(inclusive, source("tax_inclusive.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "eligible", result.checks)
        self.assertIsNone(result.revision["tax_minor"])
        self.assertEqual(result.allocations[0]["tax_minor"], 180_000)
        exclusive = invoice(number="INV-TAX-03", po="PO-TAX", description="Tax advisory services",
                            tax="1800.00", total="11700.00", presentation="exclusive")
        result = evaluate(exclusive, source("tax_mismatch.pdf"), reference(), ledger())
        self.assertEqual(checks(result)["arithmetic"], "review")

    def test_rounding_actual_fixtures_and_inclusive_boundary(self):
        for filename, number, total, expected in [
            ("rounding_within.pdf", "INV-ROUND-01", "9999.50", "eligible"),
            ("rounding_outside.pdf", "INV-ROUND-02", "9998.00", "needs_review"),
            ("cap_over_by_050.pdf", "INV-CAP-01", "10000.50", "needs_review"),
        ]:
            with self.subTest(filename=filename):
                value = invoice(number=number, total=total)
                result = evaluate(value, source(filename), reference(), ledger())
                self.assertEqual(result.verdict, expected, result.checks)
        for total, adjustment, expected in [("9999.00", "-1.00", "eligible"),
                                             ("9998.99", "-1.01", "needs_review")]:
            value = invoice(total=total)
            result = evaluate(value, synthetic(value, "Rounding adjustment INR " + adjustment), reference(), ledger())
            self.assertEqual(result.verdict, expected, result.checks)

    def test_bundled_total_fitting_balance_never_invents_quantity(self):
        value = invoice(number="INV-BUNDLE-01", po="PO-PARTIAL",
                        description="Monthly consulting engagement (bundled)",
                        quantity=None, net="6000.00", total="6000.00")
        value.line_items[0].unit = field(None)
        value.line_items[0].unit_price = field(None)
        result = evaluate(value, source("bundled_charges.pdf"), reference(), ledger())
        self.assertEqual(result.verdict, "needs_review")
        self.assertEqual(checks(result)["line_allocation"], "review")
        self.assertEqual(result.allocations, [])

    def test_policy_freshness_and_admin_required(self):
        ref = reference()
        ref["rules"][0]["auto_accept_enabled"] = False
        result = evaluate(invoice(), source("happy_full.pdf"), ref, ledger())
        self.assertEqual(result.verdict, "eligible")
        self.assertEqual(result.acceptance_mode, "admin_required")
        ref["fresh"] = False
        result = evaluate(invoice(), source("happy_full.pdf"), ref, ledger())
        self.assertEqual(result.verdict, "needs_review")
        self.assertEqual(result.acceptance_mode, "not_allowed")

    def test_missing_number_date_and_po_quantities_are_not_invented(self):
        for name in ("invoice_number", "invoice_date"):
            with self.subTest(name=name):
                value = invoice()
                setattr(value, name, field(None))
                result = evaluate(value, synthetic(value), reference(), ledger())
                self.assertIn(name, result.revision["unresolved_critical_fields"])
                self.assertEqual(result.verdict, "needs_review")
        for quantity in ("0", "-1", "1e1", "10.00001"):
            with self.subTest(quantity=quantity):
                value = invoice(quantity=quantity)
                result = evaluate(value, synthetic(value), reference(), ledger())
                self.assertEqual(checks(result)["line_allocation"], "review")

    def test_duplicate_line_rows_are_aggregated_before_quantity_cap(self):
        value = invoice(po="PO-PARTIAL", description="Consulting services", quantity="6",
                        net="12000.00", total="12000.00")
        value.line_items[0].net_amount = money("6000.00")
        value.line_items.append(value.line_items[0].model_copy(deep=True))
        result = evaluate(value, synthetic(value), reference(), ledger())
        self.assertEqual(len(result.allocations), 1)
        self.assertEqual(result.allocations[0]["quantity"], Decimal(12))
        self.assertEqual(checks(result)["po_balance"], "review")

    def test_review_allocations_never_overflow_database_quantity_precision(self):
        value = invoice(po="PO-PARTIAL", description="Consulting services",
                        quantity="99999999999999.9999", unit="0.00", net="0.00", total="1.00")
        value.line_items.append(value.line_items[0].model_copy(deep=True))
        result = evaluate(value, synthetic(value), reference(), ledger())
        self.assertEqual(result.verdict, "needs_review")
        self.assertEqual(result.allocations, [])
        self.assertIn("precision/range", next(row["detail"] for row in result.checks if row["code"] == "line_allocation"))

    def test_strict_numbers_and_ambiguous_date_are_not_coerced(self):
        for value in ("1e4", "NaN", "10,00.00", "10000.001", "-100.00", "0"):
            with self.subTest(value=value):
                item = invoice()
                item.total_gross = field(value, "TOTAL PAYABLE INR " + value)
                result = evaluate(item, synthetic(item), reference(), ledger())
                self.assertEqual(checks(result)["required_fields"], "review")
                self.assertIsNone(result.revision["total_gross_minor"])
        value = invoice()
        value.invoice_date = field("05/06/2026")
        result = evaluate(value, synthetic(value), reference(), ledger())
        self.assertIsNone(result.revision["invoice_date"])
        self.assertEqual(result.verdict, "needs_review")

    def test_price_currency_closed_po_and_quantity_overrun(self):
        value = invoice(po="PO-PARTIAL", description="Consulting services", unit="900.00", net="9000.00", total="9000.00")
        result = evaluate(value, synthetic(value), reference(), ledger())
        self.assertEqual(checks(result)["line_allocation"], "review")
        value = invoice()
        value.currency = field("USD")
        result = evaluate(value, synthetic(value), reference(), ledger())
        self.assertEqual(checks(result)["currency"], "review")
        ref = reference()
        next(row for row in ref["pos"] if row["po_code"] == "PO-FULL")["status"] = "closed"
        result = evaluate(invoice(), source("happy_full.pdf"), ref, ledger())
        self.assertEqual(checks(result)["po_match"], "review")
        # Quantities cannot exceed authorization even if a corrupted amount ledger
        # would still show sufficient money. SQL rechecks the same independent cap.
        result = evaluate(invoice(), source("happy_full.pdf"), reference(),
                          ledger(accepted_quantities={("PO-FULL", "SERVICE"): Decimal(1)}))
        self.assertEqual(checks(result)["po_balance"], "review")

    def test_tax_inclusive_claim_without_actual_source_words_is_not_authority(self):
        value = invoice(po="PO-TAX", description="Tax advisory services", unit="1180.00",
                        total="11800.00", presentation="inclusive", inclusive=True)
        result = evaluate(value, synthetic(value), reference(), ledger())
        self.assertEqual(checks(result)["line_allocation"], "review")

    def test_omitted_tax_classification_cannot_hide_a_printed_conflicting_rate(self):
        value = invoice()
        result = evaluate(value, synthetic(value, "GST (18%)"), reference(), ledger())
        self.assertEqual(checks(result)["line_allocation"], "review")

    def test_rounding_requires_readable_matching_currency_evidence(self):
        value = invoice(total="9999.50")
        for adjustment in ("", "Rounding adjustment USD -0.50"):
            with self.subTest(adjustment=adjustment):
                result = evaluate(value, synthetic(value, adjustment), reference(), ledger())
                self.assertEqual(checks(result)["arithmetic"], "review")
        doc = synthetic(value, "Rounding adjustment INR -0.50")
        doc.pages[0].method = "ocr"
        doc.pages[0].low_confidence_tokens = ["Rounding"]
        result = evaluate(value, doc, reference(), ledger())
        self.assertEqual(checks(result)["arithmetic"], "review")

    def test_conflicting_rounding_or_ignored_printed_adjustment_needs_review(self):
        for total, printed in [("9999.50", "Rounding adjustment INR -0.50\nRounding adjustment INR -0.75"),
                               ("10000.00", "Rounding adjustment INR -0.50")]:
            with self.subTest(total=total):
                value = invoice(total=total)
                result = evaluate(value, synthetic(value, printed), reference(), ledger())
                self.assertEqual(checks(result)["arithmetic"], "review")


if __name__ == "__main__":
    unittest.main()

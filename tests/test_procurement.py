import copy
import csv
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.procurement import (INPUT_RANGES, ReferenceValidationError, SheetsGateway,
                             SheetsReadError, parse_reference)

SHEETS = Path(__file__).resolve().parent / "reference_data"

@pytest.fixture
def tabs():
    return {name: list(csv.reader((SHEETS / f"{name}.csv").open(newline=""))) for name in INPUT_RANGES}

def assert_invalid(tabs, code):
    with pytest.raises(ReferenceValidationError) as exc:
        parse_reference(tabs)
    assert exc.value.errors[0]["code"] == code

def test_real_csvs_tax_and_exact_minor_units(tabs):
    snapshot = parse_reference(tabs)
    assert len(snapshot.pos) == 8
    tax_line = next(line for line in snapshot.lines if line.po_code == "PO-TAX")
    assert tax_line.tax_rate_bps == 1800
    assert tax_line.unit_net_minor == 100000
    assert tax_line.quantity == Decimal("10.0000")
    assert next(po for po in snapshot.pos if po.po_code == "PO-TAX").authorized_gross_minor == 1180000
    assert snapshot.rules[0].arithmetic_tolerance_minor == 100

def test_hash_ignores_order_blank_rows_and_report_values(tabs):
    before = parse_reference(tabs)
    for name, rows in tabs.items():
        tabs[name] = [rows[0]] + list(reversed(rows[1:])) + [[]]
    tabs["AcceptedInvoices"] = [["PO-FULL", "99999999999999"]]
    assert parse_reference(tabs).source_hash == before.source_hash
    tabs["Vendors"][1][2] = "TRUE"  # V-HOLD was FALSE, source changes must change hash.
    assert parse_reference(tabs).source_hash != before.source_hash

def test_sheet_number_and_boolean_cell_types(tabs):
    tabs["Vendors"][1][2] = True
    tabs["POLines"][1][3:6:2] = [10.0, 1000.0]
    assert parse_reference(tabs).lines

@pytest.mark.parametrize("tab,index,value,code", [
    ("PurchaseOrders", 2, "EUR", "INVALID_VALUE"),
    ("PurchaseOrders", 3, "NaN", "INVALID_NUMBER"),
    ("PurchaseOrders", 3, "10000.001", "INVALID_PRECISION_OR_RANGE"),
    ("PurchaseOrders", 3, "10,000.00", "INVALID_NUMBER"),
    ("PurchaseOrders", 3, "-10000", "INVALID_PRECISION_OR_RANGE"),
    ("PurchaseOrders", 3, True, "INVALID_NUMBER"),
    ("PurchaseOrders", 1, "UNKNOWN", "UNKNOWN_VENDOR"),
    ("Vendors", 2, "yes", "INVALID_BOOLEAN"),
    ("Vendors", 3, "{}", "INVALID_ALIASES"),
    ("Vendors", 3, '["Acme", " acme "]', "DUPLICATE_ALIAS"),
    ("Vendors", 3, '[42]', "INVALID_TEXT"),
    ("POLines", 3, "10.00001", "INVALID_QUANTITY"),
    ("POLines", 3, "1.000000000000000000000000000001", "INVALID_QUANTITY"),
    ("PurchaseOrders", 3, "10000.0000000000000000000000000001", "INVALID_PRECISION_OR_RANGE"),
    ("PurchaseOrders", 3, 9007199254740992, "UNSAFE_NUMERIC_CELL"),
    ("POLines", 3, "0", "INVALID_QUANTITY"),
    ("POLines", 6, "100.01", "INVALID_PRECISION_OR_RANGE"),
    ("Rules", 2, "1.01", "INVALID_PRECISION_OR_RANGE"),
    ("Rules", 3, "0.1", "INVALID_PRECISION_OR_RANGE"),
])
def test_rejects_invalid_cell_values(tabs, tab, index, value, code):
    tabs[tab][1][index] = value
    assert_invalid(tabs, code)

def test_cross_vendor_name_alias_ambiguity(tabs):
    tabs["Vendors"][2][3] = '[" ACME   Services "]'
    assert_invalid(tabs, "AMBIGUOUS_VENDOR_ALIAS")

@pytest.mark.parametrize("name,code", [("Vendors","DUPLICATE_VENDOR"), ("PurchaseOrders","DUPLICATE_PO"),
                                       ("POLines","DUPLICATE_LINE"), ("Rules","DUPLICATE_RULE")])
def test_unique_source_keys(tabs, name, code):
    tabs[name].append(copy.deepcopy(tabs[name][1]))
    assert_invalid(tabs, code)

def test_unknown_po_reference(tabs):
    tabs["POLines"][1][0] = "PO-UNKNOWN"
    assert_invalid(tabs, "UNKNOWN_PO")

def test_rules_must_cover_imported_currencies(tabs):
    tabs["PurchaseOrders"][1][2] = "USD"
    assert_invalid(tabs, "RULES_MISSING")

def test_budget_must_reconcile_with_line_tax(tabs):
    tabs["PurchaseOrders"][1][3] = "11000.00"
    assert_invalid(tabs, "REFERENCE_LINE_TOTAL_MISMATCH")

def test_missing_po_line(tabs):
    del tabs["POLines"][1]
    assert_invalid(tabs, "PO_LINES_MISSING")

def test_tolerance_boundary_is_exact(tabs):
    tabs["PurchaseOrders"][1][3] = "10001.00"
    assert parse_reference(tabs)
    tabs["PurchaseOrders"][1][3] = "10001.01"
    assert_invalid(tabs, "REFERENCE_LINE_TOTAL_MISMATCH")

@pytest.mark.parametrize("mutation,code", [
    (lambda t: t.pop("Rules"), "TAB_MISSING_OR_EMPTY"),
    (lambda t: t["Rules"][0].append("extra"), "INVALID_HEADERS"),
    (lambda t: t["Vendors"][1].append("extra"), "EXTRA_CELLS"),
    (lambda t: t.update({"Unrecognized": []}), "UNEXPECTED_TAB"),
])
def test_required_shape(tabs, mutation, code):
    mutation(tabs)
    assert_invalid(tabs, code)

def mock_sheets(tabs, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = {"valueRanges": [{"range": f"'{name}'!A1:F30", "values": rows}
                                                 for name, rows in tabs.items()]}
    session = MagicMock()
    session.get.return_value = response
    context = MagicMock()
    context.__enter__.return_value = session
    return response, session, context

def test_gateway_reads_only_four_tabs_with_bounded_timeout(tabs):
    response, session, context = mock_sheets(tabs)
    with patch("google.oauth2.service_account.Credentials.from_service_account_file") as load, \
            patch("google.auth.transport.requests.AuthorizedSession", return_value=context):
        result = SheetsGateway("spreadsheet_demo_id", "/not-real/key.json", timeout=12).read_reference()
    assert result == tabs
    assert session.get.call_args.kwargs["timeout"] == 12
    params = session.get.call_args.kwargs["params"]
    assert ("valueRenderOption", "UNFORMATTED_VALUE") in params
    assert len([param for param in params if param[0] == "ranges"]) == 4
    assert all("AcceptedInvoices" not in value for key, value in params)
    load.assert_called_once()

@pytest.mark.parametrize("status", [403,404,429,500])
def test_gateway_sanitizes_http_failures(tabs, status):
    response, session, context = mock_sheets(tabs, status)
    response.text = "secret accidental upstream diagnostic"
    with patch("google.oauth2.service_account.Credentials.from_service_account_file"), \
            patch("google.auth.transport.requests.AuthorizedSession", return_value=context):
        with pytest.raises(SheetsReadError) as exc:
            SheetsGateway("spreadsheet_demo_id", "/private/key.json").read_reference()
    assert "secret" not in str(exc.value)
    assert str(status) in str(exc.value)

def test_gateway_rejects_wrong_tab_order(tabs):
    response, session, context = mock_sheets(tabs)
    response.json.return_value["valueRanges"].reverse()
    with patch("google.oauth2.service_account.Credentials.from_service_account_file"), \
            patch("google.auth.transport.requests.AuthorizedSession", return_value=context):
        with pytest.raises(SheetsReadError, match="tab order"):
            SheetsGateway("spreadsheet_demo_id", "/private/key.json").read_reference()

def test_gateway_does_not_leak_credential_errors():
    with patch("google.oauth2.service_account.Credentials.from_service_account_file",
               side_effect=ValueError("secret private_key contents")):
        with pytest.raises(SheetsReadError) as exc:
            SheetsGateway("spreadsheet_demo_id", "/private/key.json").read_reference()
    assert "secret" not in str(exc.value)

"""Validated, one-way procurement imports; AcceptedInvoices is never an input.

The caller owns the database transaction, role and authenticated actor.  A failed
parse or activation must roll back the whole import, leaving the active snapshot
untouched. No network requests are made inside ``import_reference``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote
from uuid import uuid4

INPUT_RANGES = {name: f"'{name}'!A:Z" for name in
                ("Vendors", "PurchaseOrders", "POLines", "Rules")}
HEADERS = {
    "Vendors": ("vendor_code", "legal_name", "approved", "aliases_json", "tax_registration_id"),
    "PurchaseOrders": ("po_code", "vendor_code", "currency", "authorized_gross", "status", "billing_mode"),
    "POLines": ("po_code", "line_code", "description", "quantity", "unit", "unit_net", "tax_rate_percent"),
    "Rules": ("currency", "auto_accept_enabled", "arithmetic_tolerance", "price_tolerance_bps"),
}
CURRENCIES = frozenset({"INR", "USD"})
BIGINT_MAX = 9223372036854775807
# Keep multiplication within PostgreSQL numeric precision; quantity numeric(18,4).
MAX_QUANTITY = Decimal("99999999999999.9999")


class ReferenceValidationError(ValueError):
    def __init__(self, code: str, location: str, message: str):
        self.errors = [{"code": code, "location": location, "message": message}]
        super().__init__(f"{location}: {message}")


class SheetsReadError(RuntimeError):
    """An intentionally sanitized error: no credentials or API response body."""


@dataclass(frozen=True, slots=True)
class Vendor:
    vendor_code: str
    legal_name: str
    approved: bool
    aliases: tuple[str, ...]
    tax_registration_id: str | None


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    po_code: str
    vendor_code: str
    currency: str
    authorized_gross_minor: int
    status: str
    billing_mode: str


@dataclass(frozen=True, slots=True)
class POLine:
    po_code: str
    line_code: str
    description: str
    quantity: Decimal
    unit: str
    unit_net_minor: int
    tax_rate_bps: int


@dataclass(frozen=True, slots=True)
class Rule:
    currency: str
    auto_accept_enabled: bool
    arithmetic_tolerance_minor: int
    price_tolerance_bps: int


@dataclass(frozen=True, slots=True)
class ReferenceSnapshot:
    source_hash: str
    vendors: tuple[Vendor, ...]
    pos: tuple[PurchaseOrder, ...]
    lines: tuple[POLine, ...]
    rules: tuple[Rule, ...]


def _fail(code: str, location: str, message: str):
    raise ReferenceValidationError(code, location, message)


def _text(value: Any, location: str, *, optional=False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        _fail("INVALID_TEXT", location, "Expected text")
    value = value.strip()
    if not value and not optional:
        _fail("REQUIRED_FIELD", location, "Value is required")
    if len(value) > 2000:
        _fail("INVALID_TEXT", location, "Text exceeds 2000 characters")
    return value


def _number(value: Any, location: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        _fail("INVALID_NUMBER", location, "Expected an unformatted finite decimal")
    if isinstance(value, (int, float)) and abs(value) >= 2 ** 53:
        _fail("UNSAFE_NUMERIC_CELL", location, "Large numeric cells must be stored as decimal text to preserve precision")
    # No locale separators, currency symbols or exponent notation in source cells.
    raw = str(value).strip()
    if len(raw) > 40 or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        _fail("INVALID_NUMBER", location, "Expected an unformatted finite decimal")
    try:
        number = Decimal(raw)
    except InvalidOperation:
        _fail("INVALID_NUMBER", location, "Expected an unformatted finite decimal")
    if not number.is_finite():
        _fail("INVALID_NUMBER", location, "Expected an unformatted finite decimal")
    return number


def _scaled(value: Any, location: str, scale: int, *, maximum=BIGINT_MAX, minimum=0) -> int:
    with localcontext() as context:
        context.prec = 80
        number = _number(value, location) * scale
    if number != number.to_integral_value() or not minimum <= number <= maximum:
        _fail("INVALID_PRECISION_OR_RANGE", location,
              "Value has unsupported precision or is outside the allowed range")
    return int(number)


def _bool(value: Any, location: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip() in ("TRUE", "FALSE"):
        return value.strip() == "TRUE"
    _fail("INVALID_BOOLEAN", location, "Use TRUE or FALSE")


def _choice(value: Any, choices, location: str) -> str:
    text = _text(value, location)
    if text not in choices:
        _fail("INVALID_VALUE", location, f"Expected one of: {', '.join(sorted(choices))}")
    return text


def _identity(value: str) -> str:
    return " ".join(value.casefold().split())


def _rows(tabs, name):
    values = tabs.get(name)
    if not isinstance(values, list) or not values:
        _fail("TAB_MISSING_OR_EMPTY", name, "Required input tab is missing or empty")
    expected = HEADERS[name]
    header = list(values[0]) if isinstance(values[0], list) else []
    while header and header[-1] in ("", None):
        header.pop()
    if tuple(header) != expected:
        _fail("INVALID_HEADERS", name, f"Headers must be exactly {', '.join(expected)}")
    for row_no, raw in enumerate(values[1:], 2):
        location = f"{name}!{row_no}"
        if not isinstance(raw, list):
            _fail("INVALID_ROW", location, "Expected a row of cells")
        if all(cell is None or (isinstance(cell, str) and not cell.strip()) for cell in raw):
            continue
        if any(cell not in ("", None) for cell in raw[len(expected):]):
            _fail("EXTRA_CELLS", location, "Unexpected data after the last defined column")
        cells = raw[:len(expected)] + [""] * max(0, len(expected) - len(raw))
        yield dict(zip(expected, cells)), location


def parse_reference(tabs: dict[str, list[list[Any]]]) -> ReferenceSnapshot:
    """Validate source cells before any staging writes. Fail closed on bad input.

    Input is a Google batchGet result mapped by tab name, or equivalent CSV rows.
    Row order, blank trailing rows, and alias order do not change its identity.
    Only the four named input tabs contribute to the hash or commitments.
    """
    if not isinstance(tabs, dict):
        _fail("INVALID_DATASET", "spreadsheet", "Expected named input tabs")
    unknown = set(tabs) - set(HEADERS) - {"AcceptedInvoices"}
    if unknown:
        _fail("UNEXPECTED_TAB", "spreadsheet", "Unknown input tabs supplied")
    vendors: dict[str, Vendor] = {}
    names: dict[str, str] = {}
    for row, loc in _rows(tabs, "Vendors"):
        code = _text(row["vendor_code"], loc + ".vendor_code")
        if code in vendors:
            _fail("DUPLICATE_VENDOR", loc, "Duplicate vendor code")
        name = _text(row["legal_name"], loc + ".legal_name")
        try:
            aliases = json.loads(_text(row["aliases_json"], loc + ".aliases_json"))
        except (json.JSONDecodeError, TypeError):
            _fail("INVALID_ALIASES", loc, "aliases_json must contain a JSON array of names")
        if not isinstance(aliases, list) or len(aliases) > 100:
            _fail("INVALID_ALIASES", loc, "aliases_json must contain at most 100 names")
        aliases = [_text(alias, loc + ".aliases_json") for alias in aliases]
        keys = [_identity(alias) for alias in aliases]
        if len(set(keys)) != len(keys):
            _fail("DUPLICATE_ALIAS", loc, "A vendor alias is repeated")
        for label in [name] + aliases:
            identity = _identity(label)
            if identity in names and names[identity] != code:
                _fail("AMBIGUOUS_VENDOR_ALIAS", loc, "A legal name or alias identifies multiple vendors")
            names[identity] = code
        vendors[code] = Vendor(code, name, _bool(row["approved"], loc + ".approved"),
                               tuple(sorted(aliases, key=lambda alias: (_identity(alias), alias))),
                               _text(row["tax_registration_id"], loc + ".tax_registration_id", optional=True) or None)
    rules: dict[str, Rule] = {}
    for row, loc in _rows(tabs, "Rules"):
        currency = _choice(row["currency"], CURRENCIES, loc + ".currency")
        if currency in rules:
            _fail("DUPLICATE_RULE", loc, "Duplicate currency rule")
        rules[currency] = Rule(currency, _bool(row["auto_accept_enabled"], loc + ".auto_accept_enabled"),
                              _scaled(row["arithmetic_tolerance"], loc + ".arithmetic_tolerance", 100, maximum=100),
                              _scaled(row["price_tolerance_bps"], loc + ".price_tolerance_bps", 1, maximum=100))
    pos: dict[str, PurchaseOrder] = {}
    for row, loc in _rows(tabs, "PurchaseOrders"):
        code = _text(row["po_code"], loc + ".po_code")
        vendor = _text(row["vendor_code"], loc + ".vendor_code")
        currency = _choice(row["currency"], CURRENCIES, loc + ".currency")
        if code in pos:
            _fail("DUPLICATE_PO", loc, "Duplicate PO code")
        if vendor not in vendors:
            _fail("UNKNOWN_VENDOR", loc, "PO refers to an unknown vendor")
        if currency not in rules:
            _fail("RULES_MISSING", loc, "PO currency has no matching rule")
        pos[code] = PurchaseOrder(code, vendor, currency,
                                 _scaled(row["authorized_gross"], loc + ".authorized_gross", 100, minimum=1),
                                 _choice(row["status"], {"open", "closed"}, loc + ".status"),
                                 _choice(row["billing_mode"], {"full", "partial"}, loc + ".billing_mode"))
    lines: dict[tuple[str, str], POLine] = {}
    totals = {code: 0 for code in pos}
    for row, loc in _rows(tabs, "POLines"):
        po_code = _text(row["po_code"], loc + ".po_code")
        line_code = _text(row["line_code"], loc + ".line_code")
        if po_code not in pos:
            _fail("UNKNOWN_PO", loc, "Line refers to an unknown PO")
        if (po_code, line_code) in lines:
            _fail("DUPLICATE_LINE", loc, "Duplicate line code within PO")
        quantity = _number(row["quantity"], loc + ".quantity")
        with localcontext() as context:
            context.prec = 80
            precise_quantity = quantity * 10000
        if not 0 < quantity <= MAX_QUANTITY or precise_quantity != precise_quantity.to_integral_value():
            _fail("INVALID_QUANTITY", loc, "Quantity must be positive and have at most four decimal places")
        line = POLine(po_code, line_code, _text(row["description"], loc + ".description"), quantity,
                      _text(row["unit"], loc + ".unit"),
                      _scaled(row["unit_net"], loc + ".unit_net", 100),
                      _scaled(row["tax_rate_percent"], loc + ".tax_rate_percent", 100, maximum=10000))
        lines[(po_code, line_code)] = line
        with localcontext() as context:
            context.prec = 80
            net = (quantity * line.unit_net_minor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            tax = (net * line.tax_rate_bps / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        totals[po_code] += int(net + tax)
    if not vendors or not pos or not lines or not rules:
        _fail("REFERENCE_DATASET_EMPTY", "spreadsheet", "Each input tab must contain data")
    for code, po in pos.items():
        if not any(key[0] == code for key in lines):
            _fail("PO_LINES_MISSING", code, "Each PO must have at least one line")
        if abs(totals[code] - po.authorized_gross_minor) > rules[po.currency].arithmetic_tolerance_minor:
            _fail("REFERENCE_LINE_TOTAL_MISMATCH", code, "Authorized gross does not reconcile to line totals and tax")
    canonical = {
        "vendors": [asdict(vendors[key]) for key in sorted(vendors)],
        "pos": [asdict(pos[key]) for key in sorted(pos)],
        "lines": [{**asdict(lines[key]), "quantity": format(lines[key].quantity.quantize(Decimal(".0001")), "f")}
                  for key in sorted(lines)],
        "rules": [asdict(rules[key]) for key in sorted(rules)],
    }
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()
    return ReferenceSnapshot(digest, tuple(vendors[key] for key in sorted(vendors)),
                             tuple(pos[key] for key in sorted(pos)), tuple(lines[key] for key in sorted(lines)),
                             tuple(rules[key] for key in sorted(rules)))


class SheetsGateway:
    def __init__(self, spreadsheet_id: str, credentials_file: str, timeout: float = 20):
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", spreadsheet_id):
            raise ValueError("Invalid Google spreadsheet id")
        if not 0 < timeout <= 60:
            raise ValueError("Sheets timeout must be between zero and 60 seconds")
        self.spreadsheet_id = spreadsheet_id
        self.credentials_file = credentials_file
        self.timeout = timeout

    def read_reference(self) -> dict[str, list[list[Any]]]:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials
        try:
            credentials = Credentials.from_service_account_file(
                self.credentials_file, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            # read_timeout/max_allowed_time also bound token refresh, not only the Sheets request.
            with AuthorizedSession(credentials, refresh_timeout=self.timeout) as session:
                response = session.get(
                    "https://sheets.googleapis.com/v4/spreadsheets/" + quote(self.spreadsheet_id, safe="") + "/values:batchGet",
                    params=[("ranges", value) for value in INPUT_RANGES.values()] +
                           [("valueRenderOption", "UNFORMATTED_VALUE"), ("dateTimeRenderOption", "FORMATTED_STRING")],
                    timeout=self.timeout, max_allowed_time=self.timeout)
                if response.status_code != 200:
                    raise SheetsReadError(f"Google Sheets read failed (HTTP {response.status_code}); check access and tab names")
                payload = response.json()
            ranges = payload.get("valueRanges")
            if not isinstance(ranges, list) or len(ranges) != len(INPUT_RANGES):
                raise SheetsReadError("Google Sheets returned an incomplete batch")
            tabs = {}
            for (name, _), result in zip(INPUT_RANGES.items(), ranges):
                if not isinstance(result, dict) or not isinstance(result.get("values", []), list):
                    raise SheetsReadError("Google Sheets returned invalid tab data")
                returned = result.get("range", "").split("!")[0].strip("'")
                if returned != name:
                    raise SheetsReadError("Google Sheets returned unexpected tab order")
                tabs[name] = result.get("values", [])
            return tabs
        except SheetsReadError:
            raise
        except Exception:
            raise SheetsReadError("Google Sheets read unavailable; check credentials, connectivity and sharing") from None


def import_reference(conn, snapshot: ReferenceSnapshot, spreadsheet_id: str,
                     actor_id: str | None = None, ttl_hours: int = 24) -> str:
    """Stage and activate in caller's restricted transaction; never commit here.

    ``activate_reference`` rechecks existing commitments and serializes against
    acceptance. Exceptions must escape the caller transaction for full rollback.
    ``source_hash`` describes normalized inputs; an import always gets a fresh
    version/expiry even when the sheet content is unchanged.
    """
    from psycopg.types.json import Jsonb
    if not 1 <= ttl_hours <= 168:
        raise ValueError("Reference TTL must be between 1 and 168 hours")
    version_id = str(uuid4())
    imported_at = datetime.now(timezone.utc)
    conn.execute("""INSERT INTO app.reference_versions
        (id,source_spreadsheet_id,source_hash,imported_by,imported_at,valid_until,source_ranges)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (version_id, spreadsheet_id, snapshot.source_hash, actor_id, imported_at,
         imported_at + timedelta(hours=ttl_hours), Jsonb(INPUT_RANGES)))
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO app.po_accounts(po_code,vendor_code,currency)
            VALUES (%s,%s,%s) ON CONFLICT (po_code) DO NOTHING""",
            [(po.po_code, po.vendor_code, po.currency) for po in snapshot.pos])
        cur.executemany("""INSERT INTO app.reference_vendors
            (reference_version_id,vendor_code,legal_name,approved,aliases,tax_registration_id)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            [(version_id, v.vendor_code, v.legal_name, v.approved, Jsonb(list(v.aliases)), v.tax_registration_id)
             for v in snapshot.vendors])
        cur.executemany("""INSERT INTO app.reference_pos
            (reference_version_id,po_code,vendor_code,currency,authorized_gross_minor,status,billing_mode)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            [(version_id, p.po_code, p.vendor_code, p.currency, p.authorized_gross_minor, p.status, p.billing_mode)
             for p in snapshot.pos])
        cur.executemany("""INSERT INTO app.reference_lines
            (reference_version_id,po_code,line_code,description,quantity,unit,unit_net_minor,tax_rate_bps)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(version_id, l.po_code, l.line_code, l.description, l.quantity, l.unit, l.unit_net_minor, l.tax_rate_bps)
             for l in snapshot.lines])
        cur.executemany("""INSERT INTO app.reference_rules
            (reference_version_id,currency,auto_accept_enabled,arithmetic_tolerance_minor,price_tolerance_bps)
            VALUES (%s,%s,%s,%s,%s)""",
            [(version_id, r.currency, r.auto_accept_enabled, r.arithmetic_tolerance_minor, r.price_tolerance_bps)
             for r in snapshot.rules])
    conn.execute("SELECT app.activate_reference(%s,%s)", (version_id, actor_id)).fetchone()
    return version_id

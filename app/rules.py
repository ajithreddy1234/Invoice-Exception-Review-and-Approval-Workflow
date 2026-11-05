"""Pure, deterministic invoice checks. The SQL transaction remains the commit gate.

No network, filename, fixture expectation or model decision is consulted here.
Reference and ledger arguments are a caller-selected consistent database snapshot;
accept_invoice must recheck them while holding the actual PostgreSQL locks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

from app.extraction import DocumentText, InvoiceCandidate, validate_evidence

ENGINE_VERSION = "rules-1.0"
CHECK_CODES = ("required_fields", "vendor_match", "po_match", "source_evidence",
               "duplicate_check", "currency", "arithmetic", "line_allocation", "po_balance")
BIGINT_MAX = 9223372036854775807
MAX_QUANTITY = Decimal("99999999999999.9999")
_MONEY = r"(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d{1,2})?"


@dataclass(frozen=True, slots=True)
class Decision:
    revision: dict
    po_code: str | None
    checks: list[dict]
    allocations: list[dict]
    verdict: str
    acceptance_mode: str
    summary: str
    po_candidates: list


def _identity(value: str | None) -> str:
    # Match the importer's identity normalization, without fuzzy matching or
    # punctuation removal. In particular, invoice numbers retain punctuation.
    return " ".join((value or "").casefold().split())


def _money(value: str | None, currency: str | None, *, positive=False) -> int | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    wrappers = [currency] if currency in {"INR", "USD"} else []
    wrappers += ["₹"] if currency == "INR" else ["$"] if currency == "USD" else []
    for wrapper in wrappers:
        if raw.startswith(wrapper):
            raw = raw[len(wrapper):].strip()
            break
    for wrapper in wrappers:
        if raw.endswith(wrapper):
            raw = raw[:-len(wrapper)].strip()
            break
    if len(raw) > 40 or re.fullmatch(_MONEY, raw) is None:
        return None
    with localcontext() as context:
        context.prec = 80
        minor = Decimal(raw.replace(",", "")) * 100
    if minor != minor.to_integral_value() or not (1 if positive else 0) <= minor <= BIGINT_MAX:
        return None
    return int(minor)


def _quantity(value: str | None) -> Decimal | None:
    if not value or re.fullmatch(r"\d+(?:\.\d{1,4})?", value.strip()) is None or len(value) > 40:
        return None
    number = Decimal(value.strip())
    return number if 0 < number <= MAX_QUANTITY else None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    formats = []
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        formats = ["%Y-%m-%d"]
    elif re.fullmatch(r"\d{1,2} [A-Za-z]{3,9} \d{4}", raw):
        formats = ["%d %b %Y", "%d %B %Y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _rounded(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _display_money(value: int | None, currency: str | None) -> str:
    if value is None:
        return "unreadable amount"
    sign = "-" if value < 0 else ""
    major, minor = divmod(abs(value), 100)
    return f"{currency or 'Unknown currency'} {sign}{major:,}.{minor:02d}"


def _rounding_values(document: DocumentText, currency: str) -> set[int]:
    values = set()
    wrapper = r"(?:INR|₹)" if currency == "INR" else r"(?:USD|\$)"
    pattern = re.compile(r"\brounding(?:\s+adjustment|\s+off)?\s*:?\s*(?:" + wrapper + r")?\s*([+-]?" + _MONEY + r")\s*(?:" + wrapper + r")?\s*$", re.I)
    for page in document.pages:
        for line in page.text.splitlines():
            if not _line_readable(page, line):
                continue
            match = pattern.search(line)
            if match:
                raw = match[1]
                value = _money(raw.lstrip("+-"), currency)
                if value is not None:
                    values.add(-value if raw.startswith("-") else value)
    return values


def _line_readable(page, line: str) -> bool:
    normalized = _identity(line)
    return not any(re.search(r"(?<!\w)" + re.escape(_identity(token).strip(".,:;()")) + r"(?!\w)", normalized)
                   for token in page.low_confidence_tokens if _identity(token).strip(".,:;()"))


def _printed_tax_rates(document: DocumentText) -> set[int]:
    rates = set()
    for page in document.pages:
        for line in page.text.splitlines():
            matches = re.findall(r"\b(?:GST|VAT|tax)\s*(?:rate\s*)?[:(]?\s*(\d{1,3}(?:\.\d{1,2})?)\s*%", line, re.I)
            matches += re.findall(r"(?<![\d.])(\d{1,3}(?:\.\d{1,2})?)\s*%\s*(?:GST|VAT|tax)\b", line, re.I)
            for raw in matches:
                rates.add(int(Decimal(raw) * 100))
    return rates


def _inclusive_rates(document: DocumentText) -> set[int]:
    rates = set()
    # Require a tax-inclusion statement containing the printed rate. A model's
    # classification alone is insufficient grounds for deriving net/tax from PO.
    for page in document.pages:
        for line in page.text.splitlines():
            if not _line_readable(page, line):
                continue
            if not re.search(r"\b(?:include[ds]?|inclusive)\b", line, re.I):
                continue
            if not re.search(r"\b(?:GST|VAT|tax)\b", line, re.I):
                continue
            for raw in re.findall(r"(?<![\d.])(\d{1,3}(?:\.\d{1,2})?)\s*%", line):
                bps = Decimal(raw) * 100
                if 0 <= bps <= 10000:
                    rates.add(int(bps))
    return rates


def evaluate(candidate: InvoiceCandidate, document: DocumentText,
             reference: dict, ledger: dict, *, selected_po: str | None = None) -> Decision:
    """Evaluate an extraction, preserving source and derived-field distinctions.

    ``reference`` rows use schema.sql column names. ``ledger`` contains accepted
    amounts by PO, Decimal quantities by (PO,line), and a boolean duplicate flag.
    Dates deliberately support ISO and textual months only; ambiguous numeric
    dates, unsupported currencies, unknown layouts or allocations require review.
    """
    with localcontext() as context:
        context.prec = 80
        return _evaluate(candidate, document, reference, ledger, selected_po)


def _evaluate(candidate, document, reference, ledger, selected_po=None):
    check_map = {}

    def check(code, passed, detail):
        check_map[code] = {"code": code, "status": "pass" if passed else "review", "detail": detail}

    currency_raw = (candidate.currency.value or "").strip()
    currency = currency_raw if currency_raw in {"INR", "USD"} else None
    invoice_date = _date(candidate.invoice_date.value)
    total = _money(candidate.total_gross.value, currency, positive=True)
    subtotal = _money(candidate.subtotal_net.value, currency)
    tax = _money(candidate.tax_amount.value, currency)
    number = " ".join((candidate.invoice_number.value or "").split()) or None
    missing = []
    if not number:
        missing.append("invoice_number")
    if not invoice_date:
        missing.append("invoice_date")
    if not (candidate.vendor_name.value or "").strip():
        missing.append("vendor_name")
    if not currency:
        missing.append("currency")
    if total is None:
        missing.append("total_gross")
    for name, parsed in [("subtotal_net", subtotal), ("tax_amount", tax)]:
        if getattr(candidate, name).value is not None and parsed is None:
            missing.append(name)
    if candidate.tax_presentation == "unclear":
        missing.append("tax_presentation")
    fresh = reference.get("fresh") is True and bool(reference.get("id"))
    check("required_fields", not missing and fresh,
          "Required fields parse correctly and reference is current." if not missing and fresh
          else ("Unresolved fields: " + ", ".join(missing) + ". " if missing else "")
          + ("Reference snapshot is stale or missing; refresh before any acceptance." if not fresh else ""))

    evidence_issues = validate_evidence(candidate, document)
    check("source_evidence", not evidence_issues,
          "Every extracted field is supported by page text; payable evidence is readable."
          if not evidence_issues else "; ".join(f"{item.field}: {item.code}" for item in evidence_issues))

    vendor_candidates = [row for row in reference.get("vendors", [])
                         if _identity(candidate.vendor_name.value) in
                         {_identity(row["legal_name"]), *(_identity(alias) for alias in row.get("aliases", []))}]
    vendor = vendor_candidates[0] if len(vendor_candidates) == 1 else None
    approved_vendor = vendor is not None and vendor.get("approved") is True
    check("vendor_match", approved_vendor,
          f"Exact approved legal-name/alias match: {vendor['vendor_code']}." if approved_vendor else
          "Vendor is unknown, ambiguous or unapproved; no fuzzy automatic match.")

    po_candidates = []
    explicit = (candidate.po_reference.value or "").strip()
    if explicit:
        found = [row for row in reference.get("pos", []) if _identity(row["po_code"]) == _identity(explicit)]
        for row in found:
            po_candidates.append({"po_code": row["po_code"], "reason": "Explicit invoice PO reference."})
    else:
        found = []
        invoice_shapes = [(_identity(line.description.value), _identity(line.unit.value))
                          for line in candidate.line_items]
        if approved_vendor and invoice_shapes and all(all(shape) for shape in invoice_shapes):
            for row in reference.get("pos", []):
                if row["vendor_code"] != vendor["vendor_code"] or row["currency"] != currency or row["status"] != "open":
                    continue
                allowed = [line for line in reference.get("lines", []) if line["po_code"] == row["po_code"]]
                if all(sum((_identity(line["description"]), _identity(line["unit"])) == shape
                           for line in allowed) == 1 for shape in invoice_shapes):
                    found.append(row)
                    po_candidates.append({"po_code": row["po_code"],
                                          "reason": "Exact vendor, currency, open status and line description/unit match."})
    # Human selection may only disambiguate exact inferred candidates. It cannot
    # contradict a printed PO or introduce an arbitrary/unmatched purchase order.
    selected = [row for row in found if row['po_code']==selected_po] if not explicit and selected_po else []
    po = selected[0] if len(found)>1 and len(selected)==1 else found[0] if len(found)==1 and (not selected_po or selected_po==found[0]['po_code']) else None
    po_valid = bool(po and approved_vendor and po["vendor_code"] == vendor["vendor_code"] and po["status"] == "open")
    check("po_match", po_valid,
          f"Unique open PO {po['po_code']} belongs to the matched vendor." if po_valid else
          ("Several exact PO candidates require a reasoned admin selection." if len(found) > 1
           else "No unique, open PO belonging to the approved vendor was matched."))

    duplicate = ledger.get("duplicate") is True
    check("duplicate_check", not duplicate,
          "No accepted file hash or vendor/invoice identity was found." if not duplicate else
          "An accepted file or vendor/invoice identity already exists; no second commitment.")
    if duplicate:
        check_map["duplicate_check"]["status"] = "fail"
    matching_rules = [row for row in reference.get("rules", []) if row["currency"] == currency]
    rule = matching_rules[0] if len(matching_rules) == 1 else None
    currency_valid = bool(currency and po and po["currency"] == currency and rule)
    check("currency", currency_valid,
          f"Invoice and PO use {currency}; an explicit rule exists." if currency_valid else
          "Currency is unsupported, differs from PO, or has no unique rule; no FX conversion.")
    tolerance = int(rule["arithmetic_tolerance_minor"]) if rule else 0
    price_bps = int(rule["price_tolerance_bps"]) if rule else 0
    allocation_errors = []
    arithmetic_errors = []
    allocations_by_code = {}
    inclusive_rates = _inclusive_rates(document)
    allowed_lines = [row for row in reference.get("lines", []) if po and row["po_code"] == po["po_code"]]
    if not po_valid or not rule:
        allocation_errors.append("A valid PO and currency rule are needed before allocating charges.")
    if not candidate.line_items:
        allocation_errors.append("No supported invoice line quantities/prices were supplied.")
    source_rates = _printed_tax_rates(document)
    for index, line in enumerate(candidate.line_items):
        prefix = f"Line {index + 1}"
        matches = [row for row in allowed_lines if
                   _identity(row["description"]) == _identity(line.description.value) and
                   _identity(row["unit"]) == _identity(line.unit.value)]
        quantity = _quantity(line.quantity.value)
        unit = _money(line.unit_price.value, currency)
        printed_net = _money(line.net_amount.value, currency)
        printed_tax = _money(line.tax_amount.value, currency)
        printed_gross = _money(line.gross_amount.value, currency)
        if len(matches) != 1 or quantity is None or unit is None:
            allocation_errors.append(f"{prefix}: unique exact description/unit, positive quantity and printed unit price are required; bundled charges cannot invent quantities.")
            continue
        if any(getattr(line, name).value is not None and parsed is None for name, parsed in
               [("net_amount", printed_net), ("tax_amount", printed_tax), ("gross_amount", printed_gross)]):
            allocation_errors.append(f"{prefix}: a printed monetary field has unsupported precision, format or range.")
            continue
        ref = matches[0]
        rate = int(ref["tax_rate_bps"])
        expected_net = _rounded(quantity * int(ref["unit_net_minor"]))
        price_allowance = _rounded(Decimal(expected_net) * price_bps / 10000)
        if candidate.tax_presentation == "inclusive":
            if rate not in inclusive_rates:
                allocation_errors.append(f"{prefix}: tax-inclusive wording and the applicable printed rate must be evidenced.")
                continue
            gross = printed_gross if printed_gross is not None else _rounded(quantity * unit)
            if gross != _rounded(quantity * unit):
                allocation_errors.append(f"{prefix}: gross line amount differs from quantity times gross unit price.")
                continue
            net = _rounded(Decimal(gross) * 10000 / (10000 + rate))
            line_tax = gross - net
            if printed_net is not None and printed_net != net:
                allocation_errors.append(f"{prefix}: separately printed net conflicts with inclusive amounts.")
            if printed_tax is not None and printed_tax != line_tax:
                allocation_errors.append(f"{prefix}: separately printed tax conflicts with inclusive amounts.")
        else:
            net = printed_net if printed_net is not None else _rounded(quantity * unit)
            if net != _rounded(quantity * unit):
                allocation_errors.append(f"{prefix}: printed net does not equal supported quantity times unit price.")
            if candidate.tax_presentation == "none" and rate != 0:
                allocation_errors.append(f"{prefix}: source says no tax while the PO authorizes a taxable line.")
            line_tax = printed_tax if printed_tax is not None else _rounded(Decimal(net) * rate / 10000)
            gross = net + line_tax
            if printed_gross is not None and printed_gross != gross:
                allocation_errors.append(f"{prefix}: gross does not equal net plus tax.")
        if abs(net - expected_net) > price_allowance:
            allocation_errors.append(f"{prefix}: price differs from authorized PO rate beyond its tolerance.")
        if abs(line_tax - _rounded(Decimal(net) * rate / 10000)) > tolerance:
            allocation_errors.append(f"{prefix}: tax differs from authorized rate beyond arithmetic tolerance.")
        if any(value < 0 or value > BIGINT_MAX for value in (net, line_tax, gross)):
            allocation_errors.append(f"{prefix}: allocation amounts are outside supported positive-charge range.")
            continue
        code = ref["line_code"]
        allocation = allocations_by_code.setdefault(code, {"line_code": code, "quantity": Decimal(0),
                                                           "net_minor": 0, "tax_minor": 0, "gross_minor": 0})
        allocation["quantity"] += quantity
        allocation["net_minor"] += net
        allocation["tax_minor"] += line_tax
        allocation["gross_minor"] += gross
    # A review decision is persisted too. Do not hand the caller allocations that
    # would overflow numeric(18,4)/bigint and turn a useful review into a SQL error.
    persisted_allocations = []
    for allocation in allocations_by_code.values():
        if allocation["quantity"] > MAX_QUANTITY or any(allocation[key] > BIGINT_MAX for key in
                                                       ("net_minor", "tax_minor", "gross_minor")):
            allocation_errors.append("Combined line allocation exceeds database precision/range.")
        else:
            persisted_allocations.append(allocation)
    allocations = sorted(persisted_allocations, key=lambda row: row["line_code"])
    allocated_rates = {row["tax_rate_bps"] for row in allowed_lines
                       if row["line_code"] in allocations_by_code}
    if source_rates - allocated_rates:
        allocation_errors.append("A printed tax rate conflicts with the rates of the allocated PO lines.")
    for allocation in allocations:
        ref = next(row for row in allowed_lines if row["line_code"] == allocation["line_code"])
        expected_net = _rounded(allocation["quantity"] * int(ref["unit_net_minor"]))
        if abs(allocation["net_minor"] - expected_net) > _rounded(Decimal(expected_net) * price_bps / 10000):
            allocation_errors.append("Combined source rows differ from the PO line's rounded authorized net.")
        if abs(allocation["tax_minor"] - _rounded(Decimal(allocation["net_minor"]) * ref["tax_rate_bps"] / 10000)) > tolerance:
            allocation_errors.append("Combined source rows differ from the PO line's rounded authorized tax.")
    check("line_allocation", not allocation_errors,
          "Source quantities, units, prices and tax reconcile to exact PO lines; inclusive derivations are explicit."
          if not allocation_errors else "; ".join(allocation_errors))

    net_sum = sum(row["net_minor"] for row in allocations)
    tax_sum = sum(row["tax_minor"] for row in allocations)
    gross_sum = sum(row["gross_minor"] for row in allocations)
    if not allocations or not rule or total is None:
        arithmetic_errors.append("Readable total, supported allocations and currency rules are required.")
    else:
        difference = total - gross_sum
        rounding = _rounding_values(document, currency)
        if abs(difference) > tolerance:
            arithmetic_errors.append("Printed payable differs from allocated gross beyond arithmetic tolerance.")
        elif (difference or rounding) and rounding != {difference}:
            arithmetic_errors.append("Payable adjustment requires one unique, matching printed rounding adjustment; conflicting adjustments need review.")
        if subtotal is not None and subtotal != net_sum:
            arithmetic_errors.append("Printed subtotal does not equal the supported line net sum.")
        if tax is not None and tax != tax_sum:
            arithmetic_errors.append("Printed tax does not equal the supported line tax sum.")
        if candidate.tax_presentation == "exclusive" and tax is None and any(row.tax_amount.value is None for row in candidate.line_items):
            arithmetic_errors.append("Exclusive tax requires printed total tax or tax on each line.")
        if candidate.tax_presentation == "unclear":
            arithmetic_errors.append("Tax presentation is unclear.")
    check("arithmetic", not arithmetic_errors,
          f"Allocated net {_display_money(net_sum, currency)} + tax {_display_money(tax_sum, currency)} = gross {_display_money(gross_sum, currency)}; payable {_display_money(total, currency)}; tolerance {_display_money(tolerance, currency)}."
          if not arithmetic_errors else "; ".join(arithmetic_errors))

    balance_errors = []
    if not po_valid or total is None or not rule:
        balance_errors.append("No valid PO, rule and readable payable for a balance decision.")
    else:
        used = int(ledger.get("accepted_amounts", {}).get(po["po_code"], 0))
        remaining = po["authorized_gross_minor"] - used
        if total > remaining:
            balance_errors.append(f"Payable exceeds remaining PO balance by {_display_money(total - remaining, currency)}; rounding cannot raise the hard cap.")
        if po["billing_mode"] == "full" and (used != 0 or abs(total - po["authorized_gross_minor"]) > tolerance):
            balance_errors.append("Full-billing PO requires its full authorized amount within tolerance and no prior acceptance.")
        for allocation in allocations:
            ref = next(row for row in allowed_lines if row["line_code"] == allocation["line_code"])
            used_qty = Decimal(ledger.get("accepted_quantities", {}).get((po["po_code"], allocation["line_code"]), 0))
            if used_qty + allocation["quantity"] > Decimal(ref["quantity"]):
                balance_errors.append(f"Line {allocation['line_code']} exceeds its remaining authorized quantity.")
    check("po_balance", not balance_errors,
          "Payable and cumulative quantities fit current commitments; final SQL lock will recheck."
          if not balance_errors else "; ".join(balance_errors))
    all_pass = all(check_map[code]["status"] == "pass" for code in CHECK_CODES)
    verdict = "eligible" if all_pass else "blocked" if duplicate else "needs_review"
    mode = ("automatic" if rule["auto_accept_enabled"] else "admin_required") if all_pass else "not_allowed"
    if all_pass:
        summary = "All nine checks pass. " + ("Ready for atomic automatic acceptance." if mode == "automatic" else "Policy requires an administrator to accept.")
    else:
        failed = [code for code in CHECK_CODES if check_map[code]["status"] != "pass"]
        summary = ("Already processed; no second acceptance. " if duplicate else "Needs verification; no acceptance. ") + "Check: " + ", ".join(failed) + "."
    unresolved = sorted(set(missing + [item.field for item in evidence_issues]))
    revision = {
        "invoice_number": number, "invoice_date": invoice_date,
        "vendor_name": candidate.vendor_name.value, "po_reference": candidate.po_reference.value,
        "currency": currency, "subtotal_net_minor": subtotal, "tax_minor": tax,
        "total_gross_minor": total, "tax_presentation": candidate.tax_presentation,
        "line_items": [line.model_dump(mode="json") for line in candidate.line_items],
        "evidence": {"candidate": candidate.model_dump(mode="json"), "document": document.model_dump(mode="json"),
                     "issues": [item.model_dump(mode="json") for item in evidence_issues],
                     "derived_allocation": {"net_minor": net_sum, "tax_minor": tax_sum,
                                            "gross_minor": gross_sum,
                                            "basis": "Supported invoice quantities/unit prices and exact PO tax basis; never an inferred payable."}},
        "unresolved_critical_fields": unresolved,
    }
    return Decision(revision, po["po_code"] if po else None,
                    [check_map[code] for code in CHECK_CODES], allocations, verdict, mode, summary, po_candidates)

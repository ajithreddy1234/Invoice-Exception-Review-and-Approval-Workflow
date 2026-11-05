export const CHECKS = [
  ["required_fields", "Required information"],
  ["vendor_match", "Approved vendor"],
  ["po_match", "Purchase order match"],
  ["source_evidence", "Source evidence"],
  ["duplicate_check", "Duplicate protection"],
  ["currency", "Currency"],
  ["arithmetic", "Amounts and tax"],
  ["line_allocation", "Line quantities and prices"],
  ["po_balance", "Remaining PO balance"],
];

export const FIELD_NAMES = {
  vendor_name: "Vendor",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  po_reference: "PO reference",
  currency: "Currency",
  subtotal_net: "Net subtotal",
  tax_amount: "Tax amount",
  total_gross: "Total payable",
};

export function human(value) {
  if (value === null || value === undefined || value === "")
    return "Not available";
  return String(value)
    .replace(/[_.]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function activeRun(data) {
  return (
    ["received", "processing"].includes(data?.submission?.status) ||
    ["queued", "running", "leased", "pending"].includes(data?.run?.state)
  );
}

export function canAdminAccept(user, data) {
  if (user?.role !== "admin" || !data?.validation || data.acceptance)
    return false;
  if (!["needs_review", "reference_hold"].includes(data.submission?.status))
    return false;
  if (
    data.validation.verdict !== "eligible" ||
    data.validation.acceptance_mode !== "admin_required"
  )
    return false;
  if (
    data.reference &&
    (data.reference.fresh === false || data.reference.is_active === false)
  )
    return false;
  const checks = data.validation.checks;
  return (
    Array.isArray(checks) &&
    checks.length === CHECKS.length &&
    checks.every((check) => check.status === "pass") &&
    CHECKS.every(
      ([code]) =>
        checks.filter((check) => check.code === code && check.status === "pass")
          .length === 1,
    )
  );
}

export function publicationLabel(status, accepted) {
  if (!accepted) return "No accepted record";
  if (status === "published") return "Published to spreadsheet";
  if (status === "failed") return "Spreadsheet update failed";
  if (status === "reconciliation_required")
    return "Spreadsheet reconciliation required";
  return "Spreadsheet update pending";
}

export function evidenceFields(revision) {
  const candidate = revision?.evidence?.candidate || revision?.candidate;
  if (!candidate || typeof candidate !== "object") return [];
  return Object.entries(FIELD_NAMES).map(([key, label]) => ({
    key,
    label,
    value: candidate[key]?.value ?? null,
    source: candidate[key]?.source ?? null,
  }));
}

export function fileDuplicateProof(data) {
  if (
    data?.submission?.status !== "blocked_duplicate" ||
    data.validation ||
    data.revision
  )
    return null;
  const event = data.audit?.find(
    (item) =>
      item.event_type === "invoice.duplicate_blocked" &&
      typeof item.details?.acceptance_id === "string" &&
      item.details.acceptance_id,
  );
  return event
    ? {
        acceptanceId: event.details.acceptance_id,
        fileHash: data.submission.file_sha256 || null,
      }
    : null;
}

export function readableError(
  payload,
  fallback = "The request could not be completed.",
) {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail.replaceAll("_", " ");
  if (Array.isArray(detail))
    return detail.map((item) => item.msg || "Invalid input").join(". ");
  if (detail?.code === "CORRECTION_SOURCE_NOT_SUPPORTED")
    return (
      "Correction not saved. " +
      (detail.issues || [])
        .map((i) => `${FIELD_NAMES[i.field] || human(i.field)}: ${i.detail}`)
        .join(" ")
    );
  if (detail && typeof detail === "object")
    return String(detail.message || detail.code || fallback).replaceAll(
      "_",
      " ",
    );
  return fallback;
}

export function uploadError(file) {
  if (!file) return "Choose an invoice first.";
  if (file.size === 0) return "The selected file is empty.";
  if (file.size > 5 * 1024 * 1024)
    return "Choose a file smaller than or equal to 5 MiB.";
  if (!/\.(pdf|jpe?g|png)$/i.test(file.name))
    return "Choose a PDF, JPEG or PNG invoice.";
  return null;
}

export function parseRoute(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const [part, id] = raw.split("/");
  const page = ["dashboard", "upload", "invoices", "guide"].includes(part)
    ? part
    : "upload";
  return {
    page,
    invoiceId:
      page === "invoices" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id || "",
      )
        ? id
        : null,
  };
}
export function filterInvoices(
  items,
  { status = "all", vendor = "all", search = "" } = {},
) {
  return items.filter(
    (item) =>
      (status === "all" ||
        item.status === status ||
        (status === "review_queue" &&
          ["needs_review", "reference_hold"].includes(item.status))) &&
      (vendor === "all" || (item.vendor_code || "unmatched") === vendor) &&
      [
        item.original_filename,
        item.invoice_number,
        item.vendor_name,
        item.po_code,
      ]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
}
export function decisionSummary(data) {
  if (data.acceptance) return "Acceptance is recorded.";
  const providerErrors = {
    EXTRACTION_PROVIDER_BUSY: "The extraction service is temporarily busy. One retry was attempted; no invoice was accepted. Try again later.",
    EXTRACTION_RATE_LIMITED: "The extraction service has reached its request limit. One retry was attempted; no invoice was accepted. Try again when capacity is available.",
    EXTRACTION_TIMEOUT: "The extraction service timed out after one retry. No invoice was accepted. You can rerun verification.",
  };
  if (providerErrors[data.run?.error_code]) return providerErrors[data.run.error_code];
  const failed = (data.validation?.checks || [])
    .filter((c) => c.status !== "pass")
    .map((c) => CHECKS.find(([code]) => code === c.code)?.[1] || human(c.code));
  if (!data.validation)
    return data.run?.error_code
      ? "Processing could not finish. Review the error and retry."
      : "Verification is in progress.";
  return failed.length
    ? `Needs attention: ${failed.join(", ")}.`
    : data.validation.acceptance_mode === "admin_required"
      ? "All checks passed. An administrator can now approve this invoice."
      : "All checks passed; acceptance will recheck current balances.";
}

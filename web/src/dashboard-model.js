export const money = (minor, currency = "INR") =>
  minor == null
    ? "Not available"
    : !currency
      ? `${(Number(minor) / 100).toFixed(2)} · currency unknown`
      : new Intl.NumberFormat("en-IN", {
          style: "currency",
          currency,
          maximumFractionDigits: 2,
        }).format(Number(minor) / 100);
export function dashboardView(workspace, vendor, currency) {
  const match = (r) =>
    vendor === "all" || (r.vendor_code || "unmatched") === vendor;
  const groups = (workspace?.company_totals || []).filter(
    (r) => match(r) && (r.currency === currency || !r.currency),
  );
  const sum = (k) => groups.reduce((n, r) => n + Number(r[k] || 0), 0);
  const timing = (workspace?.timing_groups || []).find(
    (r) =>
      r.currency === currency &&
      (vendor === "all"
        ? r.all_vendors === true
        : !r.all_vendors && (r.vendor_code || "unmatched") === vendor),
  );
  const vendors = [
    ...(workspace?.vendors || []),
    ...((workspace?.company_totals || []).some((r) => !r.vendor_code)
      ? [
          {
            vendor_code: "unmatched",
            legal_name: "Unmatched vendor",
            approved: null,
          },
        ]
      : []),
  ];
  const companies = vendors
    .filter((v) => vendor === "all" || v.vendor_code === vendor)
    .map((v) => {
      const rows = groups.filter(
        (r) => (r.vendor_code || "unmatched") === v.vendor_code,
      );
      return {
        ...v,
        invoice_count: rows.reduce((n, r) => n + Number(r.invoice_count), 0),
        accepted_minor: rows.reduce(
          (n, r) =>
            n + (r.currency === currency ? Number(r.accepted_minor) : 0),
          0,
        ),
        review_count: rows.reduce((n, r) => n + Number(r.review_count), 0),
      };
    })
    .sort(
      (a, b) =>
        b.accepted_minor - a.accepted_minor ||
        a.legal_name.localeCompare(b.legal_name),
    );
  return {
    invoice_count: sum("invoice_count"),
    accepted_count: sum("accepted_count"),
    review_count: sum("review_count"),
    duplicate_count: sum("duplicate_count"),
    rejected_count: sum("rejected_count"),
    failed_count: sum("failed_count"),
    expired_count: sum("expired_count"),
    processing_count: sum("processing_count"),
    outcome_count: sum("outcome_count"),
    straight_through_count: sum("straight_through_count"),
    straight_through_percent: sum("outcome_count")
      ? (100 * sum("straight_through_count")) / sum("outcome_count")
      : null,
    median_processing_seconds: timing?.median_seconds ?? null,
    timing_sample_count: Number(timing?.sample_count || 0),
    publication_pending_count: sum("publication_pending_count"),
    accepted_minor: groups
      .filter((r) => r.currency === currency)
      .reduce((n, r) => n + Number(r.accepted_minor || 0), 0),
    review_minor: groups
      .filter((r) => r.currency === currency)
      .reduce((n, r) => n + Number(r.review_minor || 0), 0),
    unreadable_amount_count: sum("unreadable_amount_count"),
    companies,
    po: (workspace?.po_balances || []).filter(
      (r) => match(r) && r.currency === currency,
    ),
    daily: (workspace?.daily || []).filter(
      (r) => match(r) && (r.currency === currency || !r.currency),
    ),
  };
}

import test from "node:test";
import assert from "node:assert/strict";
import { dashboardView } from "./dashboard-model.js";
import { revisionChanges } from "./revision-history-model.js";
import { reviewGuidance } from "./review-guidance.js";

test("filtered timing uses a database aggregate, not median of vendor medians", () => {
  const w = {
    company_totals: [
      {
        vendor_code: "A",
        currency: "INR",
        outcome_count: 2,
        straight_through_count: 1,
      },
      {
        vendor_code: "B",
        currency: "INR",
        outcome_count: 1,
        straight_through_count: 1,
      },
    ],
    timing_groups: [
      {
        all_vendors: true,
        vendor_code: null,
        currency: "INR",
        sample_count: 3,
        median_seconds: 9,
      },
      {
        all_vendors: false,
        vendor_code: "A",
        currency: "INR",
        sample_count: 2,
        median_seconds: 50.5,
      },
      {
        all_vendors: false,
        vendor_code: "B",
        currency: "INR",
        sample_count: 1,
        median_seconds: 9,
      },
    ],
  };
  assert.equal(dashboardView(w, "all", "INR").median_processing_seconds, 9);
  assert.equal(dashboardView(w, "A", "INR").median_processing_seconds, 50.5);
  assert.equal(dashboardView(w, "A", "INR").straight_through_percent, 50);
  assert.equal(dashboardView(w, "all", "USD").median_processing_seconds, null);
  assert.equal(dashboardView({}, "all", "INR").straight_through_percent, null);
});

test("outcome mix keeps rejected, failed, expired and running distinct", () => {
  const w = {
    company_totals: [
      {
        currency: "INR",
        rejected_count: 3,
        failed_count: 2,
        expired_count: 1,
        processing_count: 4,
      },
    ],
  };
  const v = dashboardView(w, "all", "INR");
  assert.equal(v.rejected_count, 3);
  assert.equal(v.failed_count, 2);
  assert.equal(v.expired_count, 1);
  assert.equal(v.processing_count, 4);
});

test("revision comparison preserves null fields and source wording independently of mappings", () => {
  const previous = {
    vendor_name: {
      value: "Original supplier",
      source: { page: 1, quote: "Original supplier" },
    },
    total_gross: { value: null, source: null },
  };
  const current = structuredClone(previous);
  current.vendor_name = {
    value: "Correct supplier",
    source: { page: 2, quote: "Correct supplier" },
  };
  const diff = revisionChanges(previous, current);
  assert.equal(diff.length, 1);
  assert.equal(diff[0].before, "Original supplier");
  assert.equal(diff[0].after, "Correct supplier");
  assert.equal(diff[0].source.page, 2);
  assert.equal(revisionChanges(current, structuredClone(current)).length, 0);
  current.total_gross = {
    value: "1000.00",
    source: { page: 1, quote: "TOTAL PAYABLE INR 1000.00" },
  };
  const total = revisionChanges(previous, current).find(
    (row) => row.key === "total_gross",
  );
  assert.equal(total.before, null);
  assert.equal(total.after, "1000.00");
});

test("citation-only review preserves both source versions", () => {
  const previous = {
    invoice_number: { value: "INV-1", source: { page: 1, quote: "INV-1" } },
  };
  const current = structuredClone(previous);
  current.invoice_number.source = { page: 2, quote: "Invoice number INV-1" };
  const [row] = revisionChanges(previous, current);
  assert.equal(row.before, row.after);
  assert.deepEqual(row.before_source, previous.invoice_number.source);
  assert.deepEqual(row.after_source, current.invoice_number.source);
  assert.equal(previous.invoice_number.source.page, 1);
});

test("unreadable payable guidance cannot be mistaken for an amendable PO cap", () => {
  const data = {
    submission: { status: "needs_review" },
    decision: {
      reason_code: "PAYABLE_MISSING",
      primary_reason: "The payable total is unreadable.",
      next_action: "Request a clearer original; do not infer the total.",
    },
    validation: {
      checks: [
        { code: "po_match", status: "pass" },
        { code: "po_balance", status: "review" },
        { code: "required_fields", status: "review" },
      ],
    },
  };
  assert.match(reviewGuidance(data, "admin").message, /clearer original/);
  delete data.decision;
  assert.equal(reviewGuidance(data, "admin"), null);
});

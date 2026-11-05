import test from "node:test";
import assert from "node:assert/strict";
import { dashboardView, money } from "./dashboard-model.js";
const workspace = {
  vendors: [
    { vendor_code: "A", legal_name: "Alpha" },
    { vendor_code: "B", legal_name: "Beta" },
  ],
  company_totals: [
    {
      vendor_code: "A",
      currency: "INR",
      invoice_count: 4,
      accepted_count: 1,
      review_count: 1,
      duplicate_count: 2,
      accepted_minor: 600000,
      review_minor: 450000,
      unreadable_amount_count: 0,
    },
    {
      vendor_code: "A",
      currency: "USD",
      invoice_count: 1,
      accepted_count: 1,
      accepted_minor: 20000,
    },
    {
      vendor_code: null,
      currency: null,
      invoice_count: 1,
      review_count: 1,
      accepted_minor: 0,
      review_minor: 999,
      unreadable_amount_count: 1,
    },
  ],
  po_balances: [
    { vendor_code: "A", currency: "INR", remaining_minor: 400000 },
    { vendor_code: "A", currency: "USD", remaining_minor: 10000 },
  ],
  daily: [],
};
test("dashboard never mixes currencies or treats a review/duplicate amount as accepted", () => {
  const v = dashboardView(workspace, "all", "INR");
  assert.equal(v.accepted_minor, 600000);
  assert.equal(v.review_minor, 450000);
  assert.equal(v.invoice_count, 5);
  assert.equal(v.review_count, 2);
  assert.equal(v.duplicate_count, 2);
  assert.equal(v.unreadable_amount_count, 1);
  assert.equal(v.po.length, 1);
});
test("vendor drilldown filters counts, money and PO rows while keeping zero-value companies", () => {
  const v = dashboardView(workspace, "B", "INR");
  assert.equal(v.accepted_minor, 0);
  assert.equal(v.invoice_count, 0);
  assert.equal(v.companies.length, 1);
  assert.equal(v.companies[0].legal_name, "Beta");
  assert.equal(v.po.length, 0);
});
test("missing total and missing currency are not silently presented as INR", () => {
  assert.equal(money(null, "INR"), "Not available");
  assert.match(money(10000, null), /currency unknown/);
  assert.doesNotMatch(money(10000, null), /₹/);
});

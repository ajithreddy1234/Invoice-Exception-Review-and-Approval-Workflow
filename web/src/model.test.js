import test from "node:test";
import assert from "node:assert/strict";
import {
  CHECKS,
  canAdminAccept,
  publicationLabel,
  evidenceFields,
  fileDuplicateProof,
  activeRun,
  uploadError,
  readableError,
} from "./model.js";

const data = () => ({
  submission: { status: "needs_review" },
  validation: {
    verdict: "eligible",
    acceptance_mode: "admin_required",
    checks: CHECKS.map(([code]) => ({ code, status: "pass" })),
  },
});

test("admin acceptance is unavailable for a normal user, unresolved check or incomplete validation", () => {
  assert.equal(canAdminAccept({ role: "user" }, data()), false);
  assert.equal(canAdminAccept({ role: "admin" }, data()), true);
  for (const kind of ["fail", "missing", "duplicate"]) {
    const item = data();
    if (kind === "fail") item.validation.checks[0].status = "fail";
    if (kind === "missing") item.validation.checks.pop();
    if (kind === "duplicate")
      item.validation.checks.push({ ...item.validation.checks[0] });
    assert.equal(canAdminAccept({ role: "admin" }, item), false);
  }
  const accepted = data();
  accepted.acceptance = { id: "already-accepted" };
  assert.equal(canAdminAccept({ role: "admin" }, accepted), false);
});

test("accepted decision and spreadsheet publication remain distinct", () => {
  assert.equal(publicationLabel("pending", true), "Spreadsheet update pending");
  assert.equal(publicationLabel("published", true), "Published to spreadsheet");
  assert.equal(publicationLabel("failed", true), "Spreadsheet update failed");
  assert.equal(publicationLabel("published", false), "No accepted record");
});

test("evidence retains printed zero, source quote and page without inventing missing values", () => {
  const fields = evidenceFields({
    evidence: {
      candidate: {
        tax_amount: { value: "0.00", source: { page: 2, quote: "GST 0.00" } },
      },
    },
  });
  assert.equal(fields.find((x) => x.key === "tax_amount").value, "0.00");
  assert.deepEqual(fields.find((x) => x.key === "tax_amount").source, {
    page: 2,
    quote: "GST 0.00",
  });
  assert.equal(fields.find((x) => x.key === "total_gross").value, null);
  assert.deepEqual(evidenceFields(null), []);
});

test("polling follows active work and stops on a completed decision", () => {
  assert.equal(
    activeRun({
      submission: { status: "processing" },
      run: { state: "running" },
    }),
    true,
  );
  assert.equal(activeRun({ submission: { status: "received" } }), true);
  assert.equal(
    activeRun({
      submission: { status: "accepted" },
      run: { state: "completed" },
    }),
    false,
  );
});

test("upload checks exact size boundary, extension and empty documents", () => {
  assert.equal(uploadError({ name: "scan.PDF", size: 5 * 1024 * 1024 }), null);
  assert.ok(uploadError({ name: "scan.pdf", size: 5 * 1024 * 1024 + 1 }));
  assert.ok(uploadError({ name: "scan.svg", size: 200 }));
  assert.ok(uploadError({ name: "scan.jpg", size: 0 }));
});

test("structured API errors are readable rather than rendered as raw JSON", () => {
  assert.equal(readableError({ detail: "SESSION_EXPIRED" }), "SESSION EXPIRED");
  assert.equal(
    readableError({ detail: [{ msg: "File is required" }] }),
    "File is required",
  );
  assert.equal(
    readableError({ detail: { code: "REFERENCE_STALE" } }),
    "REFERENCE STALE",
  );
});

test("early exact-file duplicate proof comes from recorded audit and is distinct from a fully validated business duplicate", () => {
  const early = {
    submission: { status: "blocked_duplicate", file_sha256: "a".repeat(64) },
    revision: null,
    validation: null,
    audit: [
      {
        event_type: "invoice.duplicate_blocked",
        details: { acceptance_id: "existing-acceptance" },
      },
    ],
  };
  assert.deepEqual(fileDuplicateProof(early), {
    acceptanceId: "existing-acceptance",
    fileHash: "a".repeat(64),
  });
  assert.equal(
    fileDuplicateProof({ ...early, validation: { checks: [] } }),
    null,
  );
  assert.equal(
    fileDuplicateProof({ ...early, revision: { id: "revision" } }),
    null,
  );
  assert.equal(fileDuplicateProof({ ...early, audit: [] }), null);
  assert.equal(
    fileDuplicateProof({
      ...early,
      submission: { ...early.submission, status: "processing" },
    }),
    null,
  );
});

test("invoice routes survive refresh and malformed detail routes stay safe", async () => {
  const { parseRoute } = await import("./model.js");
  const id = "11111111-1111-4111-8111-111111111111";
  assert.deepEqual(parseRoute("#invoices/" + id), {
    page: "invoices",
    invoiceId: id,
  });
  assert.deepEqual(parseRoute("#upload"), { page: "upload", invoiceId: null });
  assert.deepEqual(parseRoute("#invoices/not-a-uuid"), {
    page: "invoices",
    invoiceId: null,
  });
  assert.deepEqual(parseRoute("#wrong"), {
    page: "upload",
    invoiceId: null,
  });
});
test("review queue combines held invoices while the exact status filter stays exact", async () => {
  const { filterInvoices } = await import("./model.js");
  const items = [
    { status: "needs_review", vendor_code: "A" },
    { status: "reference_hold", vendor_code: "A" },
    { status: "accepted", vendor_code: "B" },
  ];
  assert.equal(filterInvoices(items, { status: "review_queue" }).length, 2);
  assert.equal(filterInvoices(items, { status: "needs_review" }).length, 1);
  assert.equal(filterInvoices(items, { vendor: "B" }).length, 1);
});

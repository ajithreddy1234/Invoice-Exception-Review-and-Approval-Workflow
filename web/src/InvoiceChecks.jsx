import React from "react";
import { CHECKS, human } from "./model.js";

export function StatusBadge({ value, children }) {
  const tone = ["accepted", "published", "pass", "completed", "valid"].includes(
    value,
  )
    ? "positive"
    : [
          "needs_review",
          "review",
          "pending",
          "reference_hold",
          "reconciliation_required",
          "admin_required",
        ].includes(value)
      ? "warning"
      : [
            "rejected",
            "processing_failed",
            "failed",
            "fail",
            "blocked_duplicate",
          ].includes(value)
        ? "negative"
        : "neutral";
  return (
    <span className={`badge ${tone}`}>
      <span className="badge-dot" />
      {children || human(value)}
    </span>
  );
}


export default function InvoiceChecks({ validation, exactDuplicate = false }) {
  const checks = Array.isArray(validation?.checks) ? validation.checks : [];
  return (
    <div className="check-list">
      {CHECKS.map(([code, label]) => {
        const found = checks.filter((item) => item.code === code);
        const item = found[0];
        const status = found.length > 1 ? "fail" : item?.status;
        const waiting = found.length === 1 && status === "review" && Array.isArray(item?.blocked_by) && item.blocked_by.length > 0;
        return (
          <div className="check-row" key={code}>
            <span
              className={`check-icon ${status === "pass" ? "pass" : waiting ? "waiting" : status ? "fail" : ""}`}
              aria-hidden="true"
            >
              {status === "pass" ? "✓" : waiting ? "·" : status ? "!" : "·"}
            </span>
            <div>
              <strong>{label}</strong>
              <p>
                {found.length > 1
                  ? "Conflicting check results. Revalidation required."
                  : exactDuplicate
                    ? "Not run after exact-file duplicate detection."
                    : item?.reason ||
                      item?.detail ||
                      item?.message ||
                      (status === "pass"
                        ? "Verified"
                        : item
                          ? "See review summary"
                          : "Awaiting validation")}
              </p>
            </div>
            <StatusBadge value={waiting ? "waiting" : status || (exactDuplicate ? "not_run" : "pending")}>
              {waiting ? "Waiting for PO" : status ? human(status) : exactDuplicate ? "Not run" : "Pending"}
            </StatusBadge>
          </div>
        );
      })}
    </div>
  );
}

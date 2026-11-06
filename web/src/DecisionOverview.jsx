import React from "react";
import { human, decisionSummary } from "./model.js";
import { StatusBadge } from "./InvoiceChecks.jsx";
import { money } from "./dashboard-model.js";

export function seconds(value) {
  if (value == null || !Number.isFinite(Number(value))) return "Not recorded";
  return Number(value) < 0.01 ? "<0.01 s" : `${Number(value).toFixed(2)} s`;
}
const timestamp = (value) =>
  value
    ? new Date(value).toLocaleString("en-IN", {
        dateStyle: "medium",
        timeStyle: "medium",
      })
    : "Not recorded";

export default function DecisionOverview({ data }) {
  const decision = data.decision;
  const accepted = Boolean(data.acceptance);
  const report =
    decision?.report ||
    (accepted ? data.publication?.status || "pending" : "not_required");
  const reportLabels = {
    published: "Published",
    pending: "Pending",
    publishing: "Publishing",
    failed: "Retry pending",
    reconciliation_required: "Needs reconciliation",
    not_required: "Not required",
  };
  return (
    <div className="business-decision">
      <dl className="decision-facts">
        <div>
          <dt>Decision</dt>
          <dd>
            <StatusBadge
              value={
                accepted
                  ? "accepted"
                  : data.submission.status === "accepted"
                    ? "needs_review"
                    : data.submission.status
              }
            />
          </dd>
        </div>
        <div>
          <dt>PO commitment</dt>
          <dd>{accepted ? "Recorded" : "Not recorded"}</dd>
        </div>
        <div>
          <dt>Spreadsheet report</dt>
          <dd>{reportLabels[report] || human(report)}</dd>
        </div>
      </dl>
      <div className="decision-explanation">
        <strong>Primary reason</strong>
        <p>{decision?.primary_reason || decisionSummary(data)}</p>
        {decision?.next_action && (
          <>
            <strong>Next action</strong>
            <p>{decision.next_action}</p>
          </>
        )}
        <strong>Financial effect</strong>
        <p>
          {decision?.financial_effect ||
            (accepted
              ? "The accepted amount is recorded against the PO."
              : "No PO amount has been committed by this submission.")}
        </p>
      </div>
      {data.duplicate_record?.submission_id && (
        <a
          className="text-link"
          href={`#invoices/${data.duplicate_record.submission_id}`}
        >
          Inspect prior accepted invoice {data.duplicate_record.invoice_number}{" "}
          →
        </a>
      )}
      <p className="small-muted">
        Acceptance records an invoice decision and PO commitment. It does not
        execute payment.
      </p>
    </div>
  );
}

export function RunTimeline({ data }) {
  const stages = data.timing?.stages || [];
  return (
    <section className="section-card run-timings">
      <div className="section-heading">
        <h3>Recorded processing stages</h3>
        <span className="small-muted">Server timestamps</span>
      </div>
      <p className="small-muted">
        Queue wait: {seconds(data.timing?.queue_seconds)} · Processing:{" "}
        {seconds(data.timing?.processing_seconds)}
      </p>
      {stages.length ? (
        <ol className="timeline">
          {stages.map((stage, index) => (
            <li key={`${stage.started_at}-${index}`}>
              <span className="timeline-point" />
              <div>
                <strong>{human(stage.stage)}</strong>
                <p>
                  <time dateTime={stage.started_at}>
                    {timestamp(stage.started_at)}
                  </time>
                </p>
                <p>
                  {stage.seconds == null
                    ? stage.state === "in_progress"
                      ? "In progress · duration saved when the stage ends"
                      : "End time not recorded"
                    : `${seconds(stage.seconds)} · ended ${timestamp(stage.finished_at)}`}
                </p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">
          No stage timestamps were recorded for this run. Exact duplicates can
          stop before extraction; admin revalidation uses a separate recorded
          review run.
        </p>
      )}
      <p className="small-muted">
        Durations span saved stage events; they include service waits.
        Retry/recovery stages remain separate. No percentage or stage timing is
        simulated.
      </p>
    </section>
  );
}

export function PolicyEvidence({ data }) {
  const policy = data.policy,
    reference = data.reference;
  if (!reference) return null;
  return (
    <section className="section-card policy-evidence">
      <h3>Procurement policy used</h3>
      <p className="small-muted">
        Snapshot {String(reference.id).slice(0, 8)} · imported{" "}
        {timestamp(reference.imported_at)}
      </p>
      <p>
        {reference.is_active && reference.fresh
          ? "Current active reference"
          : reference.is_active
            ? "Reference freshness window expired"
            : "Historical reference; a newer snapshot is active"}
      </p>
      {!data.acceptance && (!reference.fresh || !reference.is_active) && (
        <p className="notice warning-note">
          Acceptance is paused. An administrator must sync approved references
          and revalidate. Historical decisions remain recorded.
        </p>
      )}
      {policy ? (
        <dl className="policy-grid">
          <div>
            <dt>Automatic acceptance policy</dt>
            <dd>
              {policy.auto_accept_enabled
                ? "Enabled; manual review still requires separate acceptance"
                : "Administrator required"}
            </dd>
          </div>
          <div>
            <dt>Billing mode</dt>
            <dd>{human(policy.billing_mode)}</dd>
          </div>
          <div>
            <dt>Currency</dt>
            <dd>{policy.currency}</dd>
          </div>
          <div>
            <dt>Arithmetic tolerance</dt>
            <dd>{money(policy.arithmetic_tolerance_minor, policy.currency)}</dd>
          </div>
          <div>
            <dt>Unit-price tolerance</dt>
            <dd>{Number(policy.price_tolerance_bps) / 100}%</dd>
          </div>
          <div>
            <dt>Authorized PO gross</dt>
            <dd>
              {money(
                policy.authorized_gross_minor,
                policy.po_currency || policy.currency,
              )}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="muted">
          A valid PO and currency rule must be resolved before a policy can be
          displayed. No default tolerance is assumed.
        </p>
      )}
      <p className="small-muted">
        Values come from this validation's immutable reference snapshot.
        Tolerance cannot raise the PO cap. Current remaining balances are shown
        on the dashboard.
      </p>
    </section>
  );
}

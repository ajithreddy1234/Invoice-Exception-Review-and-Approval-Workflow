import React, { useState, useEffect } from "react";
import { human } from "./model.js";

import { revisionChanges } from "./revision-history-model.js";
const display = (value) =>
  value == null
    ? "Not recorded"
    : typeof value === "object"
      ? JSON.stringify(value, null, 2)
      : String(value);

export default function RevisionHistory({ data, request }) {
  const [selected, setSelected] = useState(""),
    [record, setRecord] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    if (!selected) return;
    let current = true;
    setRecord(null);
    setError("");
    request(`/api/submissions/${data.submission.id}/revisions/${selected}`)
      .then((r) => {
        if (current) setRecord(r);
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [selected, data.submission.id, request]);
  const candidate = record?.revision?.evidence?.candidate;
  const changes = revisionChanges(
    record?.previous_revision?.candidate,
    candidate,
  );
  const context = record?.revision?.evidence?.review_context;
  return (
    <section className="section-card revision-comparison">
      <h3>Extraction & review history</h3>
      <p className="muted">
        Inspect any saved revision. Viewing history cannot change the current
        decision.
      </p>
      <label>
        Saved revision
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">Choose a revision</option>
          {(data.revisions || []).map((r) => (
            <option key={r.id} value={r.id}>
              Revision {r.revision_no} · {human(r.kind)}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
      {selected && !record && !error && (
        <p role="status">Loading recorded revision…</p>
      )}
      {record && (
        <div className="revision-record">
          <p>
            <strong>Revision {record.revision.revision_no}</strong> ·{" "}
            {record.reviewer?.display_name || "Automated extraction"}
          </p>
          {record.revision.correction_reason && (
            <p>
              <strong>Review reason:</strong>{" "}
              {record.revision.correction_reason}
            </p>
          )}
          <p className="small-muted">
            {record.revision.created_at
              ? new Date(record.revision.created_at).toLocaleString("en-IN")
              : ""}{" "}
            · Reviewer identity {record.reviewer?.id || "system"} ·{" "}
            {record.validation?.checks?.filter((c) => c.status === "pass")
              .length || 0}{" "}
            of {record.validation?.checks?.length || 0} recorded checks passed
          </p>
          {changes.length ? (
            <div className="revision-diffs">
              {changes.map((row) => (
                <article key={row.key}>
                  <h4>{row.label}</h4>
                  <div className="revision-pair">
                    <div>
                      <strong>Previous saved revision</strong>
                      <pre>{display(row.before)}</pre>
                    </div>
                    <div>
                      <strong>Saved interpretation</strong>
                      <pre>{display(row.after)}</pre>
                    </div>
                  </div>
                  {row.before_source && (
                    <p>
                      Previous source · Page {row.before_source.page} · “
                      {row.before_source.quote}”
                    </p>
                  )}
                  {row.source && (
                    <p>
                      Saved source · Page {row.source.page} · “
                      {row.source.quote}”
                    </p>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p>
              No extracted values changed. A review can resolve PO selection,
              description mapping or OCR confidence while preserving source
              values.
            </p>
          )}
          {context?.selected_po && (
            <p>
              Verified PO selection: {context.selected_po}. An absent printed PO
              stays absent.
            </p>
          )}
          {(context?.line_mappings || []).map((row) => (
            <p key={row.invoice_line}>
              Interpretation mapping only — line {row.invoice_line + 1}: “
              {row.source_description}” → “{row.po_description}”. Original
              invoice wording is preserved.
            </p>
          ))}
          {!!context?.verified_ocr_fields?.length && (
            <p>
              Grounded OCR confirmation:{" "}
              {context.verified_ocr_fields.join(", ")}. Missing or unsupported
              values cannot be invented.
            </p>
          )}
          <details>
            <summary>Recorded field and line evidence</summary>
            <pre className="historical-evidence">
              {JSON.stringify(candidate, null, 2)}
            </pre>
          </details>
          <p className="small-muted">
            Checks belong to this saved revision. A correction never constitutes
            acceptance; acceptance has its own actor, reason and ledger record.
          </p>
        </div>
      )}
    </section>
  );
}

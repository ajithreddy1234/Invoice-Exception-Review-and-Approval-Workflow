import React, { useState } from "react";
import { FIELD_NAMES, human, readableError } from "./model.js";

export function SourceViewer({ data }) {
  const [page, setPage] = useState(1),
    [zoom, setZoom] = useState(100),
    [failed, setFailed] = useState(false);
  const count =
    data.submission.page_count ||
    data.revision?.evidence?.document?.pages?.length ||
    1;
  const available =
    !data.submission.document_deleted_at &&
    Date.parse(data.submission.document_expires_at) > Date.now();
  const url = `/api/submissions/${data.submission.id}`;
  return (
    <section className="section-card source-viewer">
      <div className="section-heading">
        <div>
          <h3>Original document</h3>
          <p className="small-muted">
            Compare the source with the extracted fields.
          </p>
        </div>
        <a
          className="text-link"
          href={`${url}/document`}
          target="_blank"
          rel="noreferrer"
        >
          Open ↗
        </a>
      </div>
      <div className="preview-tools">
        <div>
          <button
            className="preview-button"
            aria-label="Previous source page"
            disabled={page === 1}
            onClick={() => {
              setPage(page - 1);
              setFailed(false);
            }}
          >
            ←
          </button>
          <span>
            Page {page} of {count}
          </span>
          <button
            className="preview-button"
            aria-label="Next source page"
            disabled={page === count}
            onClick={() => {
              setPage(page + 1);
              setFailed(false);
            }}
          >
            →
          </button>
        </div>
        <div>
          <button
            className="preview-button"
            aria-label="Zoom out source"
            disabled={zoom === 100}
            onClick={() => setZoom(zoom - 25)}
          >
            −
          </button>
          <span>{zoom}%</span>
          <button
            className="preview-button"
            aria-label="Zoom in source"
            disabled={zoom === 200}
            onClick={() => setZoom(zoom + 25)}
          >
            +
          </button>
        </div>
      </div>
      <div className="page-preview-area">
        {!available ? (
          <p>Original expired. Stored evidence is retained below.</p>
        ) : failed ? (
          <p>
            Preview unavailable.{" "}
            <a href={`${url}/document`} target="_blank" rel="noreferrer">
              Open the original document
            </a>
            .
          </p>
        ) : (
          <img
            key={page}
            className="page-preview-image"
            style={{ width: `${zoom}%` }}
            src={`${url}/pages/${page}`}
            alt={`Original invoice page ${page}`}
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <p className="preview-note">
        The preview is rendered from the private original. It is not a generated
        or modified invoice.
      </p>
    </section>
  );
}

function FieldEditor({ name, field, onChange }) {
  const f = field || { value: null, source: null };
  function update(key, value) {
    if (key === "value") {
      onChange({ value: value || null, source: value ? f.source : null });
      return;
    }
    onChange({
      ...f,
      source: {
        page: f.source?.page || 1,
        quote: f.source?.quote || "",
        [key]: value,
      },
    });
  }
  return (
    <div className="correction-field">
      <label>
        {FIELD_NAMES[name] || human(name)}
        <input
          value={f.value ?? ""}
          onChange={(e) => update("value", e.target.value)}
          placeholder="Leave empty if unreadable"
        />
      </label>
      <div className="quote-editor">
        <label>
          Page
          <input
            type="number"
            min="1"
            max="3"
            value={f.source?.page || 1}
            disabled={!f.value}
            onChange={(e) => update("page", Number(e.target.value))}
          />
        </label>
        <label>
          Exact quote from page
          <textarea
            rows="2"
            maxLength="2000"
            value={f.source?.quote ?? ""}
            disabled={!f.value}
            onChange={(e) => update("quote", e.target.value)}
          />
        </label>
      </div>
    </div>
  );
}

export function ReviewEditor({ data, user, request, onUpdate }) {
  const original = data.revision?.evidence?.candidate;
  const [open, setOpen] = useState(false),
    [candidate, setCandidate] = useState(() =>
      original ? structuredClone(original) : null,
    );
  const [reason, setReason] = useState(""),
    [selectedPo, setSelectedPo] = useState(""),
    [resolved, setResolved] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  if (
    user.role !== "admin" ||
    !candidate ||
    data.acceptance ||
    !["needs_review", "reference_hold"].includes(data.submission.status)
  )
    return null;
  const choices = data.validation?.po_candidates || [];
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const corrected = {
        ...candidate,
        uncertainties: resolved ? [] : candidate.uncertainties,
      };
      await request(`/api/admin/submissions/${data.submission.id}/correct`, {
        method: "POST",
        body: JSON.stringify({
          base_revision_id: data.revision.id,
          candidate: corrected,
          reason,
          selected_po: selectedPo || null,
        }),
      });
      await onUpdate();
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="section-card correction-panel">
      <button
        className="correction-toggle"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span>
          <strong>Correct extraction & resolve PO</strong>
          <small>Admin review · original evidence required</small>
        </span>
        <span>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <form onSubmit={submit}>
          <p className="notice">
            Correct only what the original actually shows. Every non-empty value
            needs an exact page quote. Saving reruns all checks and does not
            accept the invoice.
          </p>
          {error && (
            <div className="error-box" role="alert">
              {error}
            </div>
          )}
          {!candidate.po_reference.value && choices.length > 1 && (
            <label className="po-selection">
              Purchase order selection
              <select
                value={selectedPo}
                onChange={(e) => setSelectedPo(e.target.value)}
              >
                <option value="">Keep unresolved</option>
                {choices.map((p) => (
                  <option key={p.po_code} value={p.po_code}>
                    {p.po_code}
                  </option>
                ))}
              </select>
              <small>
                Only exact vendor, currency and line-matching candidates can be
                selected. Explain the basis below.
              </small>
            </label>
          )}
          <div className="correction-grid">
            {Object.keys(FIELD_NAMES).map((key) => (
              <FieldEditor
                key={key}
                name={key}
                field={candidate[key]}
                onChange={(field) =>
                  setCandidate({ ...candidate, [key]: field })
                }
              />
            ))}
          </div>
          <label className="tax-selector">
            Tax presentation
            <select
              value={candidate.tax_presentation}
              onChange={(e) =>
                setCandidate({ ...candidate, tax_presentation: e.target.value })
              }
            >
              {["exclusive", "inclusive", "none", "unclear"].map((v) => (
                <option key={v} value={v}>
                  {human(v)}
                </option>
              ))}
            </select>
          </label>
          <details className="line-corrections">
            <summary>
              Correct line items ({candidate.line_items.length})
            </summary>
            {candidate.line_items.map((line, i) => (
              <div key={i}>
                <h4>Line {i + 1}</h4>
                <div className="correction-grid">
                  {Object.keys(line).map((key) => (
                    <FieldEditor
                      key={key}
                      name={key}
                      field={line[key]}
                      onChange={(field) => {
                        const rows = candidate.line_items.map((v, n) =>
                          n === i ? { ...v, [key]: field } : v,
                        );
                        setCandidate({ ...candidate, line_items: rows });
                      }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </details>
          {candidate.uncertainties.length > 0 && (
            <div className="uncertainty-review">
              <strong>Extraction uncertainties</strong>
              <ul>
                {candidate.uncertainties.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={resolved}
                  onChange={(e) => setResolved(e.target.checked)}
                />
                I resolved these uncertainties against readable source evidence.
                Missing or unsupported fields will still block acceptance.
              </label>
            </div>
          )}
          <label>
            Review reason
            <textarea
              required
              minLength="5"
              maxLength="2000"
              rows="3"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="What changed, where it is visible, and why any PO was selected"
            />
          </label>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy || reason.trim().length < 5}
            >
              {busy
                ? "Verifying original & rerunning checks…"
                : "Save & rerun checks"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

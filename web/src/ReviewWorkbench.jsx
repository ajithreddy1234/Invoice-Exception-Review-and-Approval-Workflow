import React, { useEffect, useState } from "react";
import { reviewFieldLabel, reviewSelections } from "./review-model.js";
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
  const [options, setOptions] = useState(null), [optionsError,setOptionsError] = useState("");
  const [mappings,setMappings] = useState({}), [verifiedFields,setVerifiedFields] = useState([]);
  const reviewable = user.role === "admin" && candidate && !data.acceptance && ["needs_review","reference_hold"].includes(data.submission.status);
  useEffect(() => {
    if (!open || !reviewable) return;
    let current = true;
    setOptions(null);setOptionsError("");setMappings({});setVerifiedFields([]);setSelectedPo("");setResolved(false);
    request(`/api/admin/submissions/${data.submission.id}/review-options`).then(value => {
      if (current && value.revision_id === data.revision.id) setOptions(value);
      else if(current) setOptionsError("The revision changed. Refresh the invoice before reviewing.");
    }).catch(error => {if(current) setOptionsError(error.message);});
    return () => {current=false;};
  },[open,reviewable,request,data.submission.id,data.revision?.id]);
  const unchanged = candidate && JSON.stringify(candidate) === JSON.stringify(original);
  const selection = candidate ? reviewSelections(options,candidate,selectedPo,mappings) : {mappings:[]};
  function updateCandidate(value) {setCandidate(value);setMappings({});setVerifiedFields([]);setSelectedPo("");setResolved(false);}
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
          review_reference_id: unchanged ? options?.reference_version_id || null : null,
          line_mappings: unchanged ? selection.mappings : [],
          verified_ocr_fields: unchanged ? verifiedFields : [],
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
                  updateCandidate({ ...candidate, [key]: field })
                }
              />
            ))}
          </div>
          <label className="tax-selector">
            Tax presentation
            <select
              value={candidate.tax_presentation}
              onChange={(e) =>
                updateCandidate({ ...candidate, tax_presentation: e.target.value })
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
                        updateCandidate({ ...candidate, line_items: rows });
                      }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </details>
          <fieldset className="review-decisions">
            <legend>Resolve supported exceptions</legend>
            <p className="small-muted">Describe why the original and procurement record agree. Financial limits and source checks still apply. Saving requires a separate acceptance.</p>
            {optionsError && <div role="alert" className="error-box">{optionsError}</div>}
            {!unchanged && <p>Save the corrected fields first, then reopen review to load matching choices and verify OCR warnings.</p>}
            {unchanged && !options && !optionsError && <p role="status">Loading current review choices…</p>}
            {unchanged && selection.po && candidate.line_items.map((line,index) => <label key={index}>
              Map invoice line {index+1}: {line.description.value || "Unreadable description"}
              <select aria-label={`PO line for invoice line ${index+1}`} value={mappings[index]?.po === selection.po.po_code ? mappings[index].code : ""}
                onChange={e => setMappings({...mappings,[index]:{po:selection.po.po_code,code:e.target.value}})}>
                <option value="">Use exact automatic matching</option>
                {selection.po.lines.map(row => <option key={row.line_code} value={row.line_code}>{row.line_code} · {row.description} · {row.unit}</option>)}
              </select>
            </label>)}
            {unchanged && (options?.ocr_fields || []).map(path => <label className="checkbox-label" key={path}>
              <input type="checkbox" checked={verifiedFields.includes(path)} onChange={e => setVerifiedFields(e.target.checked ? [...verifiedFields,path] : verifiedFields.filter(x => x !== path))}/>
              I checked {reviewFieldLabel(path)} against the readable original; the quoted value is correct despite low OCR confidence.
            </label>)}
            {unchanged && options && !selection.po && <p>Resolve the vendor, PO and currency before mapping lines. An unreadable source value requires a clearer document.</p>}
          </fieldset>
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


export function ReviewResolution({data}) {
  const context=data.revision?.evidence?.review_context;
  if(!context?.actor_id) return null;
  return <section className="section-card review-resolution">
    <h3>Recorded admin resolution</h3>
    <p>{context.reason}</p>
    {context.selected_po && <p>Selected purchase order: <strong>{context.selected_po}</strong></p>}
    {(context.line_mappings || []).map(row => <p key={row.invoice_line}>
      Line {row.invoice_line+1}: {row.source_description} → {row.po_description} ({row.po_code}/{row.po_line_code})
    </p>)}
    {(context.verified_ocr_fields || []).length>0 && <p>OCR confirmed against original: {context.verified_ocr_fields.map(reviewFieldLabel).join(", ")}.</p>}
    <p className="small-muted">Reviewer {context.actor_id} · Reference {context.reference_version_id}. Original extraction and OCR warnings remain in the evidence history. Acceptance is a separate recorded action.</p>
  </section>;
}

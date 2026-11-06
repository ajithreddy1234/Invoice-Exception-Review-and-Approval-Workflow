import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  CHECKS,
  activeRun,
  canAdminAccept,
  evidenceFields,
  fileDuplicateProof,
  human,
  publicationLabel,
  uploadError,
  parseRoute,
  decisionSummary,
} from "./model.js";
import { SourceViewer, ReviewEditor, ReviewResolution } from "./ReviewWorkbench.jsx";
import "./styles.css";
import Dashboard, { CompanySelect, money } from "./Dashboard.jsx";
import { apiRequest } from "./api.js";
import BrandMark from "./BrandMark.jsx";
import LogoutControl from "./LogoutControl.jsx";
import Checks, { StatusBadge as Badge } from "./InvoiceChecks.jsx";
import { reviewGuidance } from "./review-guidance.js";
import { useInvoiceRegister } from "./useInvoiceRegister.js";

const dateTime = (value) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not available";
const amount = (value, currency = "INR") =>
  value === null || value === undefined
    ? "Not available"
    : new Intl.NumberFormat(undefined, {
        style: "currency",
        currency,
        minimumFractionDigits: 2,
      }).format(Number(value) / 100);


function ErrorBox({ children }) {
  return children ? (
    <div className="error-box" role="alert">
      {children}
    </div>
  ) : null;
}
function Empty({ title, children }) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden="true">
        ▤
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

function Login({ onLogin, initialError, request }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const actor = await request("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setPassword("");
      onLogin(actor);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-layout">
      <section className="login-story">
        <a href="/" className="brand">
          <BrandMark />
          <span>
            Invoice review<small>PROCUREMENT OPERATIONS</small>
          </span>
        </a>
        <div className="login-message">
          <span className="eyebrow">PROCUREMENT VERIFICATION</span>
          <h1>
            Every invoice.
            <br />A clear decision.
          </h1>
          <p>
            Match invoices to approved procurement records, inspect the source
            evidence and keep a traceable acceptance history.
          </p>
          <div className="process-list">
            <span>
              <b>01</b>Upload the original
            </span>
            <span>
              <b>02</b>Inspect the evidence
            </span>
            <span>
              <b>03</b>Record the decision
            </span>
          </div>
        </div>
        <p className="login-foot">
          PDFs and images · Google Sheets procurement · Auditable decisions
        </p>
      </section>
      <section className="login-form-panel">
        <form className="login-form" onSubmit={submit}>
          <span className="eyebrow muted">WORKSPACE ACCESS</span>
          <h2>Welcome back</h2>
          <p className="muted">
            Sign in with your provisioned workspace account.
          </p>
          <ErrorBox>{error}</ErrorBox>
          <label>
            Email address
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={busy}
              placeholder="you@company.com"
            />
          </label>
          <label>
            Password
            <span className="password-control">
              <input
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={busy}
              />
              <button
                type="button"
                className="password-toggle"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                onClick={() => setShowPassword(!showPassword)}
                title={showPassword ? "Hide password" : "Show password"}
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  aria-hidden="true"
                >
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
                  <circle cx="12" cy="12" r="3" />
                  {showPassword && <path d="m3 3 18 18" />}
                </svg>
              </button>
            </span>
          </label>
          <button className="primary full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in to workspace"}
            <span aria-hidden="true">→</span>
          </button>
          <p className="form-note">
            Access is managed by your workspace administrator. Contact them if
            you need an account.
          </p>
        </form>
      </section>
    </main>
  );
}

function Upload({ onUpload, request }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const input = useRef();
  async function submit(event) {
    event.preventDefault();
    const problem = uploadError(file);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("request_key", key);
    try {
      const result = await request("/api/submissions", {
        method: "POST",
        body: form,
      });
      setFile(null);
      setKey(crypto.randomUUID());
      input.current.value = "";
      onUpload(result.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="upload-panel" onSubmit={submit}>
      <div className="upload-symbol" aria-hidden="true">
        ↑
      </div>
      <div className="upload-content">
        <h2>Verify an invoice</h2>
        <p>PDF, JPG or PNG · Up to 5 MiB and 3 pages · English documents</p>
        <p className="small-muted">Originals are stored privately for up to seven days. Extracted page text is sent to Google Gemini for field extraction. Upload only documents your organization has authorized for that service.</p>
        <div className="file-controls">
          <label className="file-label">
            Choose invoice
            <input
              ref={input}
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
              disabled={busy}
              onChange={(e) => {
                setFile(e.target.files[0] || null);
                setKey(crypto.randomUUID());
                setError("");
              }}
            />
          </label>
          <span className="filename">
            {file ? file.name : "No file selected"}
          </span>
        </div>
        <ErrorBox>{error}</ErrorBox>
      </div>
      <button className="primary" disabled={busy || !file}>
        {busy ? "Uploading…" : "Upload & verify"}
        <span aria-hidden="true">→</span>
      </button>
    </form>
  );
}

function Evidence({ revision }) {
  const fields = evidenceFields(revision);
  const candidate = revision?.evidence?.candidate || revision?.candidate;
  const pages = revision?.evidence?.document?.pages || [];
  if (!fields.length)
    return (
      <p className="muted">
        Source fields will appear after extraction completes.
      </p>
    );
  return (
    <>
      <div className="evidence-grid">
        {fields.map((field) => (
          <article className="evidence-field" key={field.key}>
            <span className="field-label">{field.label}</span>
            <strong className={field.value === null ? "missing-value" : ""}>
              {field.value ?? "Not readable / missing"}
            </strong>
            {field.source?.quote ? (
              <>
                <blockquote>{field.source.quote}</blockquote>
                <span className="source-location">
                  Source · Page {field.source.page}
                </span>
              </>
            ) : (
              <span className="source-location missing-value">
                No supporting source quote
              </span>
            )}
          </article>
        ))}
      </div>
      {candidate?.uncertainties?.length > 0 && (
        <div className="notice warning-note">
          <strong>Extraction needs attention</strong>
          <ul>
            {candidate.uncertainties.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {candidate?.line_items?.length > 0 && (
        <details className="source-text">
          <summary>
            Invoice line evidence ({candidate.line_items.length})
          </summary>
          {candidate.line_items.map((line, index) => (
            <div className="line-evidence" key={index}>
              <h4>Line {index + 1}</h4>
              {Object.entries(line).map(([key, field]) => (
                <div key={key}>
                  <strong>{human(key)}: </strong>
                  {field?.value ?? "Not available"}
                  {field?.source && (
                    <blockquote>
                      Page {field.source.page} · {field.source.quote}
                    </blockquote>
                  )}
                </div>
              ))}
            </div>
          ))}
        </details>
      )}
      {pages.length > 0 && (
        <details className="source-text">
          <summary>Page text used for extraction</summary>
          {pages.map((page) => (
            <div key={page.number}>
              <h4>
                Page {page.number} ·{" "}
                {page.method === "ocr" ? "OCR" : "Embedded text"}
              </h4>
              <pre>{page.text}</pre>
            </div>
          ))}
        </details>
      )}
    </>
  );
}


function ReviewActions({ data, user, request, onUpdate }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const status = data?.submission?.status;
  const accepted = Boolean(data?.acceptance);
  const allowed = canAdminAccept(user, data);
  const guidance = reviewGuidance(data, user.role);
  const rejectable =
    user.role === "admin" && !accepted && status === "needs_review";
  const retryable =
    ["processing_failed", "reference_hold", "needs_review"].includes(status) &&
    !accepted;
  if (!retryable && !rejectable && !allowed) return null;
  async function action(kind) {
    setBusy(kind);
    setError("");
    try {
      const url =
        kind === "retry"
          ? `/api/submissions/${data.submission.id}/retry`
          : `/api/admin/submissions/${data.submission.id}/${kind}`;
      await request(url, {
        method: "POST",
        body: JSON.stringify(kind === "retry" ? {} : { reason }),
      });
      setReason("");
      await onUpdate();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="section-card">
      <div className="section-heading">
        <h3>{user.role === "admin" ? "Review actions" : "Next step"}</h3>
      </div>
      {guidance ? <div className="review-guidance" role="note"><strong>{guidance.title}</strong><p>{guidance.message}</p></div> : <p className="muted">
        Compare the failed checks with the source and approved procurement records. Missing or unreadable critical information needs a clearer original. An administrator cannot waive duplicates or financial limits.
      </p>}
      <ErrorBox>{error}</ErrorBox>
      {user.role === "admin" && (allowed || rejectable) && (
        <label>
          Decision reason
          <textarea
            rows="3"
            maxLength="2000"
            placeholder="Explain the verified evidence and reason for this decision…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={Boolean(busy)}
          />
        </label>
      )}
      <div className="button-row">
        {retryable && (
          <button
            className="secondary"
            disabled={Boolean(busy)}
            onClick={() => action("retry")}
          >
            {busy === "retry" ? "Retrying…" : "Re-run verification"}
          </button>
        )}
        {rejectable && (
          <button
            className="secondary"
            disabled={Boolean(busy) || reason.trim().length < 5}
            onClick={() => action("request-document")}
          >
            {busy === "request-document"
              ? "Recording request…"
              : "Request clearer invoice"}
          </button>
        )}
        {rejectable && (
          <button
            className="danger-button"
            disabled={Boolean(busy) || reason.trim().length < 5}
            onClick={() => action("reject")}
          >
            {busy === "reject" ? "Recording…" : "Reject invoice"}
          </button>
        )}
        {allowed && (
          <button
            className="primary"
            disabled={Boolean(busy) || reason.trim().length < 5}
            onClick={() => action("accept")}
          >
            {busy === "accept" ? "Accepting…" : "Accept with reason"}
          </button>
        )}
      </div>
    </section>
  );
}

function Detail({ data, loading, error, user, request, onUpdate }) {
  if (loading && !data)
    return (
      <div className="detail-placeholder" role="status">
        Loading invoice evidence…
      </div>
    );
  if (error && !data) return <ErrorBox>{error}</ErrorBox>;
  if (!data)
    return (
      <Empty title="Select an invoice">
        Choose a record to inspect its source, validation checks and decision
        history.
      </Empty>
    );
  const { submission, run, revision, validation, acceptance, publication } =
    data;
  const accepted = Boolean(acceptance);
  const duplicateProof = fileDuplicateProof(data);
  const documentUrl = `/api/submissions/${submission.id}/document`;
  const filename =
    submission.original_filename || submission.filename || "Invoice";
  const image = ["image/jpeg", "image/png"].includes(submission.mime_type);
  const sourceAvailable =
    !submission.document_deleted_at &&
    (!submission.document_expires_at ||
      Date.parse(submission.document_expires_at) > Date.now());
  const publicationStatus =
    publication?.status || submission.publication_status;
  return (
    <div className="detail-stack">
      <ErrorBox>{error}</ErrorBox>
      <section className="section-card decision-card">
        <div className="detail-title">
          <div>
            <span className="eyebrow muted">INVOICE RECORD</span>
            <h2>{filename}</h2>
            {revision?.invoice_number && <p className="small-muted">Invoice number · {revision.invoice_number}</p>}
          </div>
          <button
            className="icon-button"
            onClick={onUpdate}
            disabled={loading}
            aria-label="Refresh selected invoice"
          >
            ↻
          </button>
        </div>
        <div className="decision-badges">
          <Badge value={accepted ? "accepted" : submission.status} />
          {accepted && (
            <Badge value={publicationStatus || "pending"}>
              {publicationLabel(publicationStatus, true)}
            </Badge>
          )}
        </div>
        {accepted ? (
          <>
            <p className="decision-summary">
              Accepted amount{" "}
              <strong>
                {amount(acceptance.amount_minor, acceptance.currency)}
              </strong>
            </p>
            <p className="muted">
              The acceptance is recorded.{" "}
              {publicationLabel(publicationStatus, true)}.
            </p>
            <code className="record-id">Acceptance ID · {acceptance.id}</code>
          </>
        ) : duplicateProof ? (
          <>
            <p className="decision-summary">
              This exact file was already accepted. No new PO balance was
              consumed.
            </p>
            <code className="record-id">
              Matched acceptance ID · {duplicateProof.acceptanceId}
            </code>
            {duplicateProof.fileHash && (
              <code className="record-id">
                File SHA-256 · {duplicateProof.fileHash}
              </code>
            )}
          </>
        ) : (
          <p className="decision-summary">{decisionSummary(data)}</p>
        )}
        {run && (
          <div className="stage-line">
            <span
              className={
                activeRun(data) ? "activity-dot active" : "activity-dot"
              }
            />
            <strong>{run.stage === "retrying_extraction" ? "Extraction service busy · retrying once" : human(run.stage || run.state)}</strong>
            <span>{human(run.state)}</span>
          </div>
        )}
        {revision?.evidence?.extractor?.origin === "cache" && (
          <div className="notice" role="status"><strong>Using saved extraction</strong><p>The saved reading of this invoice was reused. Its source evidence and all nine checks were verified again against current records.</p></div>
        )}
        {revision?.evidence?.extractor?.origin === "provider" && (
          <p className="small-muted">Invoice details read from the original source for this revision.</p>
        )}
        {publication?.last_error && (
          <div className="notice warning-note">
            Spreadsheet publication: {human(publication.last_error)}
          </div>
        )}
        {!accepted &&
          data.reviews?.some((r) => r.action === "request_document") && (
            <div className="notice warning-note">
              <strong>Clearer source requested</strong>
              <p>
                {
                  data.reviews.find((r) => r.action === "request_document")
                    .reason
                }
              </p>
              <small>Recorded in this workspace; no email was sent.</small>
            </div>
          )}
        {!accepted && canAdminAccept(user, data) && (
          <p className="notice">
            All nine checks pass. Review the evidence, then use “Accept with
            reason” below.
          </p>
        )}
        {validation?.po_code && (
          <div className="key-value">
            <span>Matched purchase order</span>
            <strong>{validation.po_code}</strong>
          </div>
        )}
        {validation?.po_candidates?.length > 0 && !validation.po_code && (
          <div className="notice warning-note">
            <strong>Possible purchase orders</strong>
            <p>
              {validation.po_candidates
                .map((item) =>
                  typeof item === "string"
                    ? item
                    : item.po_code || item.id || "Unresolved candidate",
                )
                .join(", ")}
            </p>
            <p>
              An ambiguous match requires review; no purchase order has been
              selected.
            </p>
          </div>
        )}
      </section>
      <div className="review-workspace">
        <SourceViewer key={submission.id} data={data} />
        <section className="section-card">
          <div className="section-heading">
            <h3>Validation checks</h3>
            <span className="small-muted">{CHECKS.length} required checks</span>
          </div>
          {duplicateProof && (
            <p className="muted evidence-intro">
              Verification stopped after exact-file duplicate detection.
              Extraction and further checks were not repeated.
            </p>
          )}
          <Checks
            validation={validation}
            exactDuplicate={Boolean(duplicateProof)}
          />
        </section>
      </div>
      <ReviewEditor
        key={revision?.id || submission.id}
        data={data}
        user={user}
        request={request}
        onUpdate={onUpdate}
      />
      <ReviewResolution data={data} />
      <section className="section-card">
        <div className="section-heading">
          <h3>Source evidence</h3>
          {sourceAvailable ? (
            <a
              className="text-link"
              href={documentUrl}
              target="_blank"
              rel="noreferrer"
            >
              Open original ↗
            </a>
          ) : (
            <span className="small-muted">Original expired</span>
          )}
        </div>
        <p className="muted evidence-intro">
          {duplicateProof
            ? "The identical document matches the acceptance record above. Extraction was not repeated."
            : "Quotes show what the document actually states. Missing values remain unresolved."}
        </p>
        {!sourceAvailable && (
          <p className="notice warning-note">
            The original has reached its retention limit. Stored extraction
            evidence remains visible; upload a readable replacement for further
            verification.
          </p>
        )}
        {!duplicateProof && <Evidence revision={revision} />}
      </section>
      <ReviewActions
        key={submission.id}
        data={data}
        user={user}
        request={request}
        onUpdate={onUpdate}
      />
      <section className="section-card revision-history">
        <div className="section-heading">
          <h3>Source & review versions</h3>
          <span className="small-muted">
            {data.revisions?.length || 0} immutable revisions
          </span>
        </div>
        <p className="small-muted">
          Reference imported {dateTime(data.reference?.imported_at)} ·{" "}
          {data.reference?.fresh && data.reference?.is_active !== false
            ? "Active snapshot"
            : "Historical snapshot"}
        </p>
        <code className="reference-id">
          Reference: {data.reference?.id || "Not validated yet"}
        </code>
        {data.revisions?.map((r) => (
          <div className="revision-row" key={r.id}>
            <strong>
              Revision {r.revision_no} · {human(r.kind)}
            </strong>
            <span>{dateTime(r.created_at)}</span>
            {r.reason && <p>{r.reason}</p>}
          </div>
        ))}
      </section>
      <section className="section-card">
        <div className="section-heading">
          <h3>Activity history</h3>
          <span className="small-muted">Recorded events</span>
        </div>
        {data.audit?.length ? (
          <ol className="timeline">
            {data.audit.map((event, index) => (
              <li key={event.id || index}>
                <span className="timeline-point" />
                <div>
                  <strong>{human(event.event_type)}</strong>
                  {event.stage && <p>{human(event.stage)}</p>}
                  {event.details?.reason && <p>{event.details.reason}</p>}
                  <time>{dateTime(event.created_at)}</time>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No activity has been recorded yet.</p>
        )}
      </section>
      <p className="record-footer">Record ID · {submission.id}</p>
    </div>
  );
}

function AdminPanel({ request, onRefresh }) {
  const [opened, setOpened] = useState(false);
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function inspect() {
    setBusy("health");
    setError("");
    try {
      setHealth(await request("/api/admin/health"));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }
  async function action(kind) {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      await request(
        kind === "sync"
          ? "/api/admin/procurement/sync"
          : "/api/admin/publication/retry",
        { method: "POST", body: "{}" },
      );
      setNotice(
        kind === "sync"
          ? "Procurement sync completed."
          : "Spreadsheet publication retry requested.",
      );
      await onRefresh();
      await inspect();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }
  const reference = health?.reference;
  return (
    <section className="admin-panel">
      <button
        className="admin-toggle"
        aria-expanded={opened}
        onClick={() => {
          setOpened(!opened);
          if (!opened) inspect();
        }}
      >
        <span>
          ⌘ <strong>Procurement & service health</strong>
        </span>
        <span>{opened ? "−" : "+"}</span>
      </button>
      {opened && (
        <div className="admin-body">
          <ErrorBox>{error}</ErrorBox>
          {notice && (
            <p className="notice" role="status">
              {notice}
            </p>
          )}
          <div className="health-grid">
            {health && <>
              <div className="health-item"><span>Startup checks</span><Badge value={health.startup_complete && health.startup !== "reference_import_failed" ? "pass" : "pending"}>{human(health.startup)}</Badge></div>
              <div className="health-item"><span>Invoice workers</span><Badge value={health.workers_running && !Object.values(health.worker_errors || {}).some(Boolean) ? "pass" : "pending"}>{!health.workers_running ? "Starting or disabled" : Object.values(health.worker_errors || {}).some(Boolean) ? "Dependency retry pending" : "Running"}</Badge></div>
            </>}
            {health?.configured &&
              Object.entries(health.configured).map(([key, value]) => (
                <div className="health-item" key={key}>
                  <span>{human(key)}</span>
                  <Badge value={value ? "pass" : "failed"}>
                    {value ? "Configured" : "Setup required"}
                  </Badge>
                </div>
              ))}
            {health?.database && (
              <div className="health-item">
                <span>Database</span>
                <Badge
                  value={
                    health.database.status === "unavailable" ? "failed" : "pass"
                  }
                >
                  {human(health.database.status || "Checked")}
                </Badge>
              </div>
            )}
            {reference && (
              <div className="health-item">
                <span>Procurement snapshot</span>
                <Badge value={reference.fresh ? "pass" : "pending"}>
                  {reference.fresh ? "Current" : "Sync required"}
                </Badge>
              </div>
            )}
          </div>
          {health?.capacity_limits && <p className="small-muted">Pending-work limits: {health.capacity_limits.per_user} per user · {health.capacity_limits.workspace} for the workspace.</p>}
          {reference?.imported_at && (
            <p className="small-muted">
              Last imported {dateTime(reference.imported_at)}
              {reference.valid_until
                ? ` · Valid until ${dateTime(reference.valid_until)}`
                : ""}
            </p>
          )}
          {!health && busy === "health" && (
            <p className="muted" role="status">
              Checking services…
            </p>
          )}
          <div className="button-row">
            <button
              className="secondary"
              disabled={Boolean(busy)}
              onClick={() => action("sync")}
            >
              {busy === "sync" ? "Syncing…" : "Sync procurement now"}
            </button>
            <button
              className="secondary"
              disabled={Boolean(busy)}
              onClick={() => action("publication")}
            >
              {busy === "publication"
                ? "Requesting…"
                : "Retry spreadsheet publication"}
            </button>
            <button
              className="text-button"
              disabled={Boolean(busy)}
              onClick={inspect}
            >
              Refresh health
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function App() {
  const pageFromHash = () => parseRoute(location.hash).page;
  const [page, setPage] = useState(pageFromHash);
  const [user, setUser] = useState(null);
  const [starting, setStarting] = useState(true);
  const [loginError, setLoginError] = useState("");
  const [workspace, setWorkspace] = useState(null);
  const [listError, setListError] = useState("");
  const [listLoading, setListLoading] = useState(false);
  const [selected, setSelectedState] = useState(
    () => parseRoute(location.hash).invoiceId,
  );
  const setSelected = (id) => {
    setSelectedState(id);
    selectedRef.current = id;
    if (page === "invoices" || id)
      history.pushState(null, "", id ? `#invoices/${id}` : "#invoices");
  };
  const selectedRef = useRef(null);
  const [data, setData] = useState(null);
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [filter, setFilter] = useState("all");
  const [vendor, setVendor] = useState("all");
  const [listVendor, setListVendor] = useState("all");
  const [currency, setCurrency] = useState("INR");
  const [search, setSearch] = useState("");
  const scrollArea = useRef(null);
  useEffect(() => {
    scrollArea.current?.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [page, selected]);
  const mounted = useRef(true);
  const generation = useRef(0);
  const flight = useRef(null);
  const detailRequest = useRef(0);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );
  useEffect(() => {
    const change = () => {
      const route = parseRoute(location.hash);
      setPage(route.page);
      setSelectedState(route.invoiceId);
      selectedRef.current = route.invoiceId;
    };
    window.addEventListener("hashchange", change);
    window.addEventListener("popstate", change);
    return () => {
      window.removeEventListener("hashchange", change);
      window.removeEventListener("popstate", change);
    };
  }, []);
  const navigate = (next) => {
    setPage(next);
    setSelectedState(null);
    selectedRef.current = null;
    location.hash = next;
  };
  const request = useCallback(async (url, options = {}) => {
    const epoch = generation.current;
    try {
      return await apiRequest(url, options);
    } catch (error) {
      if (
        error.status === 401 &&
        url !== "/api/auth/login" &&
        mounted.current &&
        epoch === generation.current
      ) {
        setUser(null);
        setWorkspace(null);
        setData(null);
        setSelectedState(null);
        selectedRef.current = null;
      }
      throw error;
    }
  }, []);
  const loadWorkspace = useCallback(() => {
    if (flight.current) return flight.current;
    const epoch = generation.current;
    setListLoading(true);
    const promise = request("/api/workspace")
      .then((result) => {
        if (epoch !== generation.current || !mounted.current) return;
        setWorkspace(result);
        setUser((old) =>
          old?.id === result.actor.id && old?.role === result.actor.role
            ? old
            : result.actor,
        );
        setListError("");
        return result;
      })
      .catch((err) => {
        if (epoch === generation.current) {
          setListError(err.message);
          if (err.status !== 401) setLoginError(err.message);
        }
      })
      .finally(() => {
        if (flight.current === promise) flight.current = null;
        if (mounted.current) setListLoading(false);
      });
    flight.current = promise;
    return promise;
  }, [request]);
  useEffect(() => {
    loadWorkspace().finally(() => setStarting(false));
  }, [loadWorkspace]);
  useEffect(() => {
    if (user && !workspace) loadWorkspace();
  }, [user?.id, workspace, loadWorkspace]);
  useEffect(() => {
    if (!user) return;
    let stopped = false,
      timer;
    const poll = async () => {
      if (!document.hidden) await loadWorkspace();
      if (!stopped) timer = setTimeout(poll, 30000);
    };
    timer = setTimeout(poll, 30000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [user?.id, loadWorkspace]);
  const loadDetail = useCallback(async () => {
    const id = selectedRef.current;
    if (!id) return;
    const serial = ++detailRequest.current;
    setDetailLoading(true);
    try {
      const result = await request(
        `/api/submissions/${encodeURIComponent(id)}`,
      );
      if (selectedRef.current === id && detailRequest.current === serial) {
        setData(result);
        setDetailError("");
      }
    } catch (err) {
      if (selectedRef.current === id && detailRequest.current === serial)
        setDetailError(err.message);
    } finally {
      if (selectedRef.current === id && detailRequest.current === serial)
        setDetailLoading(false);
    }
  }, [request]);
  useEffect(() => {
    selectedRef.current = selected;
    setData(null);
    setDetailError("");
    if (selected && user) loadDetail();
  }, [selected, user?.id, loadDetail]);
  useEffect(() => {
    if (!selected || !data) return;
    const running = activeRun(data),
      pending = data.acceptance && data.publication?.status !== "published";
    if (!running && !pending) return;
    let stopped = false,
      timer;
    const poll = async () => {
      if (!document.hidden) {
        await loadDetail();
        await loadWorkspace();
      }
      if (!stopped) timer = setTimeout(poll, running ? 2500 : 10000);
    };
    timer = setTimeout(poll, running ? 2500 : 10000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [
    selected,
    data?.submission?.status,
    data?.run?.state,
    data?.acceptance?.id,
    data?.publication?.status,
    loadDetail,
    loadWorkspace,
  ]);
  const register = useInvoiceRegister({
    enabled: Boolean(user && page === "invoices" && !selected),
    request, user, status: filter, vendor: listVendor, search,
  });
  const refresh = async () => {
    register.refresh();
    await Promise.all([loadWorkspace(), loadDetail()]);
  };
  const openInvoices = (company = "all", status = "all") => {
    setListVendor(company);
    setFilter(status === "needs_review" ? "review_queue" : status);
    setSearch("");
    navigate("invoices");
  };
  async function logout() {
    await request("/api/auth/logout", { method: "POST", body: "{}" });
    generation.current++;
    flight.current = null;
    setUser(null);
    setWorkspace(null);
    setData(null);
    setSelectedState(null);
    selectedRef.current = null;
    setVendor("all");
    setListVendor("all");
    setFilter("all");
    setSearch("");
    setPage("upload");
    history.replaceState(null, "", "#upload");
  }
  if (starting)
    return (
      <div className="app-loading" role="status">
        <BrandMark /><div><strong>Opening your workspace…</strong><p>Checking your session and connecting to the workspace.</p></div>
      </div>
    );
  if (!user)
    return (
      <Login
        onLogin={(actor) => {
          generation.current++;
          flight.current = null;
          setUser(actor);
          setWorkspace(null);
          setLoginError("");
          const destination = parseRoute(location.hash);
          setSelectedState(destination.invoiceId);
          if (!destination.invoiceId) {
            setPage("upload");
            history.replaceState(null, "", "#upload");
          }
        }}
        initialError={loginError}
        request={request}
      />
    );
  const items = workspace?.items || [];
  const visible = register.items;
  const names = {
    dashboard: [
      "Dashboard",
      "A clear view of invoices, vendors and commitments.",
    ],
    upload: [
      "Upload invoice",
      "Verify a document against your approved procurement records.",
    ],
    invoices: [
      "Invoices",
      "Find an invoice and inspect its evidence and decision.",
    ],
  };
  const navItems = [
    ["upload", "↑", "Upload invoice"],
    ["dashboard", "◫", "Dashboard"],
    ["invoices", "▤", "Invoices"],
  ];
  const nav = (mobile = false) => (
    <nav
      className={mobile ? "mobile-nav" : ""}
      aria-label={mobile ? "Mobile workspace" : "Workspace"}
    >
      {!mobile && <span className="nav-label">WORKSPACE</span>}
      {navItems.map(([key, icon, label]) => (
        <button
          key={key}
          className={`nav-item ${page === key ? "selected" : ""}`}
          aria-current={page === key ? "page" : undefined}
          onClick={() => navigate(key)}
        >
          <span aria-hidden="true">{icon}</span>
          {label}
          {key === "invoices" && !mobile && (
            <span className="nav-count">{workspace?.total_count ?? "—"}</span>
          )}
        </button>
      ))}
    </nav>
  );
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <a href="#upload" className="brand">
          <BrandMark />
          <span>
            Invoice review<small>PROCUREMENT OPERATIONS</small>
          </span>
        </a>
        <div className="workspace-tag">
          <span className="workspace-avatar">A</span>
          <span>
            Procurement workspace
            <small>
              {user.role === "admin"
                ? "Workspace-wide access"
                : "Your invoice workspace"}
            </small>
          </span>
        </div>
        {nav()}
        <div className="sidebar-note">
          <strong>One traceable record</strong>
          <p>
            Accepted invoices are recorded once. Spreadsheet publication is
            tracked separately.
          </p>
        </div>
        <div className="user-row">
          <span className="user-avatar">
            {user.display_name?.[0]?.toUpperCase() || "U"}
          </span>
          <span>
            <strong>{user.display_name || "Workspace user"}</strong>
            <small>{human(user.role)}</small>
          </span>
          <LogoutControl onConfirm={logout} />
        </div>
      </aside>
      <main className="workspace" ref={scrollArea}>
        {nav(true)}
        <header className="page-header">
          <div>
            <div className="breadcrumbs">
              Workspace <span>/</span>
              {names[page][0]}
            </div>
            <h1>{names[page][0]}</h1>
            <p>{names[page][1]}</p>
          </div>
          <button
            className="secondary compact"
            onClick={refresh}
            disabled={listLoading}
          >
            {listLoading ? "↻ Updating…" : "↻ Refresh"}
          </button>
        </header>
        <ErrorBox>{listError}</ErrorBox>
        {page === "dashboard" && (
          <>
            <Dashboard
              workspace={workspace}
              vendor={vendor}
              setVendor={setVendor}
              currency={currency}
              setCurrency={setCurrency}
              onInvoices={openInvoices}
            />
            {user.role === "admin" && (
              <AdminPanel request={request} onRefresh={refresh} />
            )}
          </>
        )}
        {page === "upload" && (
          <div className="upload-page">
            <Upload
              request={request}
              onUpload={(id) => {
                setPage("invoices");
                history.replaceState(null, "", `#invoices/${id}`);
                setSelectedState(id);
                selectedRef.current = id;
                loadWorkspace();
              }}
            />
            <div className="upload-explainer">
              <span className="eyebrow muted">FROM DOCUMENT TO DECISION</span>
              <h2>Upload once. Understand every check.</h2>
              <div className="upload-steps">
                {[
                  [
                    "01",
                    "Read the source",
                    "Invoice details are linked to the printed source so you can review the evidence.",
                  ],
                  [
                    "02",
                    "Verify the evidence",
                    "Vendor, PO, amounts, tax, duplicates and remaining balance are checked.",
                  ],
                  [
                    "03",
                    "Record the outcome",
                    "Clear matches are accepted. Unreadable or conflicting fields go to review.",
                  ],
                ].map(([n, title, copy]) => (
                  <article key={n}>
                    <b>{n}</b>
                    <h3>{title}</h3>
                    <p>{copy}</p>
                  </article>
                ))}
              </div>
              <p className="notice">
                An unreadable total stays unknown. A clearer replacement is
                required before it can pass verification.
              </p>
            </div>
            <section className="section-card">
              <div className="section-heading">
                <h2>Recent uploads</h2>
                <button className="text-button" onClick={() => openInvoices()}>
                  View all invoices →
                </button>
              </div>
              {items.slice(0, 4).map((item) => (
                <button
                  key={item.id}
                  className="recent-upload"
                  onClick={() => {
                    navigate("invoices");
                    setSelected(item.id);
                  }}
                >
                  <span>
                    {item.original_filename}
                    <small>{dateTime(item.created_at)}</small>
                  </span>
                  <Badge value={item.status} />
                </button>
              ))}
              {!items.length && (
                <p className="muted">Your uploads will appear here.</p>
              )}
            </section>
          </div>
        )}
        {page === "invoices" &&
          (selected ? (
            <div className="invoice-detail-page">
              <button
                className="text-button back-button"
                onClick={() => setSelected(null)}
              >
                ← Back to invoice list
              </button>
              <Detail
                data={data}
                loading={detailLoading}
                error={detailError}
                user={user}
                request={request}
                onUpdate={refresh}
              />
            </div>
          ) : (
            <section className="section-card invoice-list-page">
              <div className="section-heading">
                <div>
                  <h2>Invoice register</h2>
                  <p className="small-muted">
                    {workspace?.scope === "company"
                      ? "All workspace uploads"
                      : "Your uploads"}{" "}
                    · {visible.length} shown{register.total !== null ? ` of ${register.total} matching` : ""}
                    {register.loading ? " · Updating…" : ""}
                  </p>
                </div>
                <button className="primary" onClick={() => navigate("upload")}>
                  + Upload invoice
                </button>
              </div>
              <ErrorBox>{register.error}</ErrorBox>
              <div className="invoice-toolbar">
                <input
                  aria-label="Search invoices"
                  type="search"
                  placeholder="Search invoice, vendor, PO or filename…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <CompanySelect
                  vendors={workspace?.vendors || []}
                  value={listVendor}
                  onChange={setListVendor}
                />
                <label className="toolbar-select">
                  Status
                  <select
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="all">All statuses</option>
                    <option value="review_queue">Review queue</option>
                    {[
                      "received",
                      "processing",
                      "accepted",
                      "needs_review",
                      "blocked_duplicate",
                      "rejected",
                      "processing_failed",
                      "reference_hold",
                      "expired",
                    ].map((v) => (
                      <option value={v} key={v}>
                        {human(v)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="table-scroll">
                <table className="data-table invoice-table">
                  <thead>
                    <tr>
                      <th>Invoice</th>
                      <th>Vendor / supplier</th>
                      <th>Amount</th>
                      <th>Decision</th>
                      <th>Uploaded</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <button
                            className="invoice-link"
                            onClick={() => setSelected(item.id)}
                          >
                            {item.invoice_number || item.original_filename}
                          </button>
                          <small>
                            {item.invoice_number
                              ? item.original_filename
                              : "Number not extracted yet"}
                          </small>
                        </td>
                        <td>
                          {item.vendor_name || "Awaiting extraction"}
                          <small>{item.po_code || "No PO resolved"}</small>
                        </td>
                        <td>
                          <strong>
                            {money(
                              item.accepted_minor ?? item.requested_minor,
                              item.currency,
                            )}
                          </strong>
                          {item.status !== "accepted" &&
                            item.requested_minor != null && (
                              <small>
                                {item.status === "blocked_duplicate"
                                  ? "Duplicate · no new commitment"
                                  : "Extracted · unapproved"}
                              </small>
                            )}
                        </td>
                        <td>
                          <Badge value={item.status} />
                          {item.acceptance_id && (
                            <small>
                              {publicationLabel(item.publication_status, true)}
                            </small>
                          )}
                        </td>
                        <td>{dateTime(item.created_at)}</td>
                        <td>
                          <button
                            className="text-button"
                            aria-label={`View ${item.original_filename}`}
                            onClick={() => setSelected(item.id)}
                          >
                            View ↗
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="invoice-cards">
                  {visible.map((item) => (
                    <button
                      key={item.id}
                      className="invoice-mobile-card"
                      aria-label={`View ${item.original_filename}`}
                      onClick={() => setSelected(item.id)}
                    >
                      <span>
                        <strong>{item.invoice_number || "Invoice"}</strong>
                        <Badge value={item.status} />
                      </span>
                      <small>{item.original_filename}</small>
                      <p>{item.vendor_name || "Awaiting extraction"}</p>
                      <span>
                        <strong>
                          {money(
                            item.accepted_minor ?? item.requested_minor,
                            item.currency,
                          )}
                        </strong>
                        <small>{item.po_code || "No PO resolved"}</small>
                      </span>
                      <small>
                        {dateTime(item.created_at)}
                        {item.acceptance_id
                          ? ` · ${publicationLabel(item.publication_status, true)}`
                          : ""}
                      </small>
                    </button>
                  ))}
                </div>
                {(filter !== "all" || listVendor !== "all" || search) && (
                  <button
                    className="text-button clear-filters"
                    onClick={() => {
                      setFilter("all");
                      setListVendor("all");
                      setSearch("");
                    }}
                  >
                    Clear invoice filters
                  </button>
                )}
                {!visible.length &&
                  (register.loading ? (
                    <p className="list-loading" role="status">
                      Loading invoices…
                    </p>
                  ) : (
                    <Empty
                      title={
                        search || listVendor !== "all" || filter !== "all"
                          ? "No matching invoices"
                          : "No invoices yet"
                      }
                    >
                      Upload a document or adjust the filters.
                    </Empty>
                  ))}
              </div>
              <nav className="register-pagination" aria-label="Invoice list pages">
                <span className="small-muted">Page {register.page} · Search covers the full invoice history</span>
                <div>
                  <button className="secondary" disabled={register.loading || !register.hasPrevious} onClick={register.previous}>← Previous</button>
                  <button className="secondary" disabled={register.loading || !register.hasNext} onClick={register.next}>Next →</button>
                </div>
              </nav>
            </section>
          ))}
        <footer className="workspace-footer">
          Procurement verification · Acceptance does not execute payment
        </footer>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);

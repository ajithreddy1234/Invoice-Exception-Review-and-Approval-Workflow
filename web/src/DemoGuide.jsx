import React, { useEffect, useState } from "react";

export default function DemoGuide({ request, onUpload }) {
  const [data, setData] = useState(null);
  const [pack, setPack] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true); setError("");
    try {
      const next = await request("/api/demo");
      setData(next);
      setPack(current => next.packs.some(p => p.pack === current) ? current :
        (next.packs.find(p => p.prepared && !p.used)?.pack || next.packs[0]?.pack || ""));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  useEffect(() => { load(); }, [request]);
  const selected = data?.packs.find(p => p.pack === pack);
  return <div className="demo-guide detail-stack">
    <section className="section-card">
      <span className="eyebrow muted">TRY THE WORKFLOW</span>
      <h2>A fresh invoice, a clear result</h2>
      <p>Download a sample, open Upload invoice, and choose the downloaded PDF. Watch the processing stages, then compare its source evidence with the decision.</p>
      <p><strong>This prototype records invoice decisions. It does not execute payments.</strong></p>
      <div className="button-row">
        <button className="primary" onClick={onUpload}>Open Upload invoice</button>
        <button className="secondary" onClick={load} disabled={busy}>{busy ? "Checking…" : "Refresh sample availability"}</button>
      </div>
    </section>
    <section className="section-card">
      <h2>Choose a demo pack</h2>
      <p>Each pack has independent invoice identities and purchase-order budgets. Packs are shared across this workspace. Previously accepted samples must be blocked as duplicates; their budget is never reset.</p>
      {error && <p className="error-box" role="alert">{error}</p>}
      {!data && !error && <p role="status">Checking reference data and sample availability…</p>}
      {data && <>
        <div className="demo-pack-select"><label htmlFor="demo-pack-choice">Demo pack</label>
          <select id="demo-pack-choice" value={pack} onChange={e => setPack(e.target.value)}>
            {data.packs.map(p => <option key={p.pack} value={p.pack}>Pack {p.pack} · {!p.prepared ? "Preparation needed" : p.used ? "Previously used" : "Unused"}</option>)}
          </select>
        </div>
        {!data.reference_fresh && <p className="notice warning-note">Procurement references need a refresh. Ask an admin to sync before expecting automatic acceptance.</p>}
        {selected && <>
          <p className={`notice ${!selected.prepared || selected.used ? "warning-note" : ""}`}>
            {!selected.prepared ? "This pack’s purchase orders are not ready. Ask an admin to prepare and import its references." : selected.used ? "This pack has accepted invoices. Use its history and duplicate checks, or choose an unused pack for a fresh happy path." : "This pack has not consumed any PO budget. Start with 01_clean_invoice.pdf."}
          </p>
          <a className="secondary demo-download" href={selected.download_url} download>Download pack {selected.pack} · 7 PDFs and instructions</a>
          <div className="demo-scenarios">
            {selected.fixtures.map((f,index) => <article className="demo-scenario" key={f.file}>
              <span className="eyebrow muted">{String(index+1).padStart(2,"0")} · {f.title}</span>
              <a href={`/api/demo/packs/${selected.pack}/files/${encodeURIComponent(f.file)}`} download>{f.file} ↓</a>
              <p><strong>Expected:</strong> {f.expected}</p>
              <p className="small-muted">{f.prerequisite}</p>
            </article>)}
          </div>
          <p className="small-muted">These are scenario expectations, not preprogrammed results. Every upload runs the same extraction, evidence and financial checks.</p>
        </>}
      </>}
    </section>
    <section className="section-card">
      <h2>Understand the statuses</h2>
      <dl className="demo-legend">
        <dt>Processing</dt><dd>The document is being read, extracted and checked. A temporarily busy extraction service is retried once.</dd>
        <dt>Accepted</dt><dd>The invoice is recorded once and consumes its authorized PO balance.</dd>
        <dt>Needs review</dt><dd>A check or critical source field is unresolved. No balance is consumed.</dd>
        <dt>Blocked duplicate</dt><dd>An accepted file or vendor/invoice identity already exists. No second commitment is made.</dd>
        <dt>Rejected</dt><dd>An admin recorded a rejection with a reason.</dd>
        <dt>Processing failed</dt><dd>The run could not finish. It is not an approval; retry when the dependency/source issue is resolved.</dd>
        <dt>Report pending / published</dt><dd>Spreadsheet publication is separate from acceptance. Pending publication can retry without accepting again.</dd>
      </dl>
    </section>
    <section className="section-card">
      <h2>Assumptions and limitations</h2>
      <ul>
        <li>One procurement workspace, supported INR/USD rules and English OCR. No currency conversion or tax-law verification.</li>
        <li>Invoice PDFs are the primary input. JPEG/PNG scans are supported; uploads are limited to 5 MiB and three pages.</li>
        <li>A payable total needs its own readable source evidence. An unreadable value stays unknown.</li>
        <li>Only admins resolve exceptions, reject or explicitly approve eligible corrections. They cannot bypass failed checks.</li>
        <li>Original uploads are private and expire after seven days. Hashes, extracted evidence and the decision ledger remain.</li>
        <li>No payment, email delivery, generated output invoice or ERP integration. A clearer-document request is an in-app record.</li>
        <li>The service can pause when inactive. Allow it to start before testing; OCR/model work can take tens of seconds.</li>
        <li>Live model requests are required. No saved extraction cache is used; unavailable dependencies hold processing.</li>
      </ul>
    </section>
  </div>;
}

import React from "react";
import { human } from "./model.js";

import { money, dashboardView } from "./dashboard-model.js";
export { money } from "./dashboard-model.js";
export function CompanySelect({ vendors, value, onChange }) {
  return (
    <label className="toolbar-select">
      Vendor / supplier
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="all">All vendors</option>
        {vendors.map((v) => (
          <option value={v.vendor_code} key={v.vendor_code}>
            {v.legal_name}
          </option>
        ))}
        <option value="unmatched">Unmatched vendor</option>
      </select>
    </label>
  );
}
export default function Dashboard({
  workspace,
  vendor,
  setVendor,
  currency,
  setCurrency,
  onInvoices,
}) {
  if (!workspace)
    return (
      <div className="section-card" role="status">
        Loading dashboard…
      </div>
    );
  const v = dashboardView(workspace, vendor, currency);
  const admin = workspace.scope === "company";
  const currencies = [
    ...new Set(
      [
        "INR",
        ...workspace.company_totals.map((x) => x.currency),
        ...workspace.po_balances.map((x) => x.currency),
      ].filter(Boolean),
    ),
  ];
  const max = Math.max(1, ...v.companies.map((c) => c.accepted_minor));
  const now = new Date(workspace.generated_at);
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - 13 + i);
    const day = d.toISOString().slice(0, 10);
    return {
      day,
      count: v.daily
        .filter((x) => x.day === day)
        .reduce((n, x) => n + Number(x.invoice_count), 0),
    };
  });
  const maxDay = Math.max(1, ...days.map((d) => d.count));
  return (
    <div className="dashboard-stack">
      <div className="dashboard-toolbar">
        <div>
          <span className="scope-tag">
            {admin ? "Workspace overview" : "Your submissions"}
          </span>
          <p className="small-muted">
            Sheet vendors · accepted values from the ledger · all visible
            records
          </p>
        </div>
        <div className="dashboard-filters">
          <CompanySelect
            vendors={workspace.vendors}
            value={vendor}
            onChange={setVendor}
          />
          <label className="toolbar-select">
            Currency
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {currencies.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="kpi-grid">
        <article className="kpi-card accent">
          <span>Accepted invoice value</span>
          <strong>{money(v.accepted_minor, currency)}</strong>
          <small>{v.accepted_count} accepted · recorded once</small>
        </article>
        <article className="kpi-card">
          <span>Invoices</span>
          <strong>{v.invoice_count}</strong>
          <small>Within selected vendor and currency</small>
        </article>
        <article className="kpi-card">
          <span>Needs review</span>
          <strong>{v.review_count}</strong>
          <small>
            {money(v.review_minor, currency)} readable value · unapproved
          </small>
        </article>
        <article className="kpi-card">
          <span>Duplicates blocked</span>
          <strong>{v.duplicate_count}</strong>
          <small>No additional PO commitment</small>
        </article>
      </div>
      <div className="dashboard-columns">
        <section className="section-card company-chart">
          <div className="section-heading">
            <div>
              <h2>Accepted invoice value by vendor</h2>
              <p className="small-muted">
                {currency} · select a vendor to see its invoices
              </p>
            </div>
            <span className="chart-key">
              <i />
              Accepted
            </span>
          </div>
          {v.companies.length ? (
            v.companies.map((c) => (
              <button
                className="company-bar-row"
                key={c.vendor_code}
                onClick={() => onInvoices(c.vendor_code)}
                title={`View invoices for ${c.legal_name}`}
              >
                <span className="company-bar-name">
                  {c.legal_name}
                  <small>
                    {c.invoice_count} invoices · {c.review_count} need review
                    {c.approved === false ? " · unapproved vendor" : ""}
                  </small>
                </span>
                <span className="company-bar-track">
                  <span
                    style={{ width: `${(c.accepted_minor / max) * 100}%` }}
                  />
                </span>
                <strong>{money(c.accepted_minor, currency)}</strong>
                <span aria-hidden="true">↗</span>
              </button>
            ))
          ) : (
            <p className="muted">No vendors in the imported reference yet.</p>
          )}
          <p className="chart-note">
            Only accepted ledger amounts count. Duplicates, rejected invoices
            and review amounts are excluded. Zero-value vendors remain visible.
          </p>
        </section>
        <section className="section-card">
          <div className="section-heading">
            <div>
              <h2>Review & publication</h2>
              <p className="small-muted">What needs attention next</p>
            </div>
          </div>
          <div className="attention-card">
            <span className="attention-number">{v.review_count}</span>
            <div>
              <strong>Invoices awaiting review</strong>
              <p>{v.unreadable_amount_count} without a readable total</p>
            </div>
          </div>
          <div className="attention-card">
            <span className="attention-number amber">
              {v.publication_pending_count}
            </span>
            <div>
              <strong>Accepted, report pending</strong>
              <p>Acceptance remains recorded while publication retries.</p>
            </div>
          </div>
          <button
            className="secondary full"
            onClick={() => onInvoices(vendor, "needs_review")}
          >
            Open review queue <span>→</span>
          </button>
          <p className="chart-note">
            Unknown currency contributes to counts only. No value is inferred
            from a purchase order.
          </p>
        </section>
      </div>
      <div className="dashboard-columns">
        <section className="section-card">
          <div className="section-heading">
            <div>
              <h2>Invoice activity</h2>
              <p className="small-muted">Uploads over the last 14 days · UTC</p>
            </div>
            <span className="small-muted">
              {days.reduce((n, d) => n + d.count, 0)} uploads
            </span>
          </div>
          <div
            className="activity-chart"
            role="img"
            aria-label="Daily uploaded invoice counts"
          >
            {days.map((d) => (
              <div
                className="activity-column"
                key={d.day}
                title={`${d.day}: ${d.count} uploads`}
              >
                <span>{d.count || ""}</span>
                <div className="activity-well">
                  <i style={{ height: `${(d.count / maxDay) * 100}%` }} />
                </div>
                <small>{d.day.slice(8)}</small>
              </div>
            ))}
          </div>
        </section>
        <section className="section-card">
          <div className="section-heading">
            <div>
              <h2>Decision overview</h2>
              <p className="small-muted">Selected vendor and currency</p>
            </div>
          </div>
          <div className="decision-counts">
            {[
              ["Accepted", v.accepted_count, "accepted"],
              ["Needs review", v.review_count, "review"],
              ["Duplicates", v.duplicate_count, "duplicate"],
              [
                "Other / processing",
                v.invoice_count -
                  v.accepted_count -
                  v.review_count -
                  v.duplicate_count,
                "other",
              ],
            ].map(([label, n, tone]) => (
              <div key={label}>
                <span>
                  <i className={tone} />
                  {label}
                </span>
                <strong>{n}</strong>
                <div className="decision-mini-track">
                  <i
                    className={tone}
                    style={{
                      width: `${v.invoice_count ? (n / v.invoice_count) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
      {admin && (
        <section className="section-card">
          <div className="section-heading">
            <div>
              <h2>Purchase order balances</h2>
              <p className="small-muted">
                Authorized amounts from the active Sheet reference. Accepted
                commitments from Postgres.
              </p>
            </div>
            <span className="small-muted">{v.po.length} POs</span>
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Purchase order</th>
                  <th>Vendor</th>
                  <th>Authorized</th>
                  <th>Accepted</th>
                  <th>Remaining</th>
                  <th>Utilization</th>
                </tr>
              </thead>
              <tbody>
                {v.po.map((p) => (
                  <tr key={p.po_code}>
                    <td>
                      <strong>{p.po_code}</strong>
                      <small>{human(p.status)}</small>
                    </td>
                    <td>{p.vendor_name}</td>
                    <td>{money(p.authorized_gross_minor, currency)}</td>
                    <td>{money(p.accepted_minor, currency)}</td>
                    <td>
                      <strong>{money(p.remaining_minor, currency)}</strong>
                    </td>
                    <td>
                      <div className="po-meter">
                        <i
                          style={{
                            width: `${Math.min(100, Math.max(0, (p.accepted_minor / p.authorized_gross_minor) * 100))}%`,
                          }}
                        />
                      </div>
                      <small>
                        {Math.round(
                          (p.accepted_minor / p.authorized_gross_minor) * 100,
                        )}
                        % used
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!v.po.length && (
              <p className="muted">No matching purchase orders.</p>
            )}
          </div>
        </section>
      )}
      <p className="dashboard-footnote">
        {admin
          ? "Workspace totals"
          : "Only your uploaded invoices are included"}
        . Charts cover all visible records; the invoice list shows the latest{" "}
        {workspace.list_limit}. Updated{" "}
        {new Date(workspace.generated_at).toLocaleTimeString()}.{" "}
        {workspace.reference?.fresh
          ? "Procurement reference is current."
          : "Procurement reference requires a refresh."}
      </p>
    </div>
  );
}

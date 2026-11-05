import React, { useRef, useState, useId } from "react";

function LogoutIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M15 8l4 4-4 4M8 12h11" />
  </svg>;
}

export default function LogoutControl({ onConfirm }) {
  const dialog = useRef(null);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const titleId = useId(), descriptionId = useId();
  function open() {
    setError("");
    if (!dialog.current.open) dialog.current.showModal();
  }
  function keepFocus(event) {
    if (event.key !== "Tab") return;
    const buttons = [...dialog.current.querySelectorAll("button:not(:disabled)")];
    if (!buttons.length) { event.preventDefault(); return; }
    const first = buttons[0], last = buttons[buttons.length - 1];
    if (event.shiftKey && (event.target === first || event.target === dialog.current)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (event.target === last || event.target === dialog.current)) {
      event.preventDefault(); first.focus();
    }
  }
  async function confirm() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError("");
    try {
      await onConfirm();
      dialog.current?.close();
    } catch (err) {
      setError(err.message || "We could not log you out. Please try again.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return <>
    <button type="button" className="logout-button" onClick={open}>
      <LogoutIcon /><span>Log out</span>
    </button>
    <dialog ref={dialog} className="logout-dialog" aria-labelledby={titleId} aria-describedby={descriptionId} tabIndex={-1} onKeyDown={keepFocus}
      onCancel={event => { if (inFlight.current) event.preventDefault(); }}>
      <div className="logout-dialog-icon"><LogoutIcon /></div>
      <h2 id={titleId}>Log out of your workspace?</h2>
      <p id={descriptionId}>You’ll return to the sign-in page. Saved invoices will remain available. Any unsubmitted changes will be lost.</p>
      {error && <p className="error-box" role="alert">{error}</p>}
      <div className="logout-dialog-actions">
        <button type="button" className="secondary" autoFocus disabled={busy} onClick={() => dialog.current.close()}>Cancel</button>
        <button type="button" className="primary" disabled={busy} onClick={confirm}>{busy ? "Logging out…" : "Log out"}</button>
      </div>
    </dialog>
  </>;
}

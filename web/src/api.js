import { readableError } from "./model.js";

export async function apiRequest(url, options = {}, { fetchImpl = fetch, timeoutMs } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs ?? (url.endsWith("/correct") ? 150000 : 30000));
  try {
    const response = await fetchImpl(url, {
      credentials: "same-origin", ...options, signal: controller.signal,
      headers: {
        ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
    // Render may return a host-generated HTML wake-up/error page, even with
    // status 200. It is never a valid login, upload receipt or decision.
    if (!response.headers.get("content-type")?.includes("application/json")) {
      const error = new Error("The service is starting or temporarily unavailable. Allow about a minute, then try again. Your request has not been confirmed.");
      error.status = response.status >= 400 ? response.status : 503;
      throw error;
    }
    let body;
    try { body = await response.json(); }
    catch (err) {
      if (err.name === "AbortError") throw err;
      throw new Error("The service returned an incomplete response. Refresh and check the invoice history before retrying a decision.");
    }
    if (!body || typeof body !== "object") throw new Error("The service returned an invalid response. Please try again.");
    if (!response.ok) {
      const message = ["DATABASE_NOT_READY", "DATABASE_OPERATION_FAILED"].includes(body.detail)
        ? "The workspace database is temporarily unavailable. Wait a moment and try again."
        : readableError(body, `Request failed (${response.status}).`);
      const error = new Error(message); error.status = response.status; throw error;
    }
    return body;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("The service took too long to respond. It may be waking after inactivity. Allow about a minute, then try again; use the same upload retry to avoid creating another request.");
    if (err instanceof TypeError) throw new Error("Cannot reach the service. Check your connection and try again.");
    throw err;
  } finally { clearTimeout(timer); }
}

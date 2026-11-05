import { useEffect, useRef, useState } from "react";

// Read pages independently from dashboard summaries. A response from an old
// query, page or signed-in identity must never replace the current register.
export function useInvoiceRegister({ enabled, request, user, status, vendor, search }) {
  const query = search.trim();
  const scope = user ? `${user.id}:${user.role}` : "";
  const key = JSON.stringify([scope, status, vendor, query]);
  const [position, setPosition] = useState({ key: "", cursors: [null] });
  const cursors = position.key === key ? position.cursors : [null];
  const cursor = cursors[cursors.length - 1];
  const pageKey = JSON.stringify([key, cursor]);
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null);
  const [pending, setPending] = useState(null);
  const [revision, setRevision] = useState(0);
  const sequence = useRef(0);

  useEffect(() => {
    const serial = ++sequence.current;
    if (!enabled) return;
    setPending({ key: pageKey, value: true });
    const timer = setTimeout(async () => {
      const params = new URLSearchParams({ status, vendor, search: query, limit: "25" });
      if (cursor) params.set("cursor", cursor);
      try {
        const data = await request(`/api/invoices?${params}`);
        if (serial !== sequence.current) return;
        setResult({ ...data, key: pageKey });
        setFailure(null);
      } catch (error) {
        if (serial === sequence.current) setFailure({ key: pageKey, message: error.message });
      } finally {
        if (serial === sequence.current) setPending({ key: pageKey, value: false });
      }
    }, query ? 250 : 0);
    return () => { clearTimeout(timer); sequence.current++; };
  }, [enabled, pageKey, request, status, vendor, query, cursor, revision]);

  useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(() => { if (!document.hidden) setRevision(n => n + 1); }, 30000);
    return () => clearInterval(timer);
  }, [enabled, key]);

  const current = result?.key === pageKey ? result : null;
  return {
    items: current?.items || [],
    total: current?.total_count ?? null,
    page: cursors.length,
    loading: enabled && (pending?.key !== pageKey || pending.value),
    error: failure?.key === pageKey ? failure.message : "",
    hasPrevious: cursors.length > 1,
    hasNext: Boolean(current?.next_cursor),
    previous: () => { if (cursors.length > 1) setPosition({ key, cursors: cursors.slice(0, -1) }); },
    next: () => { if (current?.next_cursor) setPosition({ key, cursors: [...cursors, current.next_cursor] }); },
    refresh: () => setRevision(n => n + 1),
  };
}

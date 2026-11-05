"""One consistent, ownership-scoped read for the workspace and its charts."""
from fastapi import APIRouter, Depends, HTTPException, Request
from .auth import verified_user_id

router = APIRouter()

WORKSPACE_SQL = r'''
WITH actor AS MATERIALIZED (
 SELECT user_id,display_name,role FROM app.profiles WHERE user_id=%s AND enabled
), active AS (
 SELECT v.* FROM app.runtime_state t JOIN app.reference_versions v ON v.id=t.active_reference_version_id
 WHERE t.singleton
), vendors AS (
 SELECT v.* FROM app.reference_vendors v JOIN active a ON a.id=v.reference_version_id
), scoped AS MATERIALIZED (
 SELECT s.id,s.original_filename,s.status,s.created_at,s.updated_at,
   a.id AS acceptance_id,e.status AS publication_status,
   coalesce(a.invoice_number,r.invoice_number,dup.invoice_number) AS invoice_number,
   coalesce(a.currency,r.currency,dup.currency) AS currency,
   coalesce(r.total_gross_minor,dup.amount_minor) AS requested_minor,a.amount_minor AS accepted_minor,
   coalesce(a.po_code,p.po_code,dup.po_code) AS po_code,
   coalesce(a.vendor_code,p.vendor_code,m.vendor_code,dup.vendor_code) AS vendor_code,
   r.vendor_name AS printed_vendor_name
 FROM app.submissions s CROSS JOIN actor u
 LEFT JOIN app.invoice_revisions r ON r.id=s.current_revision_id
 LEFT JOIN app.acceptances a ON a.submission_id=s.id
 LEFT JOIN app.acceptances dup ON dup.document_sha256=s.file_sha256 AND s.status='blocked_duplicate'
 LEFT JOIN app.export_tasks e ON e.acceptance_id=a.id
 LEFT JOIN LATERAL (SELECT x.reference_version_id,x.po_code FROM app.validation_results x
   WHERE x.submission_id=s.id ORDER BY x.created_at DESC LIMIT 1) x ON true
 LEFT JOIN app.reference_pos p ON p.reference_version_id=x.reference_version_id AND p.po_code=x.po_code
 LEFT JOIN LATERAL (
   SELECT min(v.vendor_code) AS vendor_code FROM vendors v WHERE
     lower(regexp_replace(btrim(r.vendor_name),'\s+',' ','g')) = lower(regexp_replace(btrim(v.legal_name),'\s+',' ','g'))
     OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(v.aliases) alias
       WHERE lower(regexp_replace(btrim(r.vendor_name),'\s+',' ','g'))=lower(regexp_replace(btrim(alias),'\s+',' ','g')))
   HAVING count(*)=1
 ) m ON true
 WHERE u.role='admin' OR s.uploaded_by=u.user_id
), named AS MATERIALIZED (
 SELECT s.*,coalesce(v.legal_name,s.printed_vendor_name,'Unmatched vendor') AS vendor_name
 FROM scoped s LEFT JOIN vendors v ON v.vendor_code=s.vendor_code
), company AS (
 SELECT vendor_code,currency,count(*) AS invoice_count,
   count(*) FILTER(WHERE status='accepted') AS accepted_count,
   count(*) FILTER(WHERE status IN ('needs_review','reference_hold')) AS review_count,
   count(*) FILTER(WHERE status='blocked_duplicate') AS duplicate_count,
   count(*) FILTER(WHERE status IN ('received','processing')) AS processing_count,
   coalesce(sum(accepted_minor),0) AS accepted_minor,
   coalesce(sum(requested_minor) FILTER(WHERE status IN ('needs_review','reference_hold')),0) AS review_minor,
   count(*) FILTER(WHERE status IN ('needs_review','reference_hold') AND requested_minor IS NULL) AS unreadable_amount_count,
   count(*) FILTER(WHERE acceptance_id IS NOT NULL AND publication_status IS DISTINCT FROM 'published') AS publication_pending_count
 FROM named GROUP BY vendor_code,currency
), directory AS (
 SELECT vendor_code,legal_name,approved FROM vendors
 UNION ALL
 SELECT vendor_code,min(vendor_name),NULL::boolean FROM named s
 WHERE vendor_code IS NOT NULL AND NOT EXISTS(SELECT 1 FROM vendors v WHERE v.vendor_code=s.vendor_code)
 GROUP BY vendor_code
), po_used AS (
 SELECT po_code,sum(amount_minor) AS accepted_minor FROM app.acceptances GROUP BY po_code
), po_balances AS (
 SELECT p.po_code,p.vendor_code,v.legal_name AS vendor_name,p.currency,p.status,
   p.authorized_gross_minor,coalesce(b.accepted_minor,0) AS accepted_minor,
   p.authorized_gross_minor-coalesce(b.accepted_minor,0) AS remaining_minor
 FROM app.reference_pos p JOIN active a ON p.reference_version_id=a.id
 JOIN vendors v ON v.vendor_code=p.vendor_code LEFT JOIN po_used b ON b.po_code=p.po_code
 WHERE EXISTS(SELECT 1 FROM actor WHERE role='admin')
), daily AS (
 SELECT (created_at AT TIME ZONE 'UTC')::date AS day,currency,vendor_code,count(*) AS invoice_count,
   count(*) FILTER(WHERE status='accepted') AS accepted_count,
   count(*) FILTER(WHERE status IN ('needs_review','reference_hold')) AS review_count
 FROM named WHERE created_at>=((now() AT TIME ZONE 'UTC')::date-13) AT TIME ZONE 'UTC'
 GROUP BY 1,2,3
)
SELECT (SELECT to_jsonb(u) FROM actor u) AS actor,
 coalesce((SELECT jsonb_agg(to_jsonb(n) ORDER BY n.created_at DESC) FROM
   (SELECT * FROM named ORDER BY created_at DESC LIMIT 200) n),'[]') AS items,
 (SELECT count(*) FROM named) AS total_count,
 coalesce((SELECT jsonb_agg(to_jsonb(c)) FROM company c),'[]') AS company_totals,
 coalesce((SELECT jsonb_agg(to_jsonb(v) ORDER BY v.legal_name) FROM directory v),'[]') AS vendors,
 coalesce((SELECT jsonb_agg(to_jsonb(p) ORDER BY p.vendor_name,p.po_code) FROM po_balances p),'[]') AS po_balances,
 coalesce((SELECT jsonb_agg(to_jsonb(d) ORDER BY d.day) FROM daily d),'[]') AS daily,
 coalesce((SELECT jsonb_object_agg(status,n) FROM (SELECT status,count(*) n FROM named GROUP BY status) t),'{}') AS status_totals,
 (SELECT jsonb_build_object('id',id,'imported_at',imported_at,'valid_until',valid_until,
   'fresh',valid_until>now()) FROM active) AS reference,
 now() AS generated_at
'''


@router.get('/api/workspace')
def workspace(request: Request, user_id=Depends(verified_user_id)):
    # Role and rows share one DB snapshot. No role/financial cache, no per-vendor
    # requests, no live Sheet API calls in the page-rendering path.
    row = request.app.state.db.read_one(WORKSPACE_SQL, (user_id,))
    if not row['actor']:
        raise HTTPException(403, 'ACCOUNT_DISABLED_OR_UNPROVISIONED')
    actor = row['actor']
    row['actor'] = {'id': actor['user_id'], 'display_name': actor['display_name'], 'role': actor['role']}
    row['scope'] = 'company' if actor['role']=='admin' else 'your_invoices'
    row['list_limit'] = 200
    return row

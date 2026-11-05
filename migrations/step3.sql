-- Apply once as migration owner after schema v1.2. Existing rows are preserved.
BEGIN;
CREATE SEQUENCE IF NOT EXISTS app.export_sheet_row_seq START WITH 2;
ALTER TABLE app.export_tasks ADD COLUMN IF NOT EXISTS sheet_row bigint
  NOT NULL DEFAULT nextval('app.export_sheet_row_seq');
CREATE UNIQUE INDEX IF NOT EXISTS export_tasks_sheet_row_key ON app.export_tasks(sheet_row);
GRANT USAGE, SELECT ON SEQUENCE app.export_sheet_row_seq TO service_role;
-- Row locks need UPDATE privilege. Keep it inside a fixed, non-mutating helper
-- rather than weakening the reference-pointer and PO-account grants.
CREATE OR REPLACE FUNCTION app.lock_processing_context(p_submission_id uuid,p_po_code text,p_actor_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $$
DECLARE actor_role text;
BEGIN
  SELECT role INTO actor_role FROM app.profiles WHERE user_id=p_actor_id AND enabled;
  IF actor_role IS NULL THEN RAISE EXCEPTION 'ACTOR_DISABLED_OR_UNKNOWN'; END IF;
  PERFORM 1 FROM app.runtime_state WHERE singleton FOR SHARE;
  IF p_po_code IS NOT NULL THEN
    PERFORM 1 FROM app.po_accounts WHERE po_code=p_po_code FOR UPDATE;
  END IF;
  PERFORM 1 FROM app.submissions WHERE id=p_submission_id
    AND (uploaded_by=p_actor_id OR actor_role='admin') FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'SUBMISSION_NOT_FOUND_OR_FORBIDDEN'; END IF;
END;
$$;
REVOKE ALL ON FUNCTION app.lock_processing_context(uuid,text,uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION app.lock_processing_context(uuid,text,uuid) TO service_role;
COMMIT;

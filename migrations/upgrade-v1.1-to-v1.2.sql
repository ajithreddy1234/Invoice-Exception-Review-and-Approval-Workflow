-- Apply once as migration owner to an existing v1.1 schema.
-- Fresh projects use schema.sql instead. No table/data changes are needed.
BEGIN;
ALTER FUNCTION app.freeze_reference_rows() SECURITY DEFINER;
ALTER FUNCTION app.freeze_reference_rows() SET search_path = pg_catalog, app;
REVOKE ALL ON FUNCTION app.freeze_reference_rows() FROM PUBLIC, anon, authenticated, service_role;
COMMIT;

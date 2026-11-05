-- Invoice Review: Supabase/PostgreSQL schema, v1.2, 2026-11-01.
-- Apply once to a NEW development Supabase project as the migration owner.
-- Requires existing auth.users and Supabase roles: anon, authenticated, service_role.
-- This is a schema/acceptance foundation, NOT the complete application.
BEGIN;
CREATE SCHEMA app;
REVOKE ALL ON SCHEMA app FROM PUBLIC, anon, authenticated;

CREATE FUNCTION app.invoice_key(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT upper(regexp_replace(btrim(value), '[[:space:]]+', ' ', 'g'));
$$;

CREATE TABLE app.profiles (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id),
  display_name text NOT NULL,
  role text NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.reference_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status text NOT NULL DEFAULT 'building' CHECK (status IN ('building','valid','invalid')),
  source_spreadsheet_id text NOT NULL,
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  imported_by uuid REFERENCES app.profiles(user_id), -- NULL = system-triggered refresh.
  imported_at timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz NOT NULL,
  source_ranges jsonb NOT NULL,
  import_errors jsonb NOT NULL DEFAULT '[]',
  CHECK (valid_until > imported_at)
);

-- Stable PO identity and lock target. Importing a new reference version NEVER
-- replaces these rows or resets the accepted commitments.
CREATE TABLE app.po_accounts (
  po_code text PRIMARY KEY CHECK (length(btrim(po_code)) > 0),
  vendor_code text NOT NULL,
  currency text NOT NULL CHECK (currency IN ('INR','USD')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(po_code, vendor_code, currency)
);

CREATE TABLE app.reference_vendors (
  reference_version_id uuid NOT NULL REFERENCES app.reference_versions(id),
  vendor_code text NOT NULL,
  legal_name text NOT NULL,
  approved boolean NOT NULL,
  aliases jsonb NOT NULL DEFAULT '[]',
  tax_registration_id text,
  PRIMARY KEY(reference_version_id, vendor_code)
);

CREATE TABLE app.reference_pos (
  reference_version_id uuid NOT NULL REFERENCES app.reference_versions(id),
  po_code text NOT NULL,
  vendor_code text NOT NULL,
  currency text NOT NULL CHECK (currency IN ('INR','USD')),
  authorized_gross_minor bigint NOT NULL CHECK (authorized_gross_minor > 0),
  status text NOT NULL CHECK (status IN ('open','closed')),
  billing_mode text NOT NULL CHECK (billing_mode IN ('full','partial')),
  PRIMARY KEY(reference_version_id, po_code),
  FOREIGN KEY(reference_version_id, vendor_code)
    REFERENCES app.reference_vendors(reference_version_id, vendor_code),
  FOREIGN KEY(po_code, vendor_code, currency)
    REFERENCES app.po_accounts(po_code, vendor_code, currency)
);

CREATE TABLE app.reference_lines (
  reference_version_id uuid NOT NULL,
  po_code text NOT NULL,
  line_code text NOT NULL,
  description text NOT NULL,
  quantity numeric(18,4) NOT NULL CHECK (quantity > 0),
  unit text NOT NULL,
  unit_net_minor bigint NOT NULL CHECK (unit_net_minor >= 0),
  tax_rate_bps integer NOT NULL CHECK (tax_rate_bps BETWEEN 0 AND 10000),
  PRIMARY KEY(reference_version_id, po_code, line_code),
  FOREIGN KEY(reference_version_id, po_code)
    REFERENCES app.reference_pos(reference_version_id, po_code)
);

CREATE TABLE app.reference_rules (
  reference_version_id uuid NOT NULL REFERENCES app.reference_versions(id),
  currency text NOT NULL CHECK (currency IN ('INR','USD')),
  auto_accept_enabled boolean NOT NULL DEFAULT true,
  arithmetic_tolerance_minor bigint NOT NULL DEFAULT 100 CHECK (arithmetic_tolerance_minor BETWEEN 0 AND 100),
  price_tolerance_bps integer NOT NULL DEFAULT 0 CHECK (price_tolerance_bps BETWEEN 0 AND 100),
  PRIMARY KEY(reference_version_id, currency)
);

CREATE TABLE app.runtime_state (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  active_reference_version_id uuid REFERENCES app.reference_versions(id)
);
INSERT INTO app.runtime_state(singleton) VALUES (true);

CREATE TABLE app.submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uploaded_by uuid NOT NULL REFERENCES app.profiles(user_id),
  request_key uuid NOT NULL, -- Client-generated idempotency key for upload.
  original_filename text NOT NULL,
  mime_type text NOT NULL CHECK (mime_type IN ('application/pdf','image/jpeg','image/png')),
  file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint NOT NULL CHECK (byte_size BETWEEN 1 AND 5242880),
  page_count integer CHECK (page_count BETWEEN 1 AND 3),
  storage_key text UNIQUE,
  document_expires_at timestamptz NOT NULL DEFAULT (now() + interval '7 days'),
  document_deleted_at timestamptz,
  status text NOT NULL DEFAULT 'received' CHECK (status IN
    ('received','processing','needs_review','blocked_duplicate','rejected','accepted','processing_failed','reference_hold','expired')),
  current_revision_id uuid,
  duplicate_of uuid REFERENCES app.submissions(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(uploaded_by, request_key)
);
CREATE INDEX submissions_hash_idx ON app.submissions(file_sha256);
CREATE INDEX submissions_owner_idx ON app.submissions(uploaded_by, created_at DESC);

CREATE TABLE app.extraction_cache (
  cache_key text PRIMARY KEY CHECK (cache_key ~ '^[0-9a-f]{64}$'),
  file_sha256 text NOT NULL,
  pipeline_version text NOT NULL,
  model_id text NOT NULL,
  schema_version text NOT NULL,
  payload jsonb NOT NULL,
  evidence jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '7 days')
);

-- Immutable revisions preserve the original extraction and every correction.
CREATE TABLE app.invoice_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES app.submissions(id),
  revision_no integer NOT NULL CHECK (revision_no > 0),
  kind text NOT NULL CHECK (kind IN ('extraction','admin_correction')),
  created_by uuid REFERENCES app.profiles(user_id),
  correction_reason text,
  extraction_cache_key text, -- Informational: cache eviction must not mutate revisions.
  invoice_number text,
  invoice_date date,
  vendor_name text,
  po_reference text,
  currency text CHECK (currency IN ('INR','USD')),
  subtotal_net_minor bigint CHECK (subtotal_net_minor >= 0),
  tax_minor bigint CHECK (tax_minor >= 0),
  total_gross_minor bigint CHECK (total_gross_minor > 0),
  tax_presentation text CHECK (tax_presentation IN ('exclusive','inclusive','none','unclear')),
  line_items jsonb NOT NULL DEFAULT '[]',
  evidence jsonb NOT NULL DEFAULT '{}',
  unresolved_critical_fields jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(unresolved_critical_fields) = 'array'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(submission_id, revision_no),
  UNIQUE(submission_id, id),
  CHECK (kind <> 'admin_correction' OR
    (created_by IS NOT NULL AND length(btrim(correction_reason)) >= 5))
);
ALTER TABLE app.submissions ADD CONSTRAINT submission_revision_fk
  FOREIGN KEY(id, current_revision_id)
  REFERENCES app.invoice_revisions(submission_id, id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE app.processing_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES app.submissions(id),
  revision_id uuid,
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','completed','failed')),
  stage text NOT NULL DEFAULT 'received',
  pipeline_version text NOT NULL,
  cache_hit boolean NOT NULL DEFAULT false,
  attempt_count integer NOT NULL DEFAULT 0,
  lease_token uuid,
  lease_until timestamptz,
  error_code text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(submission_id, revision_id)
    REFERENCES app.invoice_revisions(submission_id, id),
  UNIQUE(id, submission_id, revision_id)
);
CREATE UNIQUE INDEX one_active_run_per_submission ON app.processing_runs(submission_id)
  WHERE state IN ('queued','running');

CREATE TABLE app.validation_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL,
  submission_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  reference_version_id uuid NOT NULL REFERENCES app.reference_versions(id),
  po_code text,
  verdict text NOT NULL CHECK (verdict IN ('eligible','needs_review','blocked')),
  acceptance_mode text NOT NULL CHECK (acceptance_mode IN ('automatic','admin_required','not_allowed')),
  engine_version text NOT NULL,
  checks jsonb NOT NULL CHECK (jsonb_typeof(checks) = 'array' AND jsonb_array_length(checks) > 0),
  po_candidates jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(po_candidates) = 'array'),
  summary text NOT NULL,
  completed_at timestamptz, -- Freeze header + allocations before accepting.
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(submission_id, revision_id)
    REFERENCES app.invoice_revisions(submission_id, id),
  FOREIGN KEY(run_id, submission_id, revision_id)
    REFERENCES app.processing_runs(id, submission_id, revision_id),
  FOREIGN KEY(reference_version_id, po_code)
    REFERENCES app.reference_pos(reference_version_id, po_code),
  UNIQUE(id, reference_version_id, po_code)
);

CREATE TABLE app.validation_lines (
  validation_id uuid NOT NULL,
  reference_version_id uuid NOT NULL,
  po_code text NOT NULL,
  line_code text NOT NULL,
  quantity numeric(18,4) NOT NULL CHECK (quantity > 0),
  net_minor bigint NOT NULL CHECK (net_minor >= 0),
  tax_minor bigint NOT NULL CHECK (tax_minor >= 0),
  gross_minor bigint NOT NULL CHECK (gross_minor = net_minor + tax_minor),
  PRIMARY KEY(validation_id, line_code),
  FOREIGN KEY(validation_id, reference_version_id, po_code)
    REFERENCES app.validation_results(id, reference_version_id, po_code),
  FOREIGN KEY(reference_version_id, po_code, line_code)
    REFERENCES app.reference_lines(reference_version_id, po_code, line_code)
);

CREATE TABLE app.review_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES app.submissions(id),
  actor_id uuid NOT NULL REFERENCES app.profiles(user_id),
  action text NOT NULL CHECK (action IN ('correct_fields','select_po','request_document','reject','authorize_acceptance')),
  reason text NOT NULL CHECK (length(btrim(reason)) >= 5),
  before_revision_id uuid REFERENCES app.invoice_revisions(id),
  after_revision_id uuid REFERENCES app.invoice_revisions(id),
  validation_id uuid REFERENCES app.validation_results(id),
  details jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.acceptances (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL UNIQUE REFERENCES app.submissions(id),
  validation_id uuid NOT NULL UNIQUE REFERENCES app.validation_results(id),
  reference_version_id uuid NOT NULL,
  po_code text NOT NULL,
  vendor_code text NOT NULL,
  invoice_number text NOT NULL,
  normalized_invoice_number text GENERATED ALWAYS AS (app.invoice_key(invoice_number)) STORED,
  invoice_date date NOT NULL,
  currency text NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor > 0),
  document_sha256 text NOT NULL UNIQUE,
  method text NOT NULL CHECK (method IN ('automatic','admin')),
  actor_id uuid NOT NULL REFERENCES app.profiles(user_id),
  reason text,
  accepted_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(reference_version_id, po_code)
    REFERENCES app.reference_pos(reference_version_id, po_code),
  FOREIGN KEY(po_code, vendor_code, currency)
    REFERENCES app.po_accounts(po_code, vendor_code, currency),
  UNIQUE(vendor_code, normalized_invoice_number)
);
CREATE INDEX acceptances_po_idx ON app.acceptances(po_code);

CREATE TABLE app.export_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  acceptance_id uuid NOT NULL UNIQUE REFERENCES app.acceptances(id),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN
    ('pending','publishing','published','failed','reconciliation_required')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_token uuid,
  lease_until timestamptz,
  last_error text,
  sheet_range text,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX export_tasks_ready_idx ON app.export_tasks(status, available_at);

CREATE TABLE app.audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  submission_id uuid REFERENCES app.submissions(id),
  run_id uuid REFERENCES app.processing_runs(id),
  actor_id uuid REFERENCES app.profiles(user_id),
  event_type text NOT NULL,
  stage text,
  details jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_submission_idx ON app.audit_events(submission_id, id);

CREATE FUNCTION app.deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_RECORD: %', TG_TABLE_NAME; END;
$$;
CREATE TRIGGER acceptances_immutable BEFORE UPDATE OR DELETE ON app.acceptances
  FOR EACH ROW EXECUTE FUNCTION app.deny_mutation();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON app.audit_events
  FOR EACH ROW EXECUTE FUNCTION app.deny_mutation();
CREATE TRIGGER review_immutable BEFORE UPDATE OR DELETE ON app.review_actions
  FOR EACH ROW EXECUTE FUNCTION app.deny_mutation();
CREATE TRIGGER revisions_immutable BEFORE UPDATE OR DELETE ON app.invoice_revisions
  FOR EACH ROW EXECUTE FUNCTION app.deny_mutation();

-- The locking read needs UPDATE privilege on reference_versions. Keep that
-- privilege inside this fixed trigger instead of granting it to the backend.
CREATE FUNCTION app.freeze_reference_rows() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $$
DECLARE v_id uuid; v_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN v_id := OLD.reference_version_id;
  ELSE v_id := NEW.reference_version_id; END IF;
  IF TG_OP = 'UPDATE' AND NEW.reference_version_id <> OLD.reference_version_id THEN
    RAISE EXCEPTION 'REFERENCE_VERSION_CANNOT_CHANGE';
  END IF;
  SELECT status INTO v_status FROM app.reference_versions WHERE id = v_id FOR SHARE;
  IF v_status IS DISTINCT FROM 'building' THEN
    RAISE EXCEPTION 'REFERENCE_SNAPSHOT_IS_FROZEN';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
REVOKE ALL ON FUNCTION app.freeze_reference_rows() FROM PUBLIC, anon, authenticated, service_role;
CREATE TRIGGER vendors_frozen BEFORE INSERT OR UPDATE OR DELETE ON app.reference_vendors
  FOR EACH ROW EXECUTE FUNCTION app.freeze_reference_rows();
CREATE TRIGGER pos_frozen BEFORE INSERT OR UPDATE OR DELETE ON app.reference_pos
  FOR EACH ROW EXECUTE FUNCTION app.freeze_reference_rows();
CREATE TRIGGER lines_frozen BEFORE INSERT OR UPDATE OR DELETE ON app.reference_lines
  FOR EACH ROW EXECUTE FUNCTION app.freeze_reference_rows();
CREATE TRIGGER rules_frozen BEFORE INSERT OR UPDATE OR DELETE ON app.reference_rules
  FOR EACH ROW EXECUTE FUNCTION app.freeze_reference_rows();

CREATE FUNCTION app.freeze_reference_header() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'building' THEN RAISE EXCEPTION 'REFERENCE_VERSION_IS_FROZEN'; END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER reference_header_frozen BEFORE UPDATE OR DELETE ON app.reference_versions
  FOR EACH ROW EXECUTE FUNCTION app.freeze_reference_header();

CREATE FUNCTION app.freeze_validation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_id uuid; v_completed timestamptz;
BEGIN
  IF TG_TABLE_NAME = 'validation_results' THEN
    IF OLD.completed_at IS NOT NULL THEN RAISE EXCEPTION 'VALIDATION_IS_FROZEN'; END IF;
  ELSE
    IF TG_OP = 'DELETE' THEN v_id := OLD.validation_id; ELSE v_id := NEW.validation_id; END IF;
    IF TG_OP = 'UPDATE' AND NEW.validation_id <> OLD.validation_id THEN
      RAISE EXCEPTION 'VALIDATION_ID_CANNOT_CHANGE';
    END IF;
    SELECT completed_at INTO v_completed FROM app.validation_results WHERE id = v_id FOR SHARE;
    IF v_completed IS NOT NULL THEN
      RAISE EXCEPTION 'VALIDATION_IS_FROZEN';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;
CREATE TRIGGER validation_header_frozen BEFORE UPDATE OR DELETE ON app.validation_results
  FOR EACH ROW EXECUTE FUNCTION app.freeze_validation();
CREATE TRIGGER validation_lines_frozen BEFORE INSERT OR UPDATE OR DELETE ON app.validation_lines
  FOR EACH ROW EXECUTE FUNCTION app.freeze_validation();

-- A status label cannot impersonate a financial acceptance. Also protects against
-- accidental owner-level writes; a migration owner can of course disable triggers.
CREATE FUNCTION app.guard_submission_acceptance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $$
DECLARE a app.acceptances%ROWTYPE; v_revision uuid;
BEGIN
  SELECT * INTO a FROM app.acceptances WHERE submission_id = NEW.id;
  IF FOUND THEN
    IF NEW.status <> 'accepted' THEN RAISE EXCEPTION 'ACCEPTED_STATUS_IS_FINAL'; END IF;
    SELECT revision_id INTO v_revision FROM app.validation_results WHERE id = a.validation_id;
    IF NEW.file_sha256 IS DISTINCT FROM a.document_sha256
       OR NEW.current_revision_id IS DISTINCT FROM v_revision THEN
      RAISE EXCEPTION 'ACCEPTED_IDENTITY_IS_IMMUTABLE';
    END IF;
  ELSIF NEW.status = 'accepted' THEN
    RAISE EXCEPTION 'ACCEPTANCE_LEDGER_REQUIRED';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER submission_acceptance_guard BEFORE INSERT OR UPDATE ON app.submissions
  FOR EACH ROW EXECUTE FUNCTION app.guard_submission_acceptance();

-- Non-financial workflow transitions only. Actor is always supplied by the
-- verified backend, never trusted directly from a browser request body.
CREATE FUNCTION app.transition_submission(p_submission_id uuid, p_actor_id uuid,
  p_status text, p_reason text DEFAULT NULL) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $$
DECLARE s app.submissions%ROWTYPE; v_role text; v_allowed text[];
BEGIN
  SELECT role INTO v_role FROM app.profiles WHERE user_id = p_actor_id AND enabled;
  IF v_role IS NULL THEN RAISE EXCEPTION 'ACTOR_DISABLED_OR_UNKNOWN'; END IF;
  SELECT * INTO s FROM app.submissions WHERE id = p_submission_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'SUBMISSION_NOT_FOUND'; END IF;
  IF s.uploaded_by <> p_actor_id AND v_role <> 'admin' THEN RAISE EXCEPTION 'FORBIDDEN'; END IF;
  IF p_status = 'accepted' THEN RAISE EXCEPTION 'USE_ACCEPT_INVOICE'; END IF;
  IF s.status = 'accepted' THEN RAISE EXCEPTION 'ACCEPTED_STATUS_IS_FINAL'; END IF;
  IF p_status = s.status THEN RETURN s.status; END IF;
  IF p_status = 'rejected' AND (v_role <> 'admin' OR length(btrim(coalesce(p_reason,''))) < 5) THEN
    RAISE EXCEPTION 'ADMIN_REASON_REQUIRED';
  END IF;
  v_allowed := CASE s.status
    WHEN 'received' THEN ARRAY['processing','processing_failed','expired']
    WHEN 'processing' THEN ARRAY['needs_review','blocked_duplicate','processing_failed','reference_hold','expired']
    WHEN 'needs_review' THEN ARRAY['processing','rejected','expired']
    WHEN 'processing_failed' THEN ARRAY['processing','expired']
    WHEN 'reference_hold' THEN ARRAY['processing','needs_review','expired']
    WHEN 'expired' THEN ARRAY['needs_review']
    ELSE ARRAY[]::text[] END;
  IF p_status IS NULL OR NOT (p_status = ANY(v_allowed)) THEN RAISE EXCEPTION 'INVALID_STATUS_TRANSITION'; END IF;
  IF s.status = 'expired' AND (s.storage_key IS NULL OR s.document_deleted_at IS NOT NULL
      OR s.document_expires_at <= now()) THEN RAISE EXCEPTION 'SOURCE_DOCUMENT_UNAVAILABLE'; END IF;
  UPDATE app.submissions SET status = p_status, updated_at = now() WHERE id = s.id;
  INSERT INTO app.audit_events(submission_id,actor_id,event_type,details)
    VALUES(s.id,p_actor_id,'submission.transitioned',jsonb_build_object('from',s.status,'to',p_status,'reason',p_reason));
  RETURN p_status;
END;
$$;

-- Import activation is a database operation, not an unguarded pointer update.
-- Stage rows in a committed building version first, then call this function.
CREATE FUNCTION app.activate_reference(p_version_id uuid, p_actor_id uuid DEFAULT NULL) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $$
DECLARE v app.reference_versions%ROWTYPE; v_previous uuid; v_row record;
BEGIN
  IF p_actor_id IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM app.profiles WHERE user_id=p_actor_id AND enabled AND role='admin') THEN
    RAISE EXCEPTION 'ADMIN_REQUIRED';
  END IF;
  SELECT active_reference_version_id INTO v_previous FROM app.runtime_state WHERE singleton FOR UPDATE;
  SELECT * INTO v FROM app.reference_versions WHERE id=p_version_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'REFERENCE_NOT_FOUND'; END IF;
  IF v.status='valid' AND v_previous=p_version_id AND v.valid_until>now() THEN RETURN p_version_id; END IF;
  IF v.status <> 'building' THEN RAISE EXCEPTION 'REFERENCE_NOT_BUILDING'; END IF;
  IF v.valid_until<=now() THEN RAISE EXCEPTION 'REFERENCE_STALE_OR_MISSING'; END IF;
  IF NOT EXISTS (SELECT 1 FROM app.reference_vendors WHERE reference_version_id=p_version_id)
     OR NOT EXISTS (SELECT 1 FROM app.reference_pos WHERE reference_version_id=p_version_id) THEN
    RAISE EXCEPTION 'REFERENCE_DATASET_EMPTY';
  END IF;
  IF EXISTS (SELECT 1 FROM app.reference_pos p LEFT JOIN app.reference_rules r
      ON r.reference_version_id=p.reference_version_id AND r.currency=p.currency
      WHERE p.reference_version_id=p_version_id AND r.currency IS NULL) THEN RAISE EXCEPTION 'RULES_MISSING'; END IF;
  -- Same pointer-first order as acceptance. Stable accounts are never replaced.
  PERFORM 1 FROM app.po_accounts WHERE po_code IN
    (SELECT po_code FROM app.reference_pos WHERE reference_version_id=p_version_id
     UNION SELECT po_code FROM app.acceptances) ORDER BY po_code FOR UPDATE;
  IF EXISTS (SELECT 1 FROM app.acceptances a WHERE NOT EXISTS
    (SELECT 1 FROM app.reference_pos p WHERE p.reference_version_id=p_version_id AND p.po_code=a.po_code)) THEN
    RAISE EXCEPTION 'REFERENCE_OMITS_COMMITTED_PO';
  END IF;
  IF EXISTS (SELECT 1 FROM app.reference_pos p JOIN
     (SELECT po_code,sum(amount_minor) used FROM app.acceptances GROUP BY po_code) a USING(po_code)
     WHERE p.reference_version_id=p_version_id AND p.authorized_gross_minor<a.used) THEN
    RAISE EXCEPTION 'PO_BUDGET_BELOW_COMMITMENTS';
  END IF;
  FOR v_row IN SELECT a.po_code,l.line_code,sum(l.quantity) used
      FROM app.acceptances a JOIN app.validation_lines l ON l.validation_id=a.validation_id
      GROUP BY a.po_code,l.line_code LOOP
    IF NOT EXISTS (SELECT 1 FROM app.reference_lines l WHERE l.reference_version_id=p_version_id
        AND l.po_code=v_row.po_code AND l.line_code=v_row.line_code) THEN
      RAISE EXCEPTION 'REFERENCE_OMITS_COMMITTED_LINE';
    END IF;
    IF EXISTS (SELECT 1 FROM app.reference_lines l WHERE l.reference_version_id=p_version_id
        AND l.po_code=v_row.po_code AND l.line_code=v_row.line_code AND l.quantity<v_row.used) THEN
      RAISE EXCEPTION 'PO_QUANTITY_BELOW_COMMITMENTS';
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM app.acceptances a
      JOIN app.validation_lines vl ON vl.validation_id=a.validation_id
      JOIN app.reference_lines old ON (old.reference_version_id,old.po_code,old.line_code)=
        (vl.reference_version_id,vl.po_code,vl.line_code)
      JOIN app.reference_lines new ON new.reference_version_id=p_version_id
        AND new.po_code=old.po_code AND new.line_code=old.line_code
      WHERE (old.description,old.unit,old.unit_net_minor,old.tax_rate_bps) IS DISTINCT FROM
        (new.description,new.unit,new.unit_net_minor,new.tax_rate_bps)) THEN
    RAISE EXCEPTION 'COMMITTED_LINE_IDENTITY_CHANGED';
  END IF;
  -- Reference gross budgets must reconcile to line-derived gross amounts.
  IF EXISTS (SELECT 1 FROM app.reference_pos p JOIN app.reference_rules r
      ON r.reference_version_id=p.reference_version_id AND r.currency=p.currency
      LEFT JOIN (SELECT reference_version_id,po_code,
        sum(round(quantity*unit_net_minor)+round(round(quantity*unit_net_minor)*tax_rate_bps/10000.0)) total
        FROM app.reference_lines GROUP BY reference_version_id,po_code) l
        ON l.reference_version_id=p.reference_version_id AND l.po_code=p.po_code
      WHERE p.reference_version_id=p_version_id
        AND (l.total IS NULL OR abs(l.total-p.authorized_gross_minor)>r.arithmetic_tolerance_minor)) THEN
    RAISE EXCEPTION 'REFERENCE_LINE_TOTAL_MISMATCH';
  END IF;
  UPDATE app.reference_versions SET status='valid' WHERE id=p_version_id;
  UPDATE app.runtime_state SET active_reference_version_id=p_version_id WHERE singleton;
  INSERT INTO app.audit_events(actor_id,event_type,details)
    VALUES(p_actor_id,'reference.activated',jsonb_build_object('previous_version_id',v_previous,'reference_version_id',p_version_id));
  RETURN p_version_id;
END;
$$;

CREATE FUNCTION app.invalidate_reference(p_version_id uuid,p_actor_id uuid,p_errors jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $$
BEGIN
  IF p_actor_id IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM app.profiles WHERE user_id=p_actor_id AND enabled AND role='admin') THEN RAISE EXCEPTION 'ADMIN_REQUIRED'; END IF;
  IF jsonb_typeof(p_errors) IS DISTINCT FROM 'array' OR jsonb_array_length(p_errors)=0 THEN
    RAISE EXCEPTION 'IMPORT_ERRORS_REQUIRED'; END IF;
  UPDATE app.reference_versions SET status='invalid',import_errors=p_errors WHERE id=p_version_id AND status='building';
  IF NOT FOUND THEN RAISE EXCEPTION 'REFERENCE_NOT_BUILDING'; END IF;
END;
$$;

-- Final commit boundary. Only the verified backend service may call this function.
-- Actor identity comes from the backend-verified JWT, never from a request body.
-- Monetary values are integer minor units; no floating point money.
CREATE FUNCTION app.accept_invoice(
  p_validation_id uuid,
  p_actor_id uuid,
  p_method text DEFAULT 'automatic',
  p_reason text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $$
DECLARE
  v_active uuid;
  v app.validation_results%ROWTYPE;
  r app.invoice_revisions%ROWTYPE;
  s app.submissions%ROWTYPE;
  po app.reference_pos%ROWTYPE;
  rule app.reference_rules%ROWTYPE;
  line record;
  v_used numeric;
  v_line_used numeric;
  v_expected_net numeric;
  v_line_total numeric;
  v_existing uuid;
  v_id uuid;
  v_role text;
  v_constraint text;
BEGIN
  SELECT role INTO v_role FROM app.profiles WHERE user_id = p_actor_id AND enabled;
  IF v_role IS NULL THEN RAISE EXCEPTION 'ACTOR_DISABLED_OR_UNKNOWN'; END IF;
  IF p_method IS NULL OR p_method NOT IN ('automatic','admin') THEN RAISE EXCEPTION 'INVALID_METHOD'; END IF;
  IF p_method = 'admin' AND (v_role <> 'admin' OR length(btrim(coalesce(p_reason,''))) < 5) THEN
    RAISE EXCEPTION 'ADMIN_REASON_REQUIRED';
  END IF;
  -- Shared pointer lock permits parallel different-PO approvals, but blocks a
  -- reference activation until this transaction ends. Importer locks it UPDATE.
  SELECT active_reference_version_id INTO v_active FROM app.runtime_state
    WHERE singleton FOR SHARE;
  SELECT * INTO v FROM app.validation_results WHERE id = p_validation_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'VALIDATION_NOT_FOUND'; END IF;
  IF v.po_code IS NULL THEN RAISE EXCEPTION 'PO_SELECTION_REQUIRED'; END IF;
  PERFORM 1 FROM app.po_accounts WHERE po_code = v.po_code FOR UPDATE;
  SELECT * INTO s FROM app.submissions WHERE id = v.submission_id FOR UPDATE;
  IF s.uploaded_by <> p_actor_id AND v_role <> 'admin' THEN RAISE EXCEPTION 'FORBIDDEN'; END IF;
  SELECT id INTO v_existing FROM app.acceptances WHERE submission_id = s.id;
  IF v_existing IS NOT NULL THEN RETURN v_existing; END IF;
  IF s.status IN ('rejected','expired','blocked_duplicate') THEN RAISE EXCEPTION 'SUBMISSION_NOT_ACCEPTABLE'; END IF;
  IF s.storage_key IS NULL OR s.document_deleted_at IS NOT NULL OR s.document_expires_at <= now() THEN
    RAISE EXCEPTION 'SOURCE_DOCUMENT_UNAVAILABLE';
  END IF;
  IF v.completed_at IS NULL OR v.verdict <> 'eligible' OR v.acceptance_mode = 'not_allowed' THEN
    RAISE EXCEPTION 'NOT_ELIGIBLE';
  END IF;
  IF p_method = 'automatic' AND v.acceptance_mode <> 'automatic' THEN RAISE EXCEPTION 'ADMIN_REQUIRED'; END IF;
  IF v.reference_version_id IS DISTINCT FROM v_active THEN RAISE EXCEPTION 'REFERENCE_CHANGED_REVALIDATE'; END IF;
  IF NOT EXISTS (SELECT 1 FROM app.reference_versions WHERE id = v_active
                 AND status = 'valid' AND valid_until > now()) THEN
    RAISE EXCEPTION 'REFERENCE_STALE_OR_MISSING';
  END IF;
  IF s.current_revision_id IS DISTINCT FROM v.revision_id THEN RAISE EXCEPTION 'REVISION_CHANGED_REVALIDATE'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(v.checks) c
             WHERE coalesce(c->>'status','') NOT IN ('pass','not_applicable')) THEN
    RAISE EXCEPTION 'UNRESOLVED_VALIDATION_CHECK';
  END IF;
  -- This enforces the rule-result contract, not the truth of an evidence quote.
  -- The trusted backend still performs these checks against the actual source.
  IF EXISTS (SELECT 1 FROM unnest(ARRAY['required_fields','vendor_match','po_match',
      'source_evidence','duplicate_check','currency','arithmetic','line_allocation','po_balance']) required(code)
      WHERE (SELECT count(*) FROM jsonb_array_elements(v.checks) c WHERE c->>'code'=required.code)<>1
         OR (SELECT count(*) FROM jsonb_array_elements(v.checks) c
             WHERE c->>'code'=required.code AND c->>'status'='pass')<>1) THEN
    RAISE EXCEPTION 'REQUIRED_VALIDATION_CHECKS_MISSING';
  END IF;
  SELECT * INTO r FROM app.invoice_revisions WHERE id = v.revision_id;
  SELECT * INTO po FROM app.reference_pos WHERE reference_version_id = v_active AND po_code = v.po_code;
  SELECT * INTO rule FROM app.reference_rules WHERE reference_version_id = v_active AND currency = po.currency;
  IF rule.reference_version_id IS NULL THEN RAISE EXCEPTION 'RULES_MISSING'; END IF;
  IF po.status <> 'open' OR NOT EXISTS (SELECT 1 FROM app.reference_vendors
      WHERE reference_version_id = v_active AND vendor_code = po.vendor_code AND approved) THEN
    RAISE EXCEPTION 'VENDOR_OR_PO_NOT_APPROVED';
  END IF;
  IF p_method = 'automatic' AND NOT rule.auto_accept_enabled THEN RAISE EXCEPTION 'AUTO_ACCEPT_DISABLED'; END IF;
  IF r.currency IS DISTINCT FROM po.currency THEN RAISE EXCEPTION 'CURRENCY_MISMATCH'; END IF;
  IF r.invoice_number IS NULL OR length(app.invoice_key(r.invoice_number)) = 0
     OR r.invoice_date IS NULL OR r.total_gross_minor IS NULL
     OR jsonb_array_length(r.unresolved_critical_fields) > 0 THEN
    RAISE EXCEPTION 'CRITICAL_FIELD_UNRESOLVED';
  END IF;
  IF r.tax_presentation IS NULL OR r.tax_presentation = 'unclear' THEN RAISE EXCEPTION 'TAX_UNCLEAR'; END IF;
  IF r.subtotal_net_minor IS NOT NULL AND r.tax_minor IS NOT NULL
     AND abs(r.subtotal_net_minor::numeric + r.tax_minor - r.total_gross_minor) > rule.arithmetic_tolerance_minor THEN
    RAISE EXCEPTION 'ARITHMETIC_MISMATCH';
  END IF;
  IF EXISTS (SELECT 1 FROM app.acceptances WHERE
     (vendor_code = po.vendor_code AND normalized_invoice_number = app.invoice_key(r.invoice_number))
      OR document_sha256 = s.file_sha256) THEN RAISE EXCEPTION 'DUPLICATE_ACCEPTANCE'; END IF;
  SELECT coalesce(sum(amount_minor),0) INTO v_used FROM app.acceptances WHERE po_code = po.po_code;
  IF v_used + r.total_gross_minor > po.authorized_gross_minor THEN RAISE EXCEPTION 'INSUFFICIENT_PO_BALANCE'; END IF;
  IF po.billing_mode = 'full' AND (v_used <> 0 OR
      abs(r.total_gross_minor::numeric - po.authorized_gross_minor) > rule.arithmetic_tolerance_minor) THEN
    RAISE EXCEPTION 'FULL_PO_AMOUNT_MISMATCH';
  END IF;
  SELECT sum(gross_minor) INTO v_line_total FROM app.validation_lines WHERE validation_id = v.id;
  IF v_line_total IS NULL OR abs(v_line_total - r.total_gross_minor) > rule.arithmetic_tolerance_minor THEN
    RAISE EXCEPTION 'LINE_ALLOCATION_MISMATCH';
  END IF;
  FOR line IN SELECT vl.*, pl.quantity AS allowed_quantity, pl.unit_net_minor, pl.tax_rate_bps
      FROM app.validation_lines vl JOIN app.reference_lines pl
        ON (pl.reference_version_id, pl.po_code, pl.line_code) =
           (vl.reference_version_id, vl.po_code, vl.line_code)
      WHERE vl.validation_id = v.id LOOP
    SELECT coalesce(sum(vl.quantity),0) INTO v_line_used
      FROM app.acceptances a JOIN app.validation_lines vl ON vl.validation_id = a.validation_id
      WHERE a.po_code = po.po_code AND vl.line_code = line.line_code;
    IF v_line_used + line.quantity > line.allowed_quantity THEN RAISE EXCEPTION 'INSUFFICIENT_LINE_QUANTITY'; END IF;
    v_expected_net := round(line.quantity * line.unit_net_minor);
    IF abs(line.net_minor - v_expected_net) >
       round(v_expected_net * rule.price_tolerance_bps / 10000.0) THEN RAISE EXCEPTION 'LINE_PRICE_MISMATCH'; END IF;
    IF abs(line.tax_minor - round(line.net_minor::numeric * line.tax_rate_bps / 10000.0)) >
       rule.arithmetic_tolerance_minor THEN RAISE EXCEPTION 'LINE_TAX_MISMATCH'; END IF;
  END LOOP;
  BEGIN
    INSERT INTO app.acceptances(submission_id, validation_id, reference_version_id, po_code,
    vendor_code, invoice_number, invoice_date, currency, amount_minor, document_sha256, method, actor_id, reason)
  VALUES(s.id, v.id, v_active, po.po_code, po.vendor_code, r.invoice_number, r.invoice_date,
    po.currency, r.total_gross_minor, s.file_sha256, p_method, p_actor_id, p_reason)
    RETURNING id INTO v_id;
  EXCEPTION WHEN unique_violation THEN
    GET STACKED DIAGNOSTICS v_constraint=CONSTRAINT_NAME;
    IF v_constraint IN ('acceptances_vendor_code_normalized_invoice_number_key','acceptances_document_sha256_key') THEN
      RAISE EXCEPTION 'DUPLICATE_ACCEPTANCE';
    END IF;
    RAISE;
  END;
  INSERT INTO app.export_tasks(acceptance_id) VALUES(v_id);
  UPDATE app.submissions SET status = 'accepted', updated_at = now() WHERE id = s.id;
  INSERT INTO app.audit_events(submission_id, run_id, actor_id, event_type, details)
    VALUES(s.id, v.run_id, p_actor_id, 'invoice.accepted',
      jsonb_build_object('acceptance_id',v_id,'reference_version_id',v_active,'method',p_method));
  RETURN v_id;
END;
$$;

-- No browser access to app tables or database functions. Browser uses FastAPI.
-- API checks ownership/roles before EVERY privileged DB or Storage operation.
REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA app TO service_role;
GRANT SELECT ON ALL TABLES IN SCHEMA app TO service_role;
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app FROM service_role;
GRANT INSERT(id,source_spreadsheet_id,source_hash,imported_by,imported_at,valid_until,source_ranges,import_errors)
  ON app.reference_versions TO service_role;
GRANT INSERT ON app.po_accounts,app.invoice_revisions,app.review_actions,app.audit_events TO service_role;
GRANT INSERT, UPDATE, DELETE ON app.reference_vendors,app.reference_pos,app.reference_lines,
  app.reference_rules,app.extraction_cache,app.validation_lines TO service_role;
GRANT INSERT, UPDATE ON app.processing_runs,app.validation_results TO service_role;
GRANT INSERT(id,uploaded_by,request_key,original_filename,mime_type,file_sha256,byte_size,page_count,
  storage_key,document_expires_at) ON app.submissions TO service_role;
GRANT UPDATE(current_revision_id,page_count,storage_key,document_expires_at,document_deleted_at,updated_at)
  ON app.submissions TO service_role;
GRANT UPDATE(status,attempt_count,available_at,lease_token,lease_until,last_error,sheet_range,published_at)
  ON app.export_tasks TO service_role;
-- No direct ledger INSERT/UPDATE/DELETE grant: acceptance goes through function.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO service_role;
GRANT EXECUTE ON FUNCTION app.invoice_key(text) TO service_role;
GRANT EXECUTE ON FUNCTION app.accept_invoice(uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION app.transition_submission(uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION app.activate_reference(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION app.invalidate_reference(uuid,uuid,jsonb) TO service_role;
COMMIT;

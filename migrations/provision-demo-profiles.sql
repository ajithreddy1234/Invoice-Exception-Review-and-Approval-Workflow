-- Run ONCE as migration owner, AFTER creating these two users in Auth dashboard.
-- Demo passwords belong in your password manager, never in this SQL file.
BEGIN;
DO $$
BEGIN
  IF (SELECT count(*) FROM auth.users WHERE email IN
      ('demo.admin@invoice-review.example','demo.user@invoice-review.example')) <> 2 THEN
    RAISE EXCEPTION 'Create both demo users in Authentication > Users first';
  END IF;
END $$;
INSERT INTO app.profiles(user_id,display_name,role)
SELECT id,'Demo Admin','admin' FROM auth.users WHERE email='demo.admin@invoice-review.example'
ON CONFLICT(user_id) DO NOTHING;
INSERT INTO app.profiles(user_id,display_name,role)
SELECT id,'Demo User','user' FROM auth.users WHERE email='demo.user@invoice-review.example'
ON CONFLICT(user_id) DO NOTHING;
COMMIT;

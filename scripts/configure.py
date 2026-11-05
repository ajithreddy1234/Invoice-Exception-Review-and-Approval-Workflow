"""Interactive local credential entry. Values never appear in terminal history."""
from getpass import getpass
from pathlib import Path
import os
import tempfile
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
path = root / '.env'
values = dict(dotenv_values(root / '.env.example'))
if path.exists():
    values.update(dotenv_values(path))
for name, secret in [('SUPABASE_URL', False), ('SUPABASE_PUBLISHABLE_KEY', True),
                     ('SUPABASE_SECRET_KEY', True), ('DATABASE_URL', True),
                     ('GOOGLE_SPREADSHEET_ID', False), ('GEMINI_API_KEY', True), ('GEMINI_MODEL', False)]:
    label = name + (' [Enter keeps existing]' if values.get(name) else '') + ': '
    value = getpass(label) if secret else input(label)
    if value.strip():
        if '\n' in value or '\r' in value:
            raise SystemExit('Multiline values are not supported')
        values[name] = value.strip()
values['GOOGLE_APPLICATION_CREDENTIALS'] = values.get('GOOGLE_APPLICATION_CREDENTIALS') or str(root / 'credentials/Sheet_Service.json')
# JSON double quoting is dotenv-compatible. Escape $ to avoid dotenv variable
# substitution by disabling interpolation in dotenv loading? Instead reject the
# interpolation sequence; URI passwords should already be percent-encoded.
if any('${' in str(v) for v in values.values()):
    raise SystemExit('Percent-encode ${ in URL passwords; no variable expansion in credential input')
import json
fd, temp = tempfile.mkstemp(dir=root, prefix='.env-')
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as out:
        for key, value in values.items():
            out.write(f'{key}={json.dumps(str(value or ""))}\n')
    os.replace(temp, path)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
print('Saved local .env with mode 0600. No credential values printed.')


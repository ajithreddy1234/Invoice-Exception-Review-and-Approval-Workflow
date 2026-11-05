"""Save a Supabase pooler URI using a separately entered, correctly encoded password."""
from getpass import getpass
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from dotenv import set_key
from psycopg.conninfo import conninfo_to_dict


def connection_uri(template: str, password: str) -> str:
    # Python rejects bracketed placeholders in URI userinfo before parsing the
    # hostname. The template's password is discarded in favor of the hidden input.
    clean = template.strip().replace('[YOUR-PASSWORD]', 'PASSWORD_PLACEHOLDER').replace('[YOUR_PASSWORD]', 'PASSWORD_PLACEHOLDER')
    p = urlsplit(clean)
    if (p.scheme not in ('postgres', 'postgresql') or not p.hostname or not p.username
            or p.fragment or not p.hostname.endswith('.pooler.supabase.com') or p.port != 6543):
        raise ValueError('Use the original Supabase Transaction pooler URI, with port 6543 and its password placeholder unchanged.')
    if not password:
        raise ValueError('A database password is required.')
    query = dict(parse_qsl(p.query, keep_blank_values=True))
    query['sslmode'] = 'require'
    user = quote(p.username, safe='%')
    netloc = f'{user}:{quote(password, safe="")}@{p.hostname}:{p.port}'
    uri = urlunsplit((p.scheme, netloc, p.path or '/postgres', urlencode(query), ''))
    parsed = conninfo_to_dict(uri)
    if parsed['host'] != p.hostname or parsed['password'] != password:
        raise ValueError('Connection URI could not be encoded safely.')
    return uri


def main():
    print('Copy the ORIGINAL Connect > Transaction pooler URI from Supabase.')
    print('Keep its password placeholder. Enter the actual DATABASE password separately below.')
    template = getpass('Transaction pooler URI (hidden): ')
    password = getpass('Database password, exactly as saved/reset (hidden): ')
    try:
        uri = connection_uri(template, password)
    except (ValueError, TypeError):
        print('Invalid input. Copy the original transaction-pooler URI; do not paste a psql command.')
        return 1
    path = Path(__file__).resolve().parents[1] / '.env'
    set_key(path, 'DATABASE_URL', uri, quote_mode='always')
    path.chmod(0o600)
    print('Saved DATABASE_URL privately with encoded password and TLS required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

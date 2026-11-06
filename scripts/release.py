#!/usr/bin/env python3
"""Build an allowlisted source archive; refuse credentials without printing them."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', '.gitattributes', '.dockerignore', '.env.example', 'Dockerfile', 'render.yaml',
              'README.md', 'pyproject.toml', 'uv.lock', 'requirements.txt',
              'package.json', 'package-lock.json', 'extraction.schema.json'}
TREES = ('app', 'scripts', 'migrations', 'tests', 'tools', 'docs', 'web/src')
WEB_FILES = ('web/package.json', 'web/package-lock.json', 'web/index.html',
             'web/vite.config.js', 'web/README.md')
EXCLUDED = {'__pycache__', '.pytest_cache', 'node_modules', '.venv', '.git', 'data',
            'credentials', 'secrets', 'dist', '.DS_Store'}


def source_files():
    paths = [ROOT / name for name in ROOT_FILES | set(WEB_FILES) if (ROOT / name).is_file()]
    for tree in TREES:
        paths.extend(path for path in (ROOT / tree).rglob('*') if path.is_file()
                     and not path.is_symlink()
                     and not any(part in EXCLUDED for part in path.relative_to(ROOT).parts)
                     and path.suffix not in {'.pyc', '.pem', '.log'}
                     and not path.name.startswith('.env'))
    return sorted(set(paths))


def secret_values():
    values = dotenv_values(ROOT / '.env', interpolate=False)
    needles = [str(values.get(key) or '').encode() for key in
               ('DATABASE_URL', 'SUPABASE_SECRET_KEY', 'GEMINI_API_KEY')]
    try:
        password = unquote(urlsplit(values.get('DATABASE_URL') or '').password or '')
        needles.append(password.encode())
    except ValueError:
        pass
    credential_path = Path(values.get('GOOGLE_APPLICATION_CREDENTIALS') or ROOT / 'credentials/Sheet_Service.json')
    if not credential_path.is_absolute():
        credential_path = ROOT / credential_path
    if credential_path.is_file():
        credentials = json.loads(credential_path.read_text())
        for key in ('private_key', 'private_key_id'):
            value = credentials.get(key, '')
            needles.extend([value.encode(), json.dumps(value)[1:-1].encode()])
    return [value for value in needles if len(value) >= 8]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='ZIP destination outside the source tree; omit to audit only')
    args = parser.parse_args()
    paths = source_files()
    needles = secret_values()
    violations = []
    manifest = []
    contents = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        if (any(value in data for value in needles) or
                re.search(rb'-----BEGIN (?:RSA )?PRIVATE KEY-----|sb_secret_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}', data)):
            violations.append(relative)
        contents[relative] = data
        manifest.append({'path': relative, 'bytes': len(data), 'sha256': sha256(data).hexdigest()})
    required = {'Dockerfile', 'render.yaml', '.gitignore', '.dockerignore', '.env.example',
                'app/main.py', 'web/src/main.jsx', 'web/package-lock.json',
                'requirements.txt', 'migrations/schema.sql', 'migrations/step3.sql'}
    missing = sorted(required - contents.keys())
    report = {'status': 'failed' if violations or missing else 'passed', 'source_files': len(paths),
              'uncompressed_bytes': sum(item['bytes'] for item in manifest),
              'credential_violations_paths_only': violations, 'missing_required_files': missing}
    if report['status'] == 'passed' and args.output:
        destination = args.output.resolve()
        if destination.is_relative_to(ROOT):
            parser.error('Archive destination must be outside the source tree')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
            for relative, data in contents.items():
                archive.writestr('invoice-review/' + relative, data)
            archive.writestr('invoice-review/RELEASE-MANIFEST.json', json.dumps({
                'created_at_utc': datetime.now(timezone.utc).isoformat(), 'files': manifest}, indent=2) + '\n')
        digest = sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(destination.suffix + '.sha256').write_text(f'{digest}  {destination.name}\n')
        report.update(archive=destination.name, archive_sha256=digest)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

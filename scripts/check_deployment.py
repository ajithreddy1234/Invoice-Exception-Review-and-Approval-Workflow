#!/usr/bin/env python3
"""Probe a deployment without credentials, uploads or ledger changes.

Use after deployment/restart, then once after a genuine idle period. This checks
reachability and access boundaries, not provider quota or successful extraction.
"""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        value = values.get('src') if tag == 'script' else values.get('href') if tag == 'link' else None
        if value and value.startswith('/assets/') and not value.startswith('//'):
            self.paths.append(value)


def probe(base, timeout):
    checks = []

    def record(name, passed, **details):
        checks.append({'check': name, 'passed': bool(passed), **details})

    with httpx.Client(base_url=base, timeout=timeout, follow_redirects=False) as client:
        started = time.perf_counter()
        response = client.get('/health/live')
        record('liveness', response.status_code == 200 and response.json().get('status') == 'alive',
               http_status=response.status_code, seconds=round(time.perf_counter() - started, 3))
        ready = client.get('/health/ready')
        body = ready.json() if ready.headers.get('content-type', '').startswith('application/json') else {}
        record('readiness', ready.status_code == 200 and body.get('reference_fresh') is True
               and body.get('invoice_pipeline_complete') is True and body.get('workers_running') is True,
               http_status=ready.status_code)
        home = client.get('/')
        assets = Assets()
        assets.feed(home.text)
        record('built_frontend', home.status_code == 200 and bool(assets.paths))
        record('private_cache_and_frame_protection', home.headers.get('cache-control') == 'no-store'
               and home.headers.get('x-content-type-options') == 'nosniff'
               and "frame-ancestors 'none'" in home.headers.get('content-security-policy', ''))
        for path in sorted(set(assets.paths)):
            asset = client.get(path)
            record('frontend_asset', asset.status_code == 200, asset=path, http_status=asset.status_code)
        for path in ('/api/me', '/api/submissions', '/api/admin/health'):
            protected = client.get(path)
            record('unauthenticated_access_denied', protected.status_code == 401,
                   endpoint=path, http_status=protected.status_code)
        rejected = client.post('/api/auth/login', headers={'Origin': 'https://untrusted.invalid'},
                               json={'email': 'unused@example.invalid', 'password': 'not-a-real-password'})
        record('cross_origin_login_denied', rejected.status_code == 403
               and rejected.json().get('detail') == 'ORIGIN_REJECTED', http_status=rejected.status_code)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin', help='Exact deployment origin, without trailing path')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    origin = args.origin.rstrip('/')
    parsed = urlsplit(origin)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
        parser.error('Use HTTPS, or HTTP only for a local loopback origin')
    report = {'origin': origin, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'UNAUTHENTICATED_DEPLOYMENT_SMOKE_NO_LEDGER_WRITES', 'checks': []}
    try:
        report['checks'] = probe(origin, args.timeout)
    except (httpx.HTTPError, ValueError):
        report['checks'].append({'check': 'request_or_response', 'passed': False,
                                 'error': 'DEPLOYMENT_UNAVAILABLE_OR_INVALID_RESPONSE'})
    report['passed'] = bool(report['checks']) and all(item['passed'] for item in report['checks'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

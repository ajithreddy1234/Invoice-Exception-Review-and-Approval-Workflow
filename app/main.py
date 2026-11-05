from contextlib import asynccontextmanager
import asyncio
import logging
import time
from pathlib import Path
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .auth import COOKIE, Actor, LoginRequest, SupabaseAuth, actor_for_id, current_actor, require_admin
from .config import Settings, get_settings
from .db import Database, DatabaseUnavailable
from .procurement import INPUT_RANGES, ReferenceValidationError, SheetsGateway, import_reference, parse_reference
from .storage import StorageGateway
from .processing import Pipeline, Workers
from .invoice_api import router as invoice_router, UploadLimit
from .workspace import router as workspace_router
from .review import router as review_router

log = logging.getLogger(__name__)
STARTUP_RETRY_SECONDS = 10


def reference_status(db):
    with db.transaction() as conn:
        row = conn.execute('''SELECT v.id,v.status,v.source_spreadsheet_id,v.source_hash,
            v.imported_at,v.valid_until,v.valid_until>now() AS fresh
            FROM app.runtime_state s LEFT JOIN app.reference_versions v
            ON v.id=s.active_reference_version_id WHERE s.singleton''').fetchone()
    return row if row and row['id'] else {'status': 'missing', 'fresh': False}


def sync_reference(app, actor_id=None):
    settings = app.state.settings
    if not settings.configured()['sheets']:
        raise HTTPException(503, 'SHEETS_NOT_CONFIGURED')
    tabs = app.state.sheets.read_reference()
    snapshot = parse_reference(tabs)
    # Read/parse network data before opening a transaction or locking any PO.
    with app.state.db.transaction() as conn:
        version_id = import_reference(conn, snapshot, settings.google_spreadsheet_id,
                                      actor_id, settings.reference_ttl_hours)
    return {'reference_version_id': version_id, 'source_hash': snapshot.source_hash, 'status': 'active'}


def create_app(settings: Settings | None = None, *, db=None, auth=None, sheets=None, storage=None, pipeline=None):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.started_at = time.monotonic()
        app.state.startup = 'setup_required'
        app.state.startup_complete = False
        stop = asyncio.Event()

        async def initialize():
            if not settings.configured()['database']:
                app.state.startup_complete = True
                return
            # Serve the UI/liveness immediately. A slow DB or Sheets request must
            # not keep the HTTP listener behind the host's allocation page.
            while not stop.is_set():
                app.state.startup = 'checking_database'
                try:
                    await run_in_threadpool(app.state.db.permission_gate)
                    break
                except Exception:
                    app.state.startup = 'dependency_check_failed'
                    log.warning('Startup database check failed; retrying without logging credentials')
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=STARTUP_RETRY_SECONDS)
                    except TimeoutError:
                        pass
            if stop.is_set():
                return
            app.state.startup = 'database_verified'
            if settings.auto_import_on_startup and settings.configured()['sheets']:
                app.state.startup = 'syncing_reference'
                try:
                    await run_in_threadpool(sync_reference, app)
                    app.state.startup = 'reference_imported'
                except Exception:
                    # A failed import preserves the last valid snapshot. Rules
                    # and SQL still require it to be fresh for any acceptance.
                    app.state.startup = 'reference_import_failed'
                    log.warning('Startup reference import failed; previous reference preserved')
            if not stop.is_set() and app.state.workers is not None:
                app.state.workers.start()
            app.state.startup_complete = True

        task = asyncio.create_task(initialize())
        try:
            yield
        finally:
            stop.set()
            # Join in-flight bounded startup I/O before closing its DB pool.
            await task
            if app.state.workers is not None:
                app.state.workers.stop()
            if db is None:
                await run_in_threadpool(app.state.db.close)
            if auth is None:
                await run_in_threadpool(app.state.auth.close)

    app = FastAPI(title='Invoice Review API', version='0.8.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.db = db or Database(settings.database_url.get_secret_value())
    app.state.auth = auth or SupabaseAuth(settings.supabase_url, settings.supabase_publishable_key.get_secret_value())
    app.state.sheets = sheets or (SheetsGateway(settings.google_spreadsheet_id, settings.google_application_credentials)
                                 if settings.configured()['sheets'] else None)
    app.state.startup = 'not_started'
    app.state.startup_complete = False
    app.state.started_at = time.monotonic()
    configured = settings.configured()
    app.state.storage = storage or (StorageGateway(settings.supabase_url,settings.supabase_secret_key.get_secret_value(),settings.storage_bucket)
        if settings.supabase_url and settings.supabase_secret_key.get_secret_value() else None)
    app.state.pipeline = pipeline or (Pipeline(app.state.db,settings,app.state.storage)
        if db is None and all(configured.values()) and app.state.storage is not None else None)
    app.state.workers = Workers(app.state.pipeline) if settings.worker_enabled and db is None and app.state.pipeline is not None else None
    app.add_middleware(UploadLimit)

    @app.middleware('http')
    async def same_origin_and_headers(request: Request, call_next):
        # Same-origin browser UI only: no CORS exceptions or state-changing GETs.
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != settings.app_origin:
            response = JSONResponse({'detail': 'ORIGIN_REJECTED'}, status_code=403)
        else:
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if settings.app_origin.startswith('https://'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Content-Security-Policy'] = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(RequestValidationError)
    async def bad_request(request, exc):
        # FastAPI's default validation response can echo the login password input.
        errors = [{'loc': e['loc'], 'type': e['type'], 'msg': e['msg']} for e in exc.errors()]
        return JSONResponse({'detail': errors}, status_code=422)

    @app.exception_handler(DatabaseUnavailable)
    async def missing_db(request, exc):
        return JSONResponse({'detail': 'DATABASE_NOT_READY'}, status_code=503)

    @app.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        return JSONResponse({'detail': 'DATABASE_OPERATION_FAILED'}, status_code=503)

    @app.exception_handler(ReferenceValidationError)
    async def invalid_reference(request, exc):
        return JSONResponse({'detail': 'REFERENCE_INVALID', 'errors': exc.errors,
                             'previous_reference_preserved': True}, status_code=422)

    @app.get('/', response_class=HTMLResponse)
    def home():
        index=Path(__file__).resolve().parents[1]/'web/dist/index.html'
        if index.is_file():
            return FileResponse(index)
        return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Invoice Review — Backend</title><body><main><h1>Invoice Review</h1>
        <p>Invoice processing backend is running. Build the web client to open the upload dashboard.</p>
        <p>Approval ledger: Postgres. Procurement source: Google Sheets.</p>
        <p><a href="/health/live">Liveness</a> · <a href="/health/ready">Readiness</a></p>
        <p>Missing credentials are reported as setup required. No invoice decisions are simulated.</p></main></body></html>'''

    @app.get('/health/live')
    def live():
        return {'status': 'alive', 'stage': 'invoice_processing', 'version': app.version,
                'uptime_seconds': round(time.monotonic()-app.state.started_at, 3)}

    @app.get('/health/ready')
    def ready(response: Response):
        configured = settings.configured()
        if not configured['database'] or not configured['authentication'] or not configured['sheets']:
            response.status_code = 503
            return {'status': 'setup_required', 'configured': configured}
        if not app.state.startup_complete:
            response.status_code = 503
            response.headers['Retry-After'] = '2'
            return {'status': 'starting', 'stage': app.state.startup}
        try:
            app.state.db.permission_gate()
            state = reference_status(app.state.db)
            ok = bool(state.get('fresh'))
            response.status_code = 200 if ok else 503
            return {'status': 'ready_for_backend_use' if ok else 'reference_required',
                    'reference_fresh': ok, 'gemini_configured': configured['gemini'],
                    'invoice_pipeline_complete': app.state.pipeline is not None,
                    'workers_running': bool(app.state.workers and app.state.workers.running)}
        except Exception:
            response.status_code = 503
            return {'status': 'dependency_unavailable'}

    @app.post('/api/auth/login')
    def login(body: LoginRequest, request: Request, response: Response):
        data = app.state.auth.login(body.email, body.password.get_secret_value())
        # Identity comes from the validated HTTPS password-grant response, never
        # from browser input/metadata. A second /user round trip is redundant here.
        # Subsequent cookie requests still verify the token with Supabase Auth.
        user_id = UUID(data['user']['id'])
        actor = actor_for_id(request, user_id)
        response.set_cookie(COOKIE, data['access_token'], httponly=True, secure=settings.cookie_secure,
                            samesite='strict', path='/', max_age=min(int(data.get('expires_in', 3600)), 3600))
        return {'id': str(actor.id), 'display_name': actor.display_name, 'role': actor.role,
                'expires_in': min(int(data.get('expires_in', 3600)), 3600)}

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        remote_revoked = True
        if token:
            try:
                app.state.auth.logout(token)
            except HTTPException:
                remote_revoked = False
        response.delete_cookie(COOKIE, path='/', secure=settings.cookie_secure, httponly=True, samesite='strict')
        # No refresh tokens retained. Supabase access tokens expire normally.
        return {'signed_out': True, 'remote_session_revoked': remote_revoked}

    @app.get('/api/me')
    def me(actor: Actor = Depends(current_actor)):
        return {'id': str(actor.id), 'display_name': actor.display_name, 'role': actor.role}

    @app.get('/api/procurement/status')
    def procurement_status(actor: Actor = Depends(current_actor)):
        return reference_status(app.state.db)

    @app.post('/api/admin/procurement/sync')
    def sync(actor: Actor = Depends(require_admin)):
        try:
            return sync_reference(app, actor.id)
        except ReferenceValidationError:
            raise
        except psycopg.Error:
            raise
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'SHEETS_IMPORT_UNAVAILABLE') from None

    @app.get('/api/admin/health')
    def diagnostics(actor: Actor = Depends(require_admin)):
        result = {'configured': settings.configured(), 'startup': app.state.startup,
                  'startup_complete': app.state.startup_complete,
                  'workers_running': bool(app.state.workers and app.state.workers.running)}
        result['worker_errors']=app.state.workers.errors if app.state.workers else None
        try:
            result['database'] = app.state.db.permission_gate()
            result['reference'] = reference_status(app.state.db)
        except Exception:
            result['database'] = {'status': 'unavailable'}
        return result

    @app.get('/api/submissions')
    def submissions(actor: Actor = Depends(current_actor)):
        with app.state.db.transaction() as conn:
            # Backend owns access control: service_role has broad SELECT privileges.
            rows = conn.execute('''SELECT s.id,s.original_filename,s.status,s.created_at,
                a.id AS acceptance_id,e.status AS publication_status
                FROM app.submissions s LEFT JOIN app.acceptances a ON a.submission_id=s.id
                LEFT JOIN app.export_tasks e ON e.acceptance_id=a.id
                WHERE (%s='admin' OR s.uploaded_by=%s) ORDER BY s.created_at DESC LIMIT 100''',
                (actor.role, actor.id)).fetchall()
        return {'items': rows}

    app.include_router(invoice_router)
    app.include_router(workspace_router)
    app.include_router(review_router)
    assets=Path(__file__).resolve().parents[1]/'web/dist/assets'
    if assets.is_dir():
        app.mount('/assets',StaticFiles(directory=assets),name='assets')
    return app


app = create_app()

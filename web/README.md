# Invoice review browser interface

The production interface uses the existing FastAPI API and its HttpOnly cookie. No service keys or environment secrets belong in this directory.

```sh
npm ci
npm test
npm run build
```

Serve `dist/index.html` at `/` and `dist/assets/` at `/assets/` from FastAPI. Keep `/api/` routes on that same origin. The build requires Node 20.19+ or Node 22.12+; the runtime serves static files without Node.

For local UI development, run FastAPI on `127.0.0.1:8000`, then `npm run dev`. Vite proxies `/api/` to that backend. Configure the backend's allowed Origin to the exact local Vite origin while developing. The production app uses the final application origin.

The interface never creates an acceptance locally. It displays the server's record, source quotes/pages and all nine validation checks. Acceptance and spreadsheet publication are separate states. Admin acceptance remains hidden unless the server returns an eligible admin-required validation with all nine unique passing checks; the backend must enforce the same authorization and transaction rules independently.

Tests cover the safety of action visibility, acceptance/publication separation, evidence preservation, processing polling conditions and upload limits. Production compilation passes. Browser visual verification must be performed against the integrated application; no browser surface was available in the development tool session.

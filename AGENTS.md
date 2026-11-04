# Project Rules & Workflow Instructions

## 1. Branch & Deployment Policy
- **UAT Environment (`c:\E-Budget`)**: Commit and push directly to branch **`uat`**.
- **Production Environment (`c:\E-Budget_PRD`)**: Commit and push directly to branch **`main`**.

## 2. Process Cleanup & Dev Server Lifecycle
- On Windows development environments, `python manage.py runserver` can leave orphaned background processes bound to port 8000 (or custom port).
- **Rule**: Prior to testing or restarting the dev server, always check and kill any lingering processes holding the target port (e.g. `Stop-Process -Id <pid> -Force`).

## 3. Static Files & WhiteNoise Manifest (`collectstatic`)
- The project configures WhiteNoise `CompressedManifestStaticFilesStorage` with `STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')`.
- When running with `DEBUG=False`, static URLs are mapped via `staticfiles/staticfiles.json` which is loaded into memory on server start.
- **Rule**: Whenever JavaScript, CSS, or static files are modified:
  1. Run `python manage.py collectstatic --noinput` to update `staticfiles/` and regenerate the content-hash manifest.
  2. Kill any old server process and start a fresh server instance so the updated manifest is loaded into memory.
  3. Bump the query version tag in templates (e.g. `?v=YYYYMMDD_XX`) to prevent client-side browser caching.

## 4. Best Practices & Stability
- Adhere strictly to clean architecture, performance optimization, and rock-solid stability.
- Always verify changes end-to-end (e.g., automated browser/CDP test or regression tests) before committing and pushing.

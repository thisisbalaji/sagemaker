"""ML portal API.

Run locally (from portal/backend):  uvicorn --factory app.main:create_app --reload --port 8000
"""

import html
from pathlib import Path

import boto3
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from .config import Settings
from .services import AwsError, Forbidden, NotFound, Portal, is_admin_for
from .store import PENDING, Conflict, Store

NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class LoginBody(BaseModel):
    user_id: str


class AccessRequestBody(BaseModel):
    reason: str = Field(default="", max_length=500)


class ProjectBody(BaseModel):
    domain_id: str
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class RejectBody(BaseModel):
    note: str = Field(default="", max_length=500)


def create_app(settings=None, portal=None):
    settings = settings or Settings()
    if portal is None:
        session = boto3.Session(region_name=settings.region)
        store = Store(session.resource("dynamodb").Table(settings.table_name))
        portal = Portal(settings, store, session.client("sagemaker"), session.client("iam"))

    app = FastAPI(title="ML Portal")
    app.state.portal = portal
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="mlportal_session",
        same_site="lax",
        max_age=8 * 3600,
    )

    @app.middleware("http")
    async def block_cross_site_writes(request: Request, call_next):
        # Cookie auth + state-changing requests: only accept them from the portal's own pages.
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in settings.allowed_origins:
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(NotFound)
    async def _nf(_, e):
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(Forbidden)
    async def _fb(_, e):
        return JSONResponse({"detail": str(e)}, status_code=403)

    @app.exception_handler(Conflict)
    async def _cf(_, e):
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(AwsError)
    async def _aws(_, e):
        return JSONResponse({"detail": f"AWS error: {e}"}, status_code=502)

    @app.exception_handler(ValueError)
    async def _val(_, e):
        return JSONResponse({"detail": str(e)}, status_code=400)

    # ------------------------------------------------------------- auth deps
    def current_user(request: Request):
        user_id = request.session.get("user_id")
        user = portal.store.get_user(user_id) if user_id else None
        if not user:
            raise HTTPException(401, "Not logged in")
        return user

    def admin_user(user=Depends(current_user)):
        if not user.get("admin_domains"):
            raise HTTPException(403, "Admin access required")
        return user

    # ------------------------------------------------------------------ auth
    @app.get("/api/auth/users")
    def mock_users():
        if not settings.mock_auth:
            raise HTTPException(404)
        return [{"user_id": u["user_id"], "display_name": u["display_name"],
                 "is_admin": bool(u.get("admin_domains"))} for u in portal.store.list_users()]

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request):
        if not settings.mock_auth:
            raise HTTPException(404)
        if not portal.store.get_user(body.user_id):
            raise HTTPException(401, "Unknown user")
        request.session.clear()
        request.session["user_id"] = body.user_id
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return {**user, "is_admin": bool(user.get("admin_domains"))}

    # -------------------------------------------------------- user features
    @app.get("/api/domains")
    def domains(user=Depends(current_user)):
        return [{**d, "is_admin": is_admin_for(user, d["domain_id"])} for d in portal.list_domains()]

    @app.get("/api/domains/{domain_id}/projects")
    def domain_projects(domain_id: str, user=Depends(current_user)):
        return portal.projects_for_user(user, domain_id)

    @app.post("/api/projects/{project_id}/requests", status_code=201)
    def request_access(project_id: str, body: AccessRequestBody, user=Depends(current_user)):
        return portal.request_access(user, project_id, body.reason)

    @app.get("/api/me/requests")
    def my_requests(user=Depends(current_user)):
        return portal.my_requests(user)

    @app.post("/api/studio/launch")
    def launch(project_id: str = Form(...), user=Depends(current_user)):
        # Submitted as a normal form into a new tab, so errors are rendered as a small page.
        try:
            url = portal.launch_url(user, project_id)
        except (Forbidden, Conflict, AwsError) as e:
            status = 403 if isinstance(e, Forbidden) else 409 if isinstance(e, Conflict) else 502
            return HTMLResponse(error_page(str(e)), status_code=status, headers=NO_STORE)
        return RedirectResponse(url, status_code=302, headers=NO_STORE)

    # ------------------------------------------------------------------ admin
    @app.get("/api/admin/projects")
    def admin_projects(admin=Depends(admin_user)):
        return portal.admin_projects(admin)

    @app.post("/api/admin/projects", status_code=201)
    def create_project(body: ProjectBody, admin=Depends(admin_user)):
        return portal.create_project(admin, body.domain_id, body.name, body.description)

    @app.get("/api/admin/requests")
    def admin_requests(status: str = PENDING, admin=Depends(admin_user)):
        return portal.admin_requests(admin, status.upper())

    @app.post("/api/admin/requests/{project_id}/{user_id}/approve")
    def approve(project_id: str, user_id: str, admin=Depends(admin_user)):
        return portal.approve(admin, project_id, user_id)

    @app.post("/api/admin/requests/{project_id}/{user_id}/reject")
    def reject(project_id: str, user_id: str, body: RejectBody, admin=Depends(admin_user)):
        return portal.reject(admin, project_id, user_id, body.note)

    # Serve the built UI (npm run build) so one process can run the whole portal.
    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            return HTMLResponse((FRONTEND_DIST / "index.html").read_text())

    return app


def error_page(message):
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Could not open Studio</title>
<style>body{{font:16px/1.5 -apple-system,sans-serif;max-width:560px;margin:64px auto;padding:0 16px}}
@media(prefers-color-scheme:dark){{body{{background:#0f1216;color:#e6e9ee}}}}</style>
<h1>Could not open Studio</h1><p>{html.escape(message)}</p><p>Close this tab and try again from the portal.</p>"""


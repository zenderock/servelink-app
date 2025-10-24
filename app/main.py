from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from arq import create_pool
from arq.connections import RedisSettings
from starlette_wtf import CSRFProtectMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from routers import auth, project, github, google, team, user, event, bug_report
from config import get_settings, Settings
from db import get_db, AsyncSessionLocal
from models import User, Team, Deployment, Project
from dependencies import get_current_user, TemplateResponse
from services.loki import LokiService
from middleware.traffic_recorder import TrafficRecorderMiddleware


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


settings = get_settings()

log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(level=log_level)
if log_level > logging.DEBUG:
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    app.state.redis_pool = await create_pool(redis_settings)
    app.state.loki_service = LokiService()
    try:
        yield
    finally:
        try:
            await app.state.loki_service.client.aclose()
            await app.state.redis_pool.close()
        except Exception:
            pass


app = FastAPI(
    lifespan=lifespan,
    middleware=[
        Middleware(SessionMiddleware, secret_key=settings.secret_key),
        Middleware(CSRFProtectMiddleware, csrf_secret=settings.secret_key),
        Middleware(TrafficRecorderMiddleware, deploy_domain=settings.deploy_domain),
    ],
)
app.mount("/assets", CachedStaticFiles(directory="assets"), name="assets")
app.mount("/upload", StaticFiles(directory="upload"), name="upload")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/deployment-not-found/{host}")
async def catch_all_missing_container(
    request: Request,
    host: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    current_user = await get_current_user(
        request=request,
        db=db,
        settings=settings,
        redirect_on_fail=False,
    )

    if current_user and host.endswith(settings.deploy_domain):
        import re

        subdomain = host.removesuffix(f".{settings.deploy_domain}")

        match = re.match(
            r"^(?P<project_slug>.+)-id-(?P<short_id>[a-f0-9]{7})$", subdomain
        )
        if match:
            project_slug = match.group("project_slug")
            short_id = match.group("short_id")
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Deployment, Project, Team)
                    .join(Project, Deployment.project_id == Project.id)
                    .join(Team, Project.team_id == Team.id)
                    .where(
                        Project.slug == project_slug,
                        Deployment.id.startswith(short_id),
                    )
                )
                deployment, project, team = result.first() or (None, None, None)
                if deployment:
                    return TemplateResponse(
                        request=request,
                        name="error/deployment-not-found.html",
                        status_code=404,
                        context={
                            "current_user": current_user,
                            "deployment_url": request.url_for(
                                "project_deployment",
                                team_slug=team.slug,
                                project_name=project.name,
                                deployment_id=deployment.id,
                            ).include_query_params(action="redeploy"),
                            "deployment_id": deployment.id,
                        },
                    )

        return TemplateResponse(
            request=request,
            name="error/deployment-not-found.html",
            status_code=404,
            context={"current_user": current_user},
        )

    return TemplateResponse(
        request=request,
        name="error/deployment-not-found.html",
        status_code=404,
        context={},
    )


@app.get("/", name="root")
async def root(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Team.slug).where(Team.id == current_user.default_team_id)
    )
    team_slug = result.scalar_one_or_none()
    if team_slug:
        return RedirectResponse(f"/{team_slug}", status_code=302)


app.include_router(auth.router)
app.include_router(user.router)
app.include_router(project.router)
app.include_router(github.router)
app.include_router(google.router)
app.include_router(team.router)
app.include_router(event.router)
app.include_router(bug_report.router)


@app.exception_handler(404)
async def handle_404(request: Request, exc: HTTPException):
    return TemplateResponse(
        request=request, name="error/404.html", status_code=404, context={}
    )


@app.exception_handler(500)
async def handle_500(request: Request, exc: HTTPException):
    return TemplateResponse(
        request=request, name="error/500.html", status_code=500, context={}
    )

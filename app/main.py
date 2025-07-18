import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
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

from routers import auth, project, github, google, team, api, user
from config import get_settings
from db import get_db
from models import User, Team
from dependencies import get_current_user, TemplateResponse

settings = get_settings()

log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(level=log_level)
if log_level > logging.DEBUG:
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    app.state.redis_pool = await create_pool(redis_settings)
    try:
        yield
    finally:
        await app.state.redis_pool.close()


app = FastAPI(
    lifespan=lifespan,
    middleware=[
        Middleware(SessionMiddleware, secret_key=settings.secret_key),
        Middleware(CSRFProtectMiddleware, csrf_secret=settings.secret_key),
    ],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(project.router)
app.include_router(github.router)
app.include_router(google.router)
app.include_router(team.router)
app.include_router(api.router)


@app.middleware("http")
async def _fix_scheme(request: Request, call_next):
    proto = request.headers.get("x-forwarded-proto")
    if proto:
        request.scope["scheme"] = proto
    return await call_next(request)


# TODO: REMOVE
@app.middleware("http")
async def debug_middleware(request: Request, call_next):
    print("\nDEBUG REQUEST HEADERS:")
    for k, v in request.headers.items():
        print(f"{k}: {v}")
    return await call_next(request)


# TODO: REMOVE
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    # Overall timing
    start = time.time()

    # Track DB queries timing
    queries_start = time.time()
    response = await call_next(request)
    queries_duration = time.time() - queries_start

    # Total duration
    duration = time.time() - start

    # Categorize request type
    if request.url.path.startswith("/static"):
        category = "STATIC"
        threshold = 0.05
    else:
        category = "API" if request.url.path.startswith("/api") else "PAGE"
        threshold = 0.1

    status = "SLOW" if duration > threshold else "OK"

    # Only show detailed timing for slow page loads
    if status == "SLOW" and category == "PAGE":
        template_time = duration - queries_duration
        print(f"{status} {category}: {request.method} {request.url.path}")
        print(f"├─ DB Queries: {queries_duration:.3f}s")
        print(f"└─ Template:   {template_time:.3f}s")
        print(f"   TOTAL:      {duration:.3f}s")
    else:
        print(
            f"{status} {category}: {request.method} {request.url.path} - {duration:.3f}s"
        )

    return response


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

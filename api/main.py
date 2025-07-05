from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette_wtf import CSRFProtectMiddleware
import logging

from routers import auth, project, github, team, api
from config import get_settings

settings = get_settings()

app = FastAPI(middleware=[
    Middleware(SessionMiddleware, secret_key=settings.secret_key),
    Middleware(CSRFProtectMiddleware, csrf_secret=settings.secret_key)
])

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth.router)
app.include_router(project.router)
app.include_router(github.router)
app.include_router(team.router)
app.include_router(api.router)

logging.basicConfig(level=logging.INFO if settings.env == 'production' else logging.DEBUG)
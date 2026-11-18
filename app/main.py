from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.redis_client import close_redis
from app.db import database
from app.routers import admin, auth, compress, files, pages, search
from app.services import auth_service


@asynccontextmanager
async def lifespan(app):
    await database.init_pool()
    await auth_service.bootstrap_admin()
    yield
    await close_redis()
    await database.close_pool()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(auth_service.AuthError)
async def auth_error(request: Request, exc: auth_service.AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)
app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(files.router)
app.include_router(compress.router)
app.include_router(search.router)

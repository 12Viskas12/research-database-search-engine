from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.core import logs
from app.core.config import settings
from app.core.redis_client import close_redis, get_redis
from app.db import database
from app.routers import admin, auth, compress, files, pages, search
from app.services import auth_service, metrics_service, vocab_service


async def backfill_vocab():
    try:
        if await vocab_service.needs_rebuild():
            redis = await get_redis()
            await redis.enqueue_job("rebuild_vocab", _job_id="rebuild_vocab_startup")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app):
    await database.init_pool()
    await auth_service.bootstrap_admin()
    await backfill_vocab()
    yield
    await close_redis()
    await database.close_pool()


logs.setup()
app = FastAPI(lifespan=lifespan)
app.middleware("http")(logs.request_logger)


@app.exception_handler(auth_service.AuthError)
async def auth_error(request: Request, exc: auth_service.AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


@app.get("/health")
async def health():
    try:
        await database.get_pool().fetchval("SELECT 1")
        redis = await get_redis()
        await redis.ping()
    except Exception:
        return JSONResponse({"status": "down"}, status_code=503)
    return {"status": "ok"}


@app.get("/metrics")
async def metrics_endpoint(request: Request):
    if settings.metrics_token:
        header = request.headers.get("authorization", "")
        if header != f"Bearer {settings.metrics_token}":
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return PlainTextResponse(
        await metrics_service.collect(), media_type="text/plain; version=0.0.4"
    )


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

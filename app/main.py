from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.redis_client import close_redis
from app.db import database
from app.routers import files, pages, search


@asynccontextmanager
async def lifespan(app):
    await database.init_pool()
    yield
    await close_redis()
    await database.close_pool()


app = FastAPI(lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)
app.include_router(pages.router)
app.include_router(files.router)
app.include_router(search.router)

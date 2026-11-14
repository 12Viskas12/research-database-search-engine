from app.core.redis_client import redis_settings
from app.db import database
from workers.tasks import process_file


async def startup(ctx):
    await database.init_pool()


async def shutdown(ctx):
    await database.close_pool()


class WorkerSettings:
    functions = [process_file]
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 3600

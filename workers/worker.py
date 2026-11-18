from app.core.redis_client import redis_settings
from app.db import database
from workers.tasks import merge_files, pack_file, process_file, reclaim_space, unpack_file


async def startup(ctx):
    await database.init_pool()


async def shutdown(ctx):
    await database.close_pool()


class WorkerSettings:
    functions = [process_file, pack_file, unpack_file, merge_files, reclaim_space]
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 7200

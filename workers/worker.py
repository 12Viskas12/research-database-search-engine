from arq import cron

from app.core import logs
from app.core.redis_client import redis_settings
from app.db import database
from workers.tasks import (
    autopack_files,
    delete_file,
    merge_files,
    pack_file,
    process_file,
    rebuild_vocab,
    reclaim_space,
    recover,
    scan_inbox,
    unpack_file,
)


async def startup(ctx):
    logs.setup("worker")
    await database.init_pool()
    await recover(ctx)


async def shutdown(ctx):
    await database.close_pool()


class WorkerSettings:
    functions = [
        process_file,
        pack_file,
        unpack_file,
        merge_files,
        reclaim_space,
        rebuild_vocab,
        delete_file,
    ]
    cron_jobs = [
        cron(autopack_files, minute={0, 10, 20, 30, 40, 50}, timeout=7200),
        cron(scan_inbox, timeout=600),
    ]
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 7200
    health_check_interval = 30

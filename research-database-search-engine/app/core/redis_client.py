from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings

_pool = None


def redis_settings():
    return RedisSettings.from_dsn(settings.redis_url)


async def get_redis():
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_redis():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

from app.db import database
from app.services import compression_service

GET = "SELECT value FROM app_settings WHERE key = $1"
PUT = (
    "INSERT INTO app_settings (key, value) VALUES ($1, $2) "
    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
)
AUTOPACK = {"enabled": False, "days": 7, "method": "bz2"}


class SettingsError(Exception):
    pass


async def autopack():
    value = await database.get_pool().fetchval(GET, "autopack")
    return {**AUTOPACK, **(value or {})}


async def set_autopack(enabled, days, method):
    if not 0 <= days <= 3650:
        raise SettingsError("Days: 0 to 3650")
    if method not in compression_service.CODECS:
        raise SettingsError("Unknown compression method")
    value = {"enabled": bool(enabled), "days": days, "method": method}
    await database.get_pool().execute(PUT, "autopack", value)
    return value

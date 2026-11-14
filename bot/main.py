import asyncio

from aiogram import Bot, Dispatcher

from app.core.config import settings
from app.db import database
from bot.handlers import router


async def main():
    await database.init_pool()
    bot = Bot(settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await database.close_pool()


if __name__ == "__main__":
    asyncio.run(main())

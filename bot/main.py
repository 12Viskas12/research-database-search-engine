import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.core.config import settings
from app.db import database
from app.services import auth_service
from bot.handlers import router, token_text

log = logging.getLogger("bot")


async def deliver(bot):
    while True:
        try:
            for item in await auth_service.deliveries():
                if item["status"] == "approved":
                    text = token_text(item["token"], item["role"], item["expires_at"])
                else:
                    text = "Заявка отклонена."
                try:
                    await bot.send_message(item["tg_id"], text)
                except (TelegramForbiddenError, TelegramBadRequest):
                    pass
                except Exception:
                    log.exception("delivery failed")
                    continue
                await auth_service.mark_notified(item["id"])
        except Exception:
            log.exception("delivery loop failed")
        await asyncio.sleep(5)


async def main():
    if not settings.bot_token:
        print("BOT_TOKEN is empty, bot is disabled", flush=True)
        return
    await database.init_pool()
    bot = Bot(settings.bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    task = asyncio.create_task(deliver(bot))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await bot.session.close()
        await database.close_pool()


if __name__ == "__main__":
    asyncio.run(main())

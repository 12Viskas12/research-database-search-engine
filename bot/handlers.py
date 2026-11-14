from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.services.search_service import search

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    await message.answer("Отправь запрос, и я найду записи в загруженных файлах.")


@router.message(F.text, ~F.text.startswith("/"))
async def find(message: Message):
    query = message.text.strip()
    if not query:
        return
    items = await search(query, 5, 0)
    if not items:
        await message.answer("Ничего не найдено")
        return
    parts = []
    for i, item in enumerate(items, 1):
        data = item.get("data", item)
        lines = [f"{k}: {v}" for k, v in data.items() if v not in (None, "")]
        parts.append(f"{i}.\n" + "\n".join(lines))
    await message.answer("\n\n".join(parts)[:4096])

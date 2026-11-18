from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from app.core.config import settings
from app.services import auth_service
from app.services.search_service import search

router = Router()

ROLE_NAMES = {"user": "обычный", "vip": "VIP", "admin": "админ"}


def quota_text(quota):
    if quota["limit"] is None:
        return "Запросов: без ограничений"
    return f"Осталось запросов сегодня: {quota['remaining']} из {quota['limit']}"


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Это бот доступа к поиску по данным.\n\n"
        "/request текст: запросить доступ\n"
        "/status: проверить заявку или аккаунт\n\n"
        "Когда аккаунт есть, просто отправь запрос текстом."
    )


@router.message(Command("request"))
async def request(message: Message, command: CommandObject):
    user = message.from_user
    result = await auth_service.create_request(user.id, user.username, command.args)
    if result == "created":
        await message.answer("Заявка отправлена. Когда админ одобрит, я пришлю токен.")
    elif result == "pending":
        await message.answer("Заявка уже на рассмотрении.")
    else:
        await message.answer("У тебя уже есть аккаунт, просто отправь запрос текстом.")


@router.message(Command("status"))
async def status(message: Message):
    info = await auth_service.request_status(message.from_user.id)
    state = info["state"]
    if state == "account":
        account = info["user"]
        await message.answer(
            f"Аккаунт: {account['username']}, роль: {ROLE_NAMES[account['role']]}\n"
            f"{quota_text(info['quota'])}"
        )
    elif state == "none":
        await message.answer("Заявок нет. Отправь /request, чтобы запросить доступ.")
    elif state == "pending":
        await message.answer("Заявка на рассмотрении.")
    elif state == "rejected":
        await message.answer("Заявка отклонена.")
    else:
        req = info["request"]
        if req["used_at"]:
            await message.answer("Токен уже использован.")
        else:
            await message.answer(token_text(req["token"], req["role"], req["expires_at"]))


def token_text(token, role, expires_at):
    return (
        f"Заявка одобрена, роль: {ROLE_NAMES[role]}.\n"
        f"Токен: {token}\n"
        f"Действует до {expires_at:%d.%m.%Y %H:%M} UTC.\n"
        f"Зарегистрируйся на сайте: {settings.site_url}"
    )


@router.message(F.text, ~F.text.startswith("/"))
async def find(message: Message):
    query = message.text.strip()
    if not query:
        return
    user = await auth_service.user_by_tg(message.from_user.id)
    if user is None:
        await message.answer("Сначала нужен аккаунт. Отправь /request.")
        return
    try:
        quota = await auth_service.consume(user)
    except auth_service.AuthError as e:
        await message.answer(str(e))
        return
    items = await search(query, 5, 0)
    if not items:
        await message.answer(f"Ничего не найдено\n\n{quota_text(quota)}")
        return
    parts = []
    for i, item in enumerate(items, 1):
        data = item.get("data", item)
        lines = [f"{k}: {v}" for k, v in data.items() if v not in (None, "")]
        parts.append(f"{i}.\n" + "\n".join(lines))
    text = "\n\n".join(parts)
    footer = f"\n\n{quota_text(quota)}"
    await message.answer(text[: 4096 - len(footer)] + footer)

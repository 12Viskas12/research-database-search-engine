from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.services import audit_service, auth_service, history_service
from app.services.search_service import search

router = Router()

ROLE_NAMES = {"user": "обычный", "vip": "VIP", "admin": "админ"}


def quota_text(quota):
    if quota["limit"] is None:
        return "Запросов: без ограничений"
    return f"Осталось запросов в этом месяце: {quota['remaining']} из {quota['limit']}"


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Это бот доступа к поиску по данным.\n\n"
        "/request текст: запросить доступ\n"
        "/status: проверить заявку или аккаунт\n"
        "/link КОД: привязать аккаунт сайта\n"
        "/id: узнать свой Telegram ID\n\n"
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
            await message.answer(token_text(req["token"], req["role"], req["expires_at"], req["role_days"]))


def term_text(days):
    return f", на {days} дн." if days else ""


def token_text(token, role, expires_at, days=None):
    return (
        f"Заявка одобрена, роль: {ROLE_NAMES[role]}{term_text(days)}.\n"
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
    result = await search(query, 5, 0)
    items = result["items"]
    await history_service.add(user["id"], query, [], "bot", len(items))
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


@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Твой Telegram ID: {message.from_user.id}")


@router.message(Command("link"))
async def link(message: Message, command: CommandObject):
    try:
        user = await auth_service.link_tg(command.args, message.from_user.id)
    except auth_service.AuthError as e:
        await message.answer(str(e))
        return
    await audit_service.log(user, "tg_linked", tg_id=message.from_user.id)
    await message.answer(f"Аккаунт {user['username']} привязан.")


def request_keyboard(request_id):
    def button(text, data):
        return InlineKeyboardButton(text=text, callback_data=f"rq:{request_id}:{data}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Обычный", "user:0"), button("VIP 30 дн.", "vip:30")],
            [button("VIP навсегда", "vip:0"), button("Отклонить", "no")],
        ]
    )


def request_text(item):
    who = f"@{item['tg_username']}" if item["tg_username"] else str(item["tg_id"])
    text = f"Новая заявка #{item['id']}\nОт: {who} ({item['tg_id']})"
    if item["message"]:
        text += f"\nТекст: {item['message']}"
    return text


@router.callback_query(F.data.startswith("rq:"))
async def decide(query: CallbackQuery):
    admin = await auth_service.user_by_tg(query.from_user.id)
    if admin is None or admin["role"] != "admin":
        await query.answer("Нет доступа", show_alert=True)
        return
    parts = query.data.split(":")
    try:
        request_id = int(parts[1])
        if parts[2] == "no":
            await auth_service.reject_request(request_id)
            await audit_service.log(admin, "request_rejected", request=request_id, via="bot")
            result = "отклонена"
        else:
            role, days = parts[2], int(parts[3]) or None
            await auth_service.approve_request(request_id, role, admin["id"], days)
            await audit_service.log(
                admin, "request_approved", request=request_id, role=role, days=days, via="bot"
            )
            result = f"одобрена, {ROLE_NAMES[role]}{term_text(days)}"
    except (ValueError, IndexError):
        await query.answer("Некорректные данные", show_alert=True)
        return
    except auth_service.AuthError as e:
        await query.answer(str(e), show_alert=True)
        if e.status in (404, 409):
            await query.message.edit_reply_markup(reply_markup=None)
        return
    await query.message.edit_text(f"{query.message.text}\n\nЗаявка {result}")
    await query.answer("Готово")

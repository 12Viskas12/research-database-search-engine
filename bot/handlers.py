from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.services import audit_service, auth_service, history_service
from app.services.search_service import search
from bot.texts import error_text, lang_of, tr, T

router = Router()

ADMIN_LANG = "uk"


def quota_text(lang, quota):
    if quota["limit"] is None:
        return tr(lang, "quota_unlimited")
    return tr(lang, "quota", remaining=quota["remaining"], limit=quota["limit"])


def role_name(lang, role):
    return T[lang]["roles"][role]


def term_text(lang, days):
    return tr(lang, "term", days=days) if days else ""


def token_text(lang, token, role, expires_at, days=None):
    return tr(
        lang,
        "token",
        role=role_name(lang, role),
        term=term_text(lang, days),
        token=token,
        until=expires_at,
        site=settings.site_url,
    )


@router.message(CommandStart())
async def start(message: Message):
    await message.answer(tr(lang_of(message.from_user), "start"))


@router.message(Command("request"))
async def request(message: Message, command: CommandObject):
    user = message.from_user
    lang = lang_of(user)
    result = await auth_service.create_request(user.id, user.username, command.args, lang)
    key = {"created": "request_created", "pending": "request_pending"}.get(
        result, "request_account"
    )
    await message.answer(tr(lang, key))


@router.message(Command("status"))
async def status(message: Message):
    lang = lang_of(message.from_user)
    info = await auth_service.request_status(message.from_user.id)
    state = info["state"]
    if state == "account":
        account = info["user"]
        await message.answer(
            tr(
                lang,
                "status_account",
                username=account["username"],
                role=role_name(lang, account["role"]),
                quota=quota_text(lang, info["quota"]),
            )
        )
    elif state == "none":
        await message.answer(tr(lang, "status_none"))
    elif state == "pending":
        await message.answer(tr(lang, "status_pending"))
    elif state == "rejected":
        await message.answer(tr(lang, "status_rejected"))
    else:
        req = info["request"]
        if req["used_at"]:
            await message.answer(tr(lang, "token_used"))
        else:
            await message.answer(
                token_text(lang, req["token"], req["role"], req["expires_at"], req["role_days"])
            )


@router.message(F.text, ~F.text.startswith("/"))
async def find(message: Message):
    lang = lang_of(message.from_user)
    query = message.text.strip()
    if not query:
        return
    user = await auth_service.user_by_tg(message.from_user.id)
    if user is None:
        await message.answer(tr(lang, "need_account"))
        return
    try:
        quota = await auth_service.consume(user)
    except auth_service.AuthError as e:
        await message.answer(error_text(lang, str(e)))
        return
    result = await search(query, 5, 0)
    items = result["items"]
    await history_service.add(user["id"], query, [], "bot", len(items))
    if not items:
        await history_service.missed(user["id"], query, [], "bot")
        await message.answer(tr(lang, "nothing", quota=quota_text(lang, quota)))
        return
    parts = []
    for i, item in enumerate(items, 1):
        data = item.get("data", item)
        lines = [f"{k}: {v}" for k, v in data.items() if v not in (None, "")]
        parts.append(f"{i}.\n" + "\n".join(lines))
    text = "\n\n".join(parts)
    footer = f"\n\n{quota_text(lang, quota)}"
    await message.answer(text[: 4096 - len(footer)] + footer)


@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(tr(lang_of(message.from_user), "your_id", id=message.from_user.id))


@router.message(Command("link"))
async def link(message: Message, command: CommandObject):
    lang = lang_of(message.from_user)
    try:
        user = await auth_service.link_tg(command.args, message.from_user.id)
    except auth_service.AuthError as e:
        await message.answer(error_text(lang, str(e)))
        return
    await audit_service.log(user, "tg_linked", tg_id=message.from_user.id)
    await message.answer(tr(lang, "linked", username=user["username"]))


def request_keyboard(request_id, lang=ADMIN_LANG):
    def button(key, data):
        return InlineKeyboardButton(text=tr(lang, key), callback_data=f"rq:{request_id}:{data}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("btn_user", "user:0"), button("btn_vip30", "vip:30")],
            [button("btn_vip", "vip:0"), button("btn_no", "no")],
        ]
    )


def request_text(item, lang=ADMIN_LANG):
    who = f"@{item['tg_username']}" if item["tg_username"] else str(item["tg_id"])
    text = tr(lang, "new_request", id=item["id"], who=who, tg_id=item["tg_id"])
    if item["message"]:
        text += tr(lang, "request_text", text=item["message"])
    return text


@router.callback_query(F.data.startswith("rq:"))
async def decide(query: CallbackQuery):
    lang = lang_of(query.from_user)
    admin = await auth_service.user_by_tg(query.from_user.id)
    if admin is None or admin["role"] != "admin":
        await query.answer(tr(lang, "denied"), show_alert=True)
        return
    parts = query.data.split(":")
    try:
        request_id = int(parts[1])
        if parts[2] == "no":
            await auth_service.reject_request(request_id)
            await audit_service.log(admin, "request_rejected", request=request_id, via="bot")
            result = tr(lang, "rejected_word")
        else:
            role, days = parts[2], int(parts[3]) or None
            await auth_service.approve_request(request_id, role, admin["id"], days)
            await audit_service.log(
                admin, "request_approved", request=request_id, role=role, days=days, via="bot"
            )
            result = tr(
                lang, "approved_word", role=role_name(lang, role), term=term_text(lang, days)
            )
    except (ValueError, IndexError):
        await query.answer(tr(lang, "bad_data"), show_alert=True)
        return
    except auth_service.AuthError as e:
        await query.answer(error_text(lang, str(e)), show_alert=True)
        if e.status in (404, 409):
            await query.message.edit_reply_markup(reply_markup=None)
        return
    await query.message.edit_text(tr(lang, "request_result", text=query.message.text, result=result))
    await query.answer(tr(lang, "done"))

LANGS = ("uk", "en")

T = {
    "uk": {
        "roles": {"user": "звичайний", "vip": "VIP", "admin": "адмін"},
        "quota_unlimited": "Запитів: без обмежень",
        "quota": "Залишилось запитів цього місяця: {remaining} з {limit}",
        "start": (
            "Це бот доступу до пошуку по даних.\n\n"
            "/request текст: попросити доступ\n"
            "/status: перевірити заявку або акаунт\n"
            "/link КОД: прив'язати акаунт сайту\n"
            "/id: дізнатися свій Telegram ID\n\n"
            "Коли акаунт є, просто надішли запит текстом."
        ),
        "request_created": "Заявку надіслано. Коли адмін схвалить, я надішлю токен.",
        "request_pending": "Заявка вже розглядається.",
        "request_account": "У тебе вже є акаунт, просто надішли запит текстом.",
        "status_account": "Акаунт: {username}, роль: {role}\n{quota}",
        "status_none": "Заявок немає. Надішли /request, щоб попросити доступ.",
        "status_pending": "Заявка розглядається.",
        "status_rejected": "Заявку відхилено.",
        "token_used": "Токен уже використано.",
        "term": ", на {days} дн.",
        "token": (
            "Заявку схвалено, роль: {role}{term}.\nТокен: {token}\n"
            "Діє до {until:%d.%m.%Y %H:%M} UTC.\nЗареєструйся на сайті: {site}"
        ),
        "need_account": "Спочатку потрібен акаунт. Надішли /request.",
        "nothing": "Нічого не знайдено\n\n{quota}",
        "your_id": "Твій Telegram ID: {id}",
        "linked": "Акаунт {username} прив'язано.",
        "btn_user": "Звичайний",
        "btn_vip30": "VIP 30 дн.",
        "btn_vip": "VIP назавжди",
        "btn_no": "Відхилити",
        "new_request": "Нова заявка #{id}\nВід: {who} ({tg_id})",
        "request_text": "\nТекст: {text}",
        "denied": "Немає доступу",
        "bad_data": "Некоректні дані",
        "rejected_word": "відхилено",
        "approved_word": "схвалено, {role}{term}",
        "request_result": "{text}\n\nЗаявку {result}",
        "done": "Готово",
        "request_rejected": "Заявку відхилено.",
        "errors": {
            "Monthly limit reached": "Місячний ліміт вичерпано, скидання 1-го числа о 00:00 UTC",
            "Token is invalid or expired": "Токен недійсний або прострочений",
            "Code is invalid or expired": "Код недійсний або прострочений",
            "This Telegram is already linked to another account": "Цей Telegram уже прив'язано до іншого акаунта",
            "Account is blocked": "Акаунт заблоковано",
            "Request not found": "Заявку не знайдено",
            "Request is already handled": "Заявку вже оброблено",
            "A request can only give the user or vip role": "За заявкою можна видати лише роль user або vip",
            "Term is only for VIP": "Термін задається лише для VIP",
        },
    },
    "en": {
        "roles": {"user": "regular", "vip": "VIP", "admin": "admin"},
        "quota_unlimited": "Searches: unlimited",
        "quota": "Searches left this month: {remaining} of {limit}",
        "start": (
            "This is the access bot for the data search.\n\n"
            "/request text: ask for access\n"
            "/status: check the request or the account\n"
            "/link CODE: link your site account\n"
            "/id: show your Telegram ID\n\n"
            "Once you have an account, just send a query as text."
        ),
        "request_created": "Request sent. When the admin approves it, I will send a token.",
        "request_pending": "The request is already pending.",
        "request_account": "You already have an account, just send a query as text.",
        "status_account": "Account: {username}, role: {role}\n{quota}",
        "status_none": "No requests. Send /request to ask for access.",
        "status_pending": "The request is pending.",
        "status_rejected": "The request was rejected.",
        "token_used": "The token is already used.",
        "term": ", for {days} days",
        "token": (
            "Request approved, role: {role}{term}.\nToken: {token}\n"
            "Valid until {until:%Y-%m-%d %H:%M} UTC.\nRegister on the site: {site}"
        ),
        "need_account": "You need an account first. Send /request.",
        "nothing": "Nothing found\n\n{quota}",
        "your_id": "Your Telegram ID: {id}",
        "linked": "Account {username} linked.",
        "btn_user": "Regular",
        "btn_vip30": "VIP 30 days",
        "btn_vip": "VIP forever",
        "btn_no": "Reject",
        "new_request": "New request #{id}\nFrom: {who} ({tg_id})",
        "request_text": "\nText: {text}",
        "denied": "No access",
        "bad_data": "Invalid data",
        "rejected_word": "rejected",
        "approved_word": "approved, {role}{term}",
        "request_result": "{text}\n\nRequest {result}",
        "done": "Done",
        "request_rejected": "The request was rejected.",
        "errors": {},
    },
}


def lang_of(user):
    code = (getattr(user, "language_code", None) or "").lower()
    return "en" if code.startswith("en") else "uk"


def tr(lang, key, **values):
    table = T.get(lang) or T["uk"]
    text = table[key]
    return text.format(**values) if values else text


def error_text(lang, message):
    for known, translated in (T.get(lang) or T["uk"])["errors"].items():
        if message.startswith(known):
            return translated
    return message

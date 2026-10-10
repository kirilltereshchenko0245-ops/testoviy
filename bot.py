import asyncio
import html
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BusinessConnection
)
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "bot.db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("business-nft-offer")

if not TOKEN:
    raise RuntimeError("Set BOT_TOKEN in environment variables")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS connections(
            connection_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            is_enabled INTEGER NOT NULL, rights TEXT, updated_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            kind TEXT NOT NULL, details TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS button_actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            user_id INTEGER, connection_id TEXT, action TEXT NOT NULL,
            chat_id INTEGER, nft_url TEXT, amount INTEGER)""")


def event(kind, details):
    with db() as c:
        c.execute("INSERT INTO events(created_at,kind,details) VALUES(?,?,?)", (now(), kind, details))


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def notify_admins(text):
    for uid in ADMIN_IDS:
        try:
            await bot.send_message(uid, text)
        except Exception:
            log.exception("Could not notify admin %s", uid)


def safe_url(raw):
    parsed = urlparse(raw)
    return raw if parsed.scheme in ("https", "http") and parsed.netloc else None



async def get_nft_preview(nft_url):
    """Return public Open Graph image/title, if available."""
    timeout = aiohttp.ClientTimeout(total=8)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NFTOfferBot/1.0)"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(nft_url, allow_redirects=True) as response:
                if response.status != 200:
                    return None, None
                content_type = response.headers.get("Content-Type", "")
                if "html" not in content_type.lower():
                    return (str(response.url) if content_type.lower().startswith("image/") else None), None
                page = await response.text(errors="ignore")
        title, image = None, None
        for tag in re.findall(r"<meta\b[^>]*>", page, flags=re.IGNORECASE):
            prop = re.search(r"(?:property|name)\s*=\s*[\"']([^\"']+)[\"']", tag, flags=re.IGNORECASE)
            content = re.search(r"content\s*=\s*[\"']([^\"']+)[\"']", tag, flags=re.IGNORECASE)
            if not prop or not content:
                continue
            key = prop.group(1).lower()
            value = html.unescape(content.group(1).strip())
            if key in ("og:image", "twitter:image") and not image:
                image = urljoin(nft_url, value)
            elif key in ("og:title", "twitter:title") and not title:
                title = value[:150]
        return image, title
    except Exception as exc:
        log.info("Could not fetch NFT preview metadata: %s", exc)
        return None, None


def offer_keyboard(connection_id, chat_id, amount):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отклонить", callback_data=f"nft:decline:{connection_id}:{chat_id}:{amount}"),
        InlineKeyboardButton(text="Принять", callback_data=f"nft:accept:{connection_id}:{chat_id}:{amount}")
    ]])


def render_connections():
    with db() as c:
        rows = c.execute("SELECT * FROM connections ORDER BY updated_at DESC LIMIT 20").fetchall()
    if not rows:
        return "Подключений пока нет."
    return "<b>Business-подключения</b>\n" + "\n".join(
        f"• <code>{r['connection_id']}</code> user=<code>{r['user_id']}</code> active={r['is_enabled']}"
        for r in rows
    )


def render_events():
    with db() as c:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 15").fetchall()
    if not rows:
        return "Событий пока нет."
    return "<b>Последние события</b>\n" + "\n".join(
        f"• {r['created_at']} — <b>{r['kind']}</b>: {r['details'][:220]}" for r in rows
    )


@dp.message(CommandStart())
async def start(message: Message):
    if message.from_user and is_admin(message.from_user.id):
        await message.answer(
            "Бот запущен.\n/admin — панель\n/status — статус\n"
            "/connections — подключения\n/events — журнал\n\n"
            "В Business-чате:\\n.1ofer t.me/nft/Slug-123 500 — NFT-карточка\\n.2ofer https://ссылка 500 — только текст\\n.3ofer https://ссылка 500 — полная карточка\\n.4ofer https://ссылка 500 — без форматирования"
        )
    else:
        await message.answer("Бот работает после подключения владельцем Telegram Business.")


@dp.message(Command("admin"))
async def admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статус", callback_data="admin:status"),
         InlineKeyboardButton(text="Подключения", callback_data="admin:connections")],
        [InlineKeyboardButton(text="Последние события", callback_data="admin:events")]
    ])
    await message.answer("<b>Панель администратора</b>", reply_markup=kb)


@dp.message(Command("status"))
async def status(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM connections").fetchone()["n"]
        active = c.execute("SELECT COUNT(*) n FROM connections WHERE is_enabled=1").fetchone()["n"]
    await message.answer(f"<b>Статус</b>\nПодключений: {total}\nАктивных: {active}")


@dp.message(Command("connections"))
async def connections_cmd(message: Message):
    if message.from_user and is_admin(message.from_user.id):
        await message.answer(render_connections())


@dp.message(Command("events"))
async def events_cmd(message: Message):
    if message.from_user and is_admin(message.from_user.id):
        await message.answer(render_events())


@dp.callback_query(F.data.startswith("admin:"))
async def admin_buttons(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    action = call.data.split(":")[1]
    if action == "status":
        with db() as c:
            total = c.execute("SELECT COUNT(*) n FROM connections").fetchone()["n"]
            active = c.execute("SELECT COUNT(*) n FROM connections WHERE is_enabled=1").fetchone()["n"]
        text = f"<b>Статус</b>\nПодключений: {total}\nАктивных: {active}"
    elif action == "connections":
        text = render_connections()
    else:
        text = render_events()
    await call.message.answer(text)
    await call.answer()


@dp.business_connection()
async def business_connection_handler(connection: BusinessConnection):
    rights = {
        "can_reply": getattr(connection, "can_reply", None),
        "can_read_messages": getattr(connection, "can_read_messages", None),
        "is_enabled": connection.is_enabled,
        "user_chat_id": connection.user_chat_id,
    }
    rights_text = json.dumps(rights, ensure_ascii=False)
    with db() as c:
        c.execute("""INSERT INTO connections VALUES(?,?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET
            user_id=excluded.user_id,is_enabled=excluded.is_enabled,rights=excluded.rights,updated_at=excluded.updated_at""",
            (connection.id, connection.user.id, int(connection.is_enabled), rights_text, now()))
    event("business_connected" if connection.is_enabled else "business_disconnected",
          f"connection_id={connection.id}; user_id={connection.user.id}; rights={rights_text}")
    await notify_admins(
        f"<b>{'Подключение' if connection.is_enabled else 'Отключение'} Telegram Business</b>\n"
        f"Пользователь: <code>{connection.user.id}</code>\n"
        f"Connection ID: <code>{connection.id}</code>\nПрава: <code>{rights_text}</code>"
    )


@dp.business_message()
async def business_message_handler(message: Message):
    text = (message.text or message.caption or "").strip()
    connection_id = getattr(message, "business_connection_id", None)
    log.info("BUSINESS MESSAGE connection=%s chat=%s text=%r",
             connection_id, message.chat.id, text[:200])
    event("business_message_received",
          f"connection_id={connection_id}; chat_id={message.chat.id}; text={text[:150]!r}")

    # Commands .1ofer ... .10ofer; amount is required.
    match = re.fullmatch(r"\.(10|[1-9])ofer\s+(\S+)\s+(\d{1,7})", text, flags=re.IGNORECASE)
    if not match:
        if re.match(r"\.\d+ofer\b", text, flags=re.IGNORECASE):
            event("ofer_usage_error", f"chat_id={message.chat.id}; expected='.N o fer <URL> <amount>'")
        return

    variant = int(match.group(1))
    raw_url = match.group(2)
    amount = int(match.group(3))
    display_url = ("https://" + raw_url) if raw_url.lower().startswith("t.me/") else raw_url
    nft_url = safe_url(display_url)

    if variant == 1 and not raw_url.lower().startswith("t.me/"):
        event("ofer_invalid", f"chat_id={message.chat.id}; variant=1; expected t.me/... link")
        return
    if variant != 1 and not raw_url.lower().startswith(("https://", "http://")):
        event("ofer_invalid", f"chat_id={message.chat.id}; variant={variant}; expected HTTP(S) URL")
        return
    if not nft_url or amount < 1:
        event("ofer_invalid", f"chat_id={message.chat.id}; variant={variant}")
        return
    if not connection_id:
        event("ofer_ignored_no_business_connection", f"chat_id={message.chat.id}")
        return
    with db() as c:
        row = c.execute("SELECT is_enabled FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
    if not row or not row["is_enabled"]:
        event("ofer_ignored_connection_unknown", f"connection_id={connection_id}; chat_id={message.chat.id}")
        return

    try:
        await bot.delete_business_messages(business_connection_id=connection_id, message_ids=[message.message_id])
        event("ofer_command_deleted", f"connection_id={connection_id}; chat_id={message.chat.id}")
    except Exception as exc:
        log.warning("Could not delete command: %s", exc)
        event("delete_command_failed", f"connection_id={connection_id}; chat_id={message.chat.id}; error={exc}")

    # Variants that request media attempt to download the preview locally first.
    media_variants = {1, 3, 5, 7, 9, 10}
    image_url, nft_title = (None, None)
    image_bytes = None
    if variant in media_variants:
        image_url, nft_title = await get_nft_preview(nft_url)
        if image_url:
            try:
                timeout = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as session:
                    async with session.get(image_url, allow_redirects=True) as response:
                        if response.status == 200 and response.headers.get("Content-Type", "").lower().startswith("image/"):
                            data = await response.read()
                            if data and len(data) <= 10 * 1024 * 1024:
                                from aiogram.types import BufferedInputFile
                                suffix = ".jpg"
                                ctype = response.headers.get("Content-Type", "").lower()
                                if "png" in ctype: suffix = ".png"
                                elif "webp" in ctype: suffix = ".webp"
                                elif "gif" in ctype: suffix = ".gif"
                                image_bytes = BufferedInputFile(data, filename="nft-preview" + suffix)
            except Exception as exc:
                log.info("Could not download preview image: %s", exc)

    title = nft_title or "NFT-подарок"
    escaped_title = html.escape(title)
    escaped_url = html.escape(display_url, quote=True)
    keyboard = offer_keyboard(connection_id, message.chat.id, amount)

    # Template matrix: keep variants 1-4 and add distinct 5-10 combinations.
    if variant == 1:
        card_text = f'<a href="{escaped_url}">{escaped_title}</a>'
    elif variant == 2:
        card_text = f"Пользователь предлагает NFT: {escaped_title} за {amount} ⭐ Telegram Stars.\nВыберите действие ниже."
    elif variant == 3:
        card_text = (f'<b>Предложение NFT</b>\n\n<a href="{escaped_url}">{escaped_title}</a>\n'
                     f'Цена: <b>{amount} ⭐ Telegram Stars</b>\n\nПроверьте подарок и выберите действие.')
    elif variant == 4:
        card_text = f"Предложение NFT\n\n{title}\nЦена: {amount} ⭐ Telegram Stars\n\nПроверьте подарок и выберите действие."
    elif variant == 5:
        card_text = f"{title}\nПредложение: {amount} ⭐ Telegram Stars"
    elif variant == 6:
        card_text = f'Предложение NFT: <a href="{escaped_url}">{escaped_title}</a>\nЦена: {amount} ⭐'
    elif variant == 7:
        card_text = f'<b>🎁 Предложение подарка</b>\n\n<a href="{escaped_url}">{escaped_title}</a>\n<b>Цена: {amount} ⭐</b>\n\nВыберите действие.'
    elif variant == 8:
        card_text = f"🎁 ПРЕДЛОЖЕНИЕ\nПодарок: {title}\nСумма: {amount} ⭐\nСсылка: {display_url}"
    elif variant == 9:
        card_text = f'<b>Условия предложения</b>\n\n<a href="{escaped_url}">{escaped_title}</a>\nСумма: <b>{amount} ⭐</b>\nСтатус: ожидает ответа'
    else:  # 10
        card_text = f'<a href="{escaped_url}">{escaped_title}</a> — <b>{amount} ⭐</b>'

    parse_mode = None if variant in (4, 5, 8) else ParseMode.HTML
    try:
        if image_bytes is not None and variant in media_variants:
            await bot.send_photo(
                chat_id=message.chat.id,
                business_connection_id=connection_id,
                photo=image_bytes,
                caption=card_text[:1024],
                reply_markup=keyboard
            )
            preview = "yes"
        else:
            # Fallback to text instead of giving Telegram an inaccessible remote image URL.
            await bot.send_message(
                chat_id=message.chat.id,
                business_connection_id=connection_id,
                text=card_text,
                reply_markup=keyboard,
                parse_mode=parse_mode,
                disable_web_page_preview=(variant in {2, 4, 5, 8})
            )
            preview = "no"
        event("offer_sent", f"connection_id={connection_id}; chat_id={message.chat.id}; variant={variant}; amount={amount}; preview={preview}")
        log.info("NFT offer sent chat=%s variant=%s amount=%s preview=%s", message.chat.id, variant, amount, preview)
    except Exception as exc:
        log.exception("Could not send NFT offer")
        event("offer_send_failed", f"connection_id={connection_id}; chat_id={message.chat.id}; variant={variant}; error={exc}")

@dp.callback_query(F.data.startswith("nft:"))
async def nft_callback(call: CallbackQuery):
    parts = (call.data or "").split(":")
    if len(parts) != 5:
        await call.answer("Не удалось обработать действие.", show_alert=True)
        return
    _, action, connection_id, chat_raw, amount_raw = parts
    amount = int(amount_raw)
    with db() as c:
        c.execute("INSERT INTO button_actions(created_at,user_id,connection_id,action,chat_id,nft_url,amount) VALUES(?,?,?,?,?,?,?)",
                  (now(), call.from_user.id, connection_id, action, int(chat_raw), None, amount))
    event("nft_offer_button", f"user_id={call.from_user.id}; action={action}; chat_id={chat_raw}; amount={amount}")
    await call.answer("Выбор записан.")
    if call.message:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await notify_admins(
        f"<b>Ответ на NFT-предложение</b>\nПользователь ID: <code>{call.from_user.id}</code>\n"
        f"Действие: <b>{'принять' if action == 'accept' else 'отклонить'}</b>\nЦена: <b>{amount} ⭐</b>"
    )


async def main():
    init_db()
    me = await bot.get_me()
    log.info("Starting @%s", me.username)
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "business_connection", "business_message", "edited_business_message"]
    )


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BusinessConnection
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "bot.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("business-bot")

if not TOKEN:
    raise RuntimeError("Set BOT_TOKEN in .env")

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
        c.execute("""CREATE TABLE IF NOT EXISTS connections (
            connection_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            is_enabled INTEGER NOT NULL, rights TEXT, updated_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            kind TEXT NOT NULL, details TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS button_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            user_id INTEGER, connection_id TEXT, action TEXT NOT NULL, chat_id INTEGER
        )""")


def event(kind, details):
    with db() as c:
        c.execute("INSERT INTO events(created_at,kind,details) VALUES(?,?,?)", (now(), kind, details))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def notify_admins(text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            log.exception("Could not notify admin %s", admin_id)


def offer_keyboard(connection_id: str, chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Принять слова", callback_data=f"offer:accept:{connection_id}:{chat_id}"),
        InlineKeyboardButton(text="Отказаться от слов", callback_data=f"offer:decline:{connection_id}:{chat_id}")
    ]])


def render_connections():
    with db() as c:
        rows = c.execute("SELECT * FROM connections ORDER BY updated_at DESC LIMIT 20").fetchall()
    if not rows:
        return "Подключений пока нет."
    lines = ["<b>Business-подключения</b>"]
    for r in rows:
        state = "активно" if r["is_enabled"] else "отключено"
        lines.append(
            f"• ID <code>{r['connection_id']}</code> — user <code>{r['user_id']}</code> — {state}\n"
            f"  Права: <code>{(r['rights'] or 'не указаны')[:180]}</code>"
        )
    return "\n".join(lines)


def render_events():
    with db() as c:
        rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        return "Событий пока нет."
    return "<b>Последние события</b>\n" + "\n".join(
        f"• {r['created_at']} — <b>{r['kind']}</b>: {r['details'][:250]}" for r in rows
    )


@dp.message(CommandStart())
async def start(message: Message):
    if message.from_user and is_admin(message.from_user.id):
        await message.answer(
            "Бот запущен.\n\nКоманды администратора:\n"
            "/admin — панель управления\n/status — состояние и подключения\n"
            "/connections — список Business-подключений\n/events — последние события"
        )
    else:
        await message.answer("Бот работает в Telegram Business после подключения владельцем аккаунта.")


@dp.message(Command("admin"))
async def admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статус", callback_data="admin:status"),
         InlineKeyboardButton(text="Подключения", callback_data="admin:connections")],
        [InlineKeyboardButton(text="Последние события", callback_data="admin:events")]
    ])
    await message.answer("<b>Панель администратора</b>\nВыберите раздел:", reply_markup=kb)


@dp.message(Command("status"))
async def status(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    with db() as c:
        total = c.execute("SELECT COUNT(*) n FROM connections").fetchone()["n"]
        active = c.execute("SELECT COUNT(*) n FROM connections WHERE is_enabled=1").fetchone()["n"]
        count = c.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
    await message.answer(f"<b>Статус</b>\nПодключений: {total}\nАктивных: {active}\nСобытий: {count}")


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
        c.execute("""INSERT INTO connections(connection_id,user_id,is_enabled,rights,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET
        user_id=excluded.user_id,is_enabled=excluded.is_enabled,rights=excluded.rights,updated_at=excluded.updated_at""",
        (connection.id, connection.user.id, int(connection.is_enabled), rights_text, now()))
    kind = "business_connected" if connection.is_enabled else "business_disconnected"
    event(kind, f"connection_id={connection.id}; user_id={connection.user.id}; rights={rights_text}")
    await notify_admins(
        f"<b>{'Подключение Telegram Business' if connection.is_enabled else 'Отключение Telegram Business'}</b>\n"
        f"Пользователь ID: <code>{connection.user.id}</code>\n"
        f"Connection ID: <code>{connection.id}</code>\n"
        f"Активно: <b>{'да' if connection.is_enabled else 'нет'}</b>\n"
        f"Права: <code>{rights_text}</code>"
    )


@dp.business_message()
async def business_message_handler(message: Message):
    text = (message.text or message.caption or "").strip()
    connection_id = getattr(message, "business_connection_id", None)
    log.info("BUSINESS MESSAGE RECEIVED: connection_id=%s chat_id=%s message_id=%s text=%r", connection_id, message.chat.id, message.message_id, text[:200])
    event("business_message_received", f"connection_id={connection_id}; chat_id={message.chat.id}; message_id={message.message_id}; text={text[:120]!r}")
    if not connection_id:
        return
    with db() as c:
        row = c.execute("SELECT is_enabled FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
    if not row or not row["is_enabled"]:
        log.warning("Business message ignored: connection missing/disabled in DB, connection_id=%s", connection_id)
        event("message_ignored_connection_unknown", f"connection_id={connection_id}; chat_id={message.chat.id}")
        return
    if text.casefold() != ".ofer":
        return
    log.info("OFER MATCHED: connection_id=%s chat_id=%s", connection_id, message.chat.id)
    try:
        await bot.delete_business_messages(
            business_connection_id=connection_id,
            message_ids=[message.message_id]
        )
    except Exception as exc:
        log.warning("Could not delete .ofer (check Business rights/API support): %s", exc)
        event("delete_command_failed", f"connection_id={connection_id}; chat_id={message.chat.id}; error={exc}")
    try:
        await bot.send_message(
            chat_id=message.chat.id,
            business_connection_id=connection_id,
            text="<b>привет, как твои дела?</b>",
            reply_markup=offer_keyboard(connection_id, message.chat.id)
        )
        event("offer_sent", f"connection_id={connection_id}; chat_id={message.chat.id}")
    except Exception as exc:
        log.exception("Could not send Business reply")
        event("offer_send_failed", f"connection_id={connection_id}; chat_id={message.chat.id}; error={exc}")


@dp.callback_query(F.data.startswith("offer:"))
async def offer_callback(call: CallbackQuery):
    parts = (call.data or "").split(":")
    if len(parts) != 4:
        await call.answer("Не удалось обработать действие.", show_alert=True)
        return
    _, action, connection_id, chat_id_raw = parts
    chat_id = int(chat_id_raw)
    label = "принять слова" if action == "accept" else "отказаться от слов"
    with db() as c:
        c.execute("INSERT INTO button_actions(created_at,user_id,connection_id,action,chat_id) VALUES(?,?,?,?,?)",
                  (now(), call.from_user.id, connection_id, action, chat_id))
    event("button_action", f"user_id={call.from_user.id}; action={action}; connection_id={connection_id}; chat_id={chat_id}")
    await call.answer("Ваш выбор записан.")
    if call.message:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await notify_admins(
        f"<b>Нажатие кнопки</b>\nПользователь ID: <code>{call.from_user.id}</code>\n"
        f"Выбор: <b>{label}</b>\nЧат ID: <code>{chat_id}</code>"
    )


async def main():
    init_db()
    me = await bot.get_me()
    log.info("Starting @%s", me.username)
    # Removed dp.business_messages_deleted(): it is not available in some aiogram versions
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "business_connection", "business_message", "edited_business_message"]
    )


if __name__ == "__main__":
    asyncio.run(main())

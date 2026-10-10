# Telegram Business Bot

Python 3.11+ bot using aiogram 3 and the official Telegram Business Bot API.

## Features
- Admin-only commands: `/admin`, `/status`, `/connections`, `/events`
- Notifications to configured admin IDs when a Business connection is enabled/disabled
- Watches Business messages for the exact text `.ofer`
- Attempts to delete the command and sends **привет, как твои дела?** with two inline buttons
- Logs button choices and important events in SQLite
- Docker / Docker Compose support

## Setup (VPS)
1. Create a bot with [@BotFather](https://t.me/BotFather), copy its token.
2. Find your numeric Telegram user ID (e.g. via a trusted ID bot).
3. Upload/unzip this project on your server.
4. Create `.env` from the example:
   ```bash
   cp .env.example .env
   nano .env
   ```
   Set `BOT_TOKEN` and `ADMIN_IDS` (comma-separated numeric IDs).
5. Install and run:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python bot.py
   ```
   Or with Docker:
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```

## Telegram Business setup
In Telegram, the account owner must connect the bot through Telegram Business settings and explicitly grant the rights it needs. Availability of Business features depends on Telegram client/account/API support and the rights granted. Test on an account you own or have explicit permission to manage.

## Notes / limitations
- The bot cannot add itself to an account or grant itself rights. The account owner must connect it.
- Deleting `.ofer` is best-effort and requires the appropriate permission/API support. If deletion fails, the bot logs the failure and still attempts to reply.
- Inline button presses are logged and the buttons are removed after the first press. Admins receive a notification.
- Telegram may restrict sending messages via a Business connection based on the connection's rights and chat eligibility.
- Keep `.env` private; never share your bot token. If leaked, revoke it with BotFather.
- This project is a starter implementation; validate it with your current Telegram Bot API/aiogram version before production use.

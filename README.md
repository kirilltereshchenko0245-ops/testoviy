# Telegram Business Bot — fixed build

## Setup
1. Set `BOT_TOKEN` and `ADMIN_IDS` in the host's Environment Variables.
2. Install command: `pip install -r requirements.txt`
3. Start command: `python bot.py`
4. Connect the bot in Telegram Business settings and grant only the permissions you need.

## Admin commands
`/admin`, `/status`, `/connections`, `/events`

The app notifies configured admins about Business connections and disconnections. It watches Business messages for the exact `.ofer` command, attempts to delete it if Telegram permissions allow, then replies with bold text and two inline buttons. Button actions are logged and reported to admins.

The unavailable `dp.business_messages_deleted()` decorator was removed to fix the startup crash in the screenshot. Keep the token private. Test on an account you own or are authorized to manage.

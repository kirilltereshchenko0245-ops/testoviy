# Telegram Business NFT offer bot

Deploy command: `python bot.py`
Build/install command: `pip install -r requirements.txt`

Set `BOT_TOKEN` and `ADMIN_IDS` as environment variables.

In a Business chat, use:
`.ofer https://your-nft-link.example/item/123 500`

The bot attempts to delete the command (requires Telegram permissions), then sends a custom offer card with the NFT page's public image/title when available, the amount in Telegram Stars, and Accept/Decline buttons. The URL itself is not shown in the card text. This is a custom bot message, not Telegram's official native gift card. The command format is `.ofer <NFT URL> 500`. The URL is accepted as command input but is not sent to the recipient or shown in the card. It does not create an actual marketplace transaction or transfer an NFT/Stars. Button presses are logged and admins are notified. Test only with chats/accounts you are authorized to manage.

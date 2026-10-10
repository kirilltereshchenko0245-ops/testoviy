# Telegram Business NFT offer bot

Deploy command: `python bot.py`
Build/install command: `pip install -r requirements.txt`

Set `BOT_TOKEN` and `ADMIN_IDS` as environment variables.

In a Business chat, use:
`.ofer https://your-nft-link.example/item/123 500`

The bot attempts to delete the command (requires Telegram permissions), then sends a custom NFT link-preview offer with a stated price in Telegram Stars and Accept/Decline buttons. It does not create an actual Telegram marketplace transaction or transfer an NFT/Stars. Button presses are logged and admins are notified.

The NFT link preview is supplied by Telegram from the URL's page metadata; a preview may not appear for every URL. Test only with chats/accounts you are authorized to manage.

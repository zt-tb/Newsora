# Security Policy

Please do not open a public issue for a vulnerability.

Report it privately to Mohsen Al-Taie on Telegram: [@K0_MG](https://t.me/K0_MG), or through GitHub's private vulnerability reporting on this repository.

Include the affected version, steps to reproduce and the impact.

## What to protect

- The control panel answers only the account in `OWNER_ID`, in a private chat with the bot.
- The Telegram user session (`session.txt`) gives full access to the account it belongs to. It is stored as plain text in `DATA_DIR` with `0600` permissions. Keep `DATA_DIR` on a private volume and never commit it.
- AI provider keys added from the panel are stored in `keys.json` in `DATA_DIR`, also as plain text with `0600` permissions.
- Login codes, 2FA passwords and API keys sent to the bot are deleted from the chat right after they are read. The session shown by the "show session" button is deleted after 2 minutes.
- `.env`, `data/` and session files are ignored by Git. Do not remove them from `.gitignore`.

If a bot token, `API_HASH`, session or key is ever exposed, revoke it immediately: revoke the bot token with [@BotFather](https://t.me/BotFather), end the session from Telegram under Settings, Devices, and rotate the AI keys at their providers.

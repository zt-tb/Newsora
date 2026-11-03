<div align="center">

# Newsora

**Telegram bot that moves news from other channels to your channel: it reads the sources you choose, translates the posts to Arabic, removes duplicates and publishes them for you.**

English · [العربية](README.ar.md)

<a href="https://github.com/zt-tb/Newsora/actions/workflows/checks.yml"><img src="https://github.com/zt-tb/Newsora/actions/workflows/checks.yml/badge.svg" alt="Checks" /></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT%20%2B%20Attribution-2ea44f?style=flat" alt="License" /></a>
<img src="https://img.shields.io/badge/Telegram-Bot%20(Kurigram)-26A5E4?logo=telegram&logoColor=white" alt="Telegram Bot" />
<img src="https://img.shields.io/badge/Reader-Telethon-1F6FEB" alt="Telethon" />
<img src="https://img.shields.io/badge/AI-multi--provider%20failover-8A2BE2" alt="AI providers" />
<img src="https://img.shields.io/badge/FFmpeg-optional-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg" />
<img src="https://img.shields.io/badge/docs-Arabic%20%7C%20English-green" alt="Languages" />

<a href="https://t.me/K0_MG"><img src="https://img.shields.io/badge/Telegram-@K0__MG-26A5E4?logo=telegram&logoColor=white" alt="Telegram @K0_MG" /></a>
<a href="https://instagram.com/z0_28"><img src="https://img.shields.io/badge/Instagram-z0__28-E4405F?logo=instagram&logoColor=white" alt="Instagram z0_28" /></a>
<a href="https://www.tiktok.com/@zt_tb"><img src="https://img.shields.io/badge/TikTok-@zt__tb-000000?logo=tiktok&logoColor=white" alt="TikTok @zt_tb" /></a>
<a href="https://youtube.com/@M7JN"><img src="https://img.shields.io/badge/YouTube-@M7JN-FF0000?logo=youtube&logoColor=white" alt="YouTube @M7JN" /></a>
<a href="https://github.com/zt-tb"><img src="https://img.shields.io/badge/GitHub-zt--tb-181717?logo=github&logoColor=white" alt="GitHub zt-tb" /></a>

</div>

> **Open source with attribution.** Newsora is released under the MIT License with an attribution requirement. You may use, modify and share it, but you must keep the [NOTICE](NOTICE) file and the copyright headers, and credit the original author, **Mohsen Al-Taie (@K0_MG)**. See [LICENSE](LICENSE).

## What it does

Newsora moves news from other Telegram channels (the **sources**) to your own channel (the **target**), automatically and on a schedule. You manage everything from a private control panel inside the bot.

How a post travels:

1. You write your channel in `TARGET_CHANNEL` and add the source channels you want to follow from the panel. Nothing is added for you.
2. Your Telegram account joins the sources and listens for new posts (text, photos, videos, files and albums).
3. Each new post is cleaned, translated to Arabic, and checked: it must not be a duplicate and it must pass your word filters.
4. Posts that pass wait in a queue. Breaking news goes first.
5. The bot (or your account) publishes them to your channel, with gaps between posts, inside your daily limit and publishing hours.

| Feature | Details |
|---|---|
| **Reading** | Your own Telegram account reads the source channels (Telethon). Text, photos, videos, files and albums are supported |
| **Translation to Arabic** | A chain of AI providers with automatic failover (Gemini, Groq, NVIDIA, OpenRouter, Mistral, a custom OpenAI-compatible provider, Claude, OpenAI), ending with Google Translate. Numbers in the translation are checked against the original |
| **Duplicate protection** | Five layers: same file, similar image or video (even re-encoded), same text, same story in another wording or language, and an AI verdict for gray cases |
| **Breaking news first** | Posts with breaking words and event words jump the queue and are published immediately with a breaking header |
| **Unconfirmed label** | Posts with wording such as "reportedly" or "unconfirmed" get an "unconfirmed news" label. You can also mark weak sources, and all their posts get the label |
| **Topic hashtags** | Hashtags are added automatically from the topic of the post |
| **Filters** | Block list (any post containing a word is ignored) and allow list (only posts containing one of the words are published) |
| **Source deletes and edits** | If the source deletes a post that is still in the queue, it is removed here. If the source edits it, the edited version is used |
| **Two ways to publish** | Through the bot, or through your own account (needed for animated custom emoji in channels; the account must be Premium and an admin of the channel) |
| **Daily report** | A summary sent to you privately at 10 PM Iraq time: posted, duplicates, filtered, and the state of each AI provider |
| **Optional, experimental** | Video speech transcription (ffmpeg and Groq Whisper) and reading text inside images (Gemini Vision). Both are off by default and can make mistakes, so test them on a few channels first |

## Default behavior

These are the defaults in `config.py`. All of them can be changed from the panel.

| Setting | Default |
|---|---|
| Gap between posts | random between 30 and 90 minutes |
| Daily limit | 20 posts |
| Publishing hours | 7 to 24, Iraq time (`Asia/Baghdad`) |
| Age of a post in the queue | 2 hours, older posts are dropped even if unpublished |
| Queue size | 40 posts |
| Minimum text length | 40 characters |
| Duplicate window | 48 hours (the record of published fingerprints keeps the last 40,000) |
| Source channels | none, you add your own |
| Signature on posts | none, you can set one with `POST_SIGNATURE` |
| Breaking news bypass, unconfirmed label, topic hashtags, daily report | on |
| Source line, video transcription, image text reading | off |

## Setup

**Requirements:** a Telegram bot token from [@BotFather](https://t.me/BotFather), `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org), your numeric Telegram ID (you can get it from [@userinfobot](https://t.me/userinfobot)), and a channel where the bot is an admin with permission to post.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `API_ID`, `API_HASH` | Yes | From my.telegram.org |
| `BOT_TOKEN` | Yes | From @BotFather |
| `OWNER_ID` | Yes | Your numeric Telegram ID. The only account allowed to use the panel |
| `TARGET_CHANNEL` | Yes | **Write your channel here**: the channel the posts are published to, as `@username` or a numeric ID. The bot will not start without it |
| `POST_SIGNATURE` | No | Text added under every post, for example your channel name and link. Use `\n` for a new line |
| `DATA_DIR` | No | Folder for settings, session, keys and the duplicate record. Default `data` |
| `SESSION_STRING` | No | Backup session. A session extracted from the panel takes priority |
| `MAX_MEDIA_MB` | No | Largest media file to handle. Default `100` |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY` | No | Free AI providers. You can also add them from the panel |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | No | Paid providers, used last. `OPENAI_BASE_URL` sets a custom OpenAI endpoint |
| `CUSTOM_LLM_BASE`, `CUSTOM_LLM_KEY`, `CUSTOM_LLM_MODEL` | No | Any OpenAI-compatible provider |
| `LLM_ORDER` | No | Provider order, for example `gemini,groq,nvidia`. Default: gemini, groq, nvidia, openrouter, mistral, custom, anthropic, openai |
| `GEMINI_MODELS`, `GROQ_MODELS`, `WHISPER_MODEL` | No | Model names, comma separated. Change them if a model is removed from a free plan |

Without any AI key, translation still works through Google Translate.

### Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file from `.env.example`, load its values as environment variables, then:

```bash
python main.py
```

Install `ffmpeg` only if you want video transcription.

### Deploy on Railway

1. Push the project to a GitHub repository (never commit `.env` or `data/`).
2. In Railway choose **New Project, Deploy from GitHub repo**. `Procfile` starts the worker (`python main.py`) and `nixpacks.toml` installs ffmpeg.
3. Add `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID` and `TARGET_CHANNEL` under **Variables**.
4. **Important:** create a **Volume**, attach it to the bot service on `/data`, and set `DATA_DIR=/data`. Without it, every deploy wipes the session, keys, settings and the duplicate record. If you get a permissions error, add `RAILWAY_RUN_UID=0`.
5. A new deploy causes a short stop, and you cannot run two copies of the service with one Volume.

## Write your channel and your sources

- **Your channel (where posts are published):** write it in `TARGET_CHANNEL`, for example `TARGET_CHANNEL=@your_channel_here`, or use its numeric ID. Add the bot to that channel as an admin with permission to post. If you publish through your account, that account must be an admin of the channel too.
- **Source channels (where news is taken from):** there are none by default. In the panel press **Sources**, then **Add source**, and send each channel as a username (`@name`), a `t.me/name` link, or a numeric ID. You can send several at once, one per line. If the reader account is connected, it joins them automatically, 3 to 7 seconds apart to avoid Telegram limits. Invite links that start with `+` are not accepted. For a private channel your account already joined, send its numeric ID.
- **Remove a source:** press **Sources**, then **Delete source**, and send its number from the list or its username.

## First run

1. Open the bot from your account and send `/start`. The panel works only for `OWNER_ID`.
2. **Extract session** (the panel is in Arabic): choose phone number or QR, then activate. With a phone number, type the code separated by dashes, like `1-2-3-4-5`, so Telegram does not cancel it. With QR, open Telegram on another device, go to Settings, Devices, Link a device, and scan the image.
3. **AI** (optional): add a Gemini key and a Groq key, both free, then press the real test button.
4. **Sources**: add the channels you want to follow (see the section above). To join your account to all of them again, press the join button.
5. Press **Full check**. It sends a silent message to the channel and deletes it, to confirm publishing works.

## Control panel

Send `/start` or `/panel` to the bot in a private chat. `/cancel` cancels the current step.

| Button | What it does |
|---|---|
| Status | Reader connection, queue, daily count, last post, duplicates ignored, last error |
| Full check | Real tests of publishing, providers and ffmpeg |
| Stop or start publishing | Pauses and resumes the whole system |
| Sources | Add, delete, and join the account to source channels |
| Settings | Translation on or off, publish through bot or account, gap, daily limit, queue age, hours |
| Extract session | Phone or QR login, activate, show or delete the saved session |
| Publish now | Publishes the newest post in the queue within seconds |
| AI | Provider keys and a real test of each provider |
| Smart features | Switches for breaking news, unconfirmed label, source line, hashtags, transcription, image text, daily report |
| Filters | Block words, allow words and weak sources |
| Restart reader | Reconnects the reading account |

## Project files

| File | Purpose |
|---|---|
| `main.py` | Starts the bot, the panel and the engine |
| `engine.py` | Reader, queue, duplicate checks, translation and publishing |
| `panel.py` | The owner-only control panel |
| `login.py` | Session extraction by phone or QR |
| `llm.py` | AI provider chain with failover |
| `textproc.py` | Text cleaning, translation and caption building |
| `filters.py` | Breaking news score, unconfirmed detection, word filters, topic hashtags |
| `dedupe.py` | Duplicate detection |
| `media.py` | Video transcription and image text reading |
| `emojis.py` | Animated emoji support |
| `store.py` | Settings, session, keys and fingerprint storage |
| `config.py` | Environment variables, signature and default hashtags |

To sign every post, set `POST_SIGNATURE`. To change the default hashtags, edit `HASHTAGS` in `config.py`.

## Responsible use

Newsora republishes content from other channels. You choose the sources, and you are responsible for what you publish, for respecting copyright and Telegram's terms, and for the accuracy of the news. Turn on the source line from the smart features if you want to credit where each post came from. Use your own account for the reader and keep its session private. See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Credit

If you use Newsora or build on it, please credit the author in your README or bot description, for example: *Based on Newsora by Mohsen Al-Taie (@K0_MG)*. Redistributions must keep the `NOTICE` file.

To cite it, use [CITATION.cff](CITATION.cff) (GitHub shows a "Cite this repository" button).

## Author

**Mohsen Al-Taie**

<div align="center">

<img src="assets/divider.svg" width="100%" alt="" />

### 📱 Follow Me | تابعني

<div dir="ltr">

<a href="https://t.me/K0_MG"><img src="assets/social/telegram.svg" width="72" alt="Telegram @K0_MG" /></a>
<a href="https://instagram.com/z0_28"><img src="assets/social/instagram.svg" width="72" alt="Instagram z0_28" /></a>
<a href="https://www.tiktok.com/@zt_tb"><img src="assets/social/tiktok.svg" width="72" alt="TikTok @zt_tb" /></a>
<a href="https://youtube.com/@M7JN"><img src="assets/social/youtube.svg" width="72" alt="YouTube @M7JN" /></a>
<a href="https://github.com/zt-tb"><img src="assets/social/github.svg" width="72" alt="GitHub zt-tb" /></a>

</div>

[Telegram @K0_MG](https://t.me/K0_MG) · [Instagram z0_28](https://instagram.com/z0_28) · [TikTok @zt_tb](https://www.tiktok.com/@zt_tb) · [YouTube @M7JN](https://youtube.com/@M7JN) · [GitHub zt-tb](https://github.com/zt-tb)

<img src="assets/divider.svg" width="100%" alt="" />

</div>

Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See [LICENSE](LICENSE).

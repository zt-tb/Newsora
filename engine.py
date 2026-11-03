# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import asyncio
import hashlib
import inspect
import logging
import os
import random
import shutil
import tempfile
import time
from datetime import datetime, timedelta

from telethon import TelegramClient, events, errors as tgerr
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityCustomEmoji, MessageMediaWebPage

from pyrogram import errors as pgerr
from pyrogram.enums import MessageEntityType
from pyrogram.types import InputMediaPhoto, InputMediaVideo, MessageEntity

import config
import dedupe
import filters
import llm
import media
import store
import textproc as tp
from emojis import find_custom

logger = logging.getLogger("engine")

_FATAL_SESSION = tuple(
    getattr(tgerr, n) for n in (
        "AuthKeyUnregisteredError", "SessionRevokedError", "SessionExpiredError",
        "UserDeactivatedError", "UserDeactivatedBanError", "AuthKeyDuplicatedError",
    ) if hasattr(tgerr, n)
)
_EMOJI_ERR_KEYS = ("EMOJI", "ENTIT", "PREMIUM", "DOCUMENT_INVALID")


def iraq_now() -> datetime:
    return datetime.now(config.IRAQ_TZ)


class Job:
    __slots__ = ("kind", "msgs", "source", "created", "attempts", "raw_tok", "score", "urgent", "title")

    def __init__(self, kind, msgs, source):
        self.kind, self.msgs, self.source = kind, msgs, source
        self.created = time.monotonic()
        self.attempts = 0
        self.raw_tok = []
        self.score = 0
        self.urgent = False
        self.title = ""


class _FixedParse:

    def __init__(self, text, entities):
        self.text, self.entities = text, entities

    def parse(self, t):
        return (t, list(self.entities)) if t == self.text else (t, [])

    def unparse(self, t, e):
        return t


class Engine:
    def __init__(self, bot, settings: store.Settings, hashes: store.HashStore, notify):
        self.bot = bot
        self.s = settings
        self.hashes = hashes
        self.dd = dedupe.Dedupe(hours=settings.get("dedupe_hours"))
        self.notify = notify
        self.client = None
        self.me = None
        self.queue = []
        self._pending = {}
        self._tasks = []
        self._stop = False
        self._force = False
        self.daily = 0
        self._day = None
        self._rich_blocked_until = 0.0
        self.last_error = ""
        self.last_post_at = None
        self._nopreview = self._detect_nopreview()
        self._last_post_mono = 0.0
        self._report_day = None
        self.counters = dict(posted=0, dup=0, fail=0, filtered=0, urgent=0, deleted=0, expired=0)

    def _detect_nopreview(self):
        try:
            params = inspect.signature(self.bot.send_message).parameters
            if "link_preview_options" in params:
                from pyrogram.types import LinkPreviewOptions
                return {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
            if "disable_web_page_preview" in params:
                return {"disable_web_page_preview": True}
        except Exception:
            pass
        return {}

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected() and self.me)

    def me_name(self) -> str:
        if not self.me:
            return "-"
        u = getattr(self.me, "username", None)
        return f"@{u}" if u else (getattr(self.me, "first_name", None) or str(self.me.id))

    async def start(self):
        if iraq_now().hour >= 22:
            self._report_day = iraq_now().date()
        self._tasks = [
            asyncio.create_task(self._worker()),
            asyncio.create_task(self._keepalive()),
        ]
        session = store.load_session()
        if session:
            ok, msg = await self.start_reader(session)
            logger.info("reader: %s", msg)
        else:
            logger.warning("لا يوجد سيشن. استخرجه من لوحة التحكم (🔑 استخراج سيشن).")

    async def shutdown(self):
        self._stop = True
        for t in self._tasks:
            t.cancel()
        await self.stop_reader()

    async def stop_reader(self):
        c, self.client, self.me = self.client, None, None
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass

    async def start_reader(self, session: str):
        await self.stop_reader()
        client = TelegramClient(
            StringSession(session), config.API_ID, config.API_HASH,
            connection_retries=-1, retry_delay=3, auto_reconnect=True,
        )
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return False, "السيشن غير صالح أو منتهي، استخرج سيشن جديد."
            me = await client.get_me()
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            return False, f"{type(e).__name__}: {e}"
        client.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        client.add_event_handler(self._on_deleted, events.MessageDeleted())
        client.add_event_handler(self._on_edited, events.MessageEdited(incoming=True))
        self.client, self.me = client, me
        return True, f"القارئ شغّال بحساب {self.me_name()}"

    async def _keepalive(self):
        while not self._stop:
            try:
                await asyncio.sleep(random.uniform(1500, 1900))
                c = self.client
                if not c:
                    continue
                if not c.is_connected():
                    await c.connect()
                await c.get_me()
                logger.info("[ALIVE] ping ok")
            except asyncio.CancelledError:
                break
            except _FATAL_SESSION as e:
                logger.error("session dead: %s", e)
                await self.stop_reader()
                await self._safe_notify("⚠️ السيشن انتهت أو انحذفت من الأجهزة. استخرج سيشن جديد من اللوحة.")
            except Exception as e:
                logger.warning("keepalive: %s", e)

    async def _safe_notify(self, text):
        try:
            await self.notify(text)
        except Exception as e:
            logger.warning("notify failed: %s", e)

    @staticmethod
    def norm_source(raw: str):
        s = (raw or "").strip()
        s = s.replace("https://", "").replace("http://", "")
        for p in ("t.me/s/", "t.me/", "telegram.me/"):
            if s.lower().startswith(p):
                s = s[len(p):]
        s = s.lstrip("@").split("/")[0].split("?")[0].strip()
        if not s or s.startswith("+") or s.lower() == "joinchat":
            return None
        if s.lstrip("-").isdigit():
            return s
        if not all(ch.isalnum() or ch == "_" for ch in s) or len(s) < 4:
            return None
        return s

    def _source_set(self):
        return {x.lower() for x in self.s.get("sources")}

    async def _match_source(self, event):
        srcs = self._source_set()
        names = {str(event.chat_id)}
        title = ""
        try:
            chat = await event.get_chat()
            title = getattr(chat, "title", "") or ""
            u = getattr(chat, "username", None)
            if u:
                names.add(u.lower())
            for un in getattr(chat, "usernames", None) or []:
                names.add(un.username.lower())
        except Exception:
            pass
        hit = names & srcs
        return (next(iter(hit)), title) if hit else None

    async def join_sources(self, only=None):
        if not self.client:
            return None
        from telethon.tl.functions.channels import JoinChannelRequest
        ok, fail = [], []
        for src in (only or self.s.get("sources")):
            try:
                ent = await self.client.get_entity(int(src) if src.lstrip("-").isdigit() else src)
                await self.client(JoinChannelRequest(ent))
                ok.append(src)
            except tgerr.UserAlreadyParticipantError:
                ok.append(src)
            except tgerr.FloodWaitError as e:
                fail.append(f"{src} (انتظار {e.seconds}ث)")
                if e.seconds > 120:
                    break
                await asyncio.sleep(e.seconds + 2)
            except Exception as e:
                fail.append(f"{src} ({type(e).__name__})")
            await asyncio.sleep(random.uniform(3, 7))
        return ok, fail

    async def _on_message(self, event):
        try:
            if not self.s.get("enabled") or not (event.is_channel or event.is_group):
                return
            matched = await self._match_source(event)
            if not matched:
                return
            src, title = matched
            msg = event.message
            gid = msg.grouped_id
            if gid:
                if gid not in self._pending:
                    self._pending[gid] = []
                    asyncio.create_task(self._collect_group(gid, src, title))
                self._pending[gid].append(msg)
                return
            if msg.gif or msg.video or msg.photo:
                self._enqueue(Job("single", [msg], src), title)
            elif (msg.media is None or isinstance(msg.media, MessageMediaWebPage)) and msg.raw_text:
                if len(tp.clean_text(msg.raw_text)) >= self.s.get("min_text_len"):
                    self._enqueue(Job("text", [msg], src), title)
        except Exception:
            logger.exception("handler error")

    async def _on_deleted(self, event):
        try:
            ids, cid = set(event.deleted_ids or []), getattr(event, "chat_id", None)
            before = len(self.queue)
            self.queue[:] = [j for j in self.queue if not any(
                m.id in ids and (cid is None or getattr(m, "chat_id", None) == cid) for m in j.msgs)]
            if len(self.queue) != before:
                self.counters["deleted"] += before - len(self.queue)
                logger.info("[QUEUE] source deleted %d queued post(s) → removed", before - len(self.queue))
        except Exception:
            logger.exception("deleted handler error")

    async def _on_edited(self, event):
        try:
            m = event.message
            for j in self.queue:
                for i, old in enumerate(j.msgs):
                    if old.id == m.id and getattr(old, "chat_id", None) == getattr(m, "chat_id", None):
                        j.msgs[i] = m
                        logger.info("[QUEUE] source edited a queued post → updated")
        except Exception:
            logger.exception("edited handler error")

    async def _collect_group(self, gid, src, title=""):
        await asyncio.sleep(random.uniform(2.0, 4.0))
        msgs = [m for m in self._pending.pop(gid, []) if (m.photo or m.video or m.gif)]
        if msgs:
            msgs.sort(key=lambda m: m.id)
            self._enqueue(Job("group", msgs[:10], src), title)

    def _enqueue(self, job: Job, title: str = ""):
        job.title = title
        raw = next((m.raw_text for m in job.msgs if m.raw_text), "")
        if not filters.passes_filters(raw, self.s.get("blacklist"), self.s.get("whitelist")):
            self.counters["filtered"] += 1
            logger.info("[FILTER] dropped by keyword filters (source %s)", job.source)
            return
        job.score = filters.urgency(raw, any(getattr(m, "video", None) or getattr(m, "gif", None) for m in job.msgs))
        job.urgent = job.score >= 3
        job.raw_tok = dedupe.tokens(tp.clean_text(raw))
        if len(job.raw_tok) >= 6:
            for j in self.queue:
                if dedupe.similarity(job.raw_tok, j.raw_tok)[0] >= 0.8:
                    logger.info("[QUEUE] duplicate of a queued job from %s → dropped", j.source)
                    return
        self.queue.append(job)
        mx = self.s.get("queue_max")
        while len(self.queue) > mx:
            self.queue.pop(0)
        logger.info("[QUEUE] +%s from %s | urgency=%d | size=%d", job.kind, job.source, job.score, len(self.queue))
        if job.urgent and self.s.get("breaking_bypass") \
                and time.monotonic() - self._last_post_mono >= self.s.get("urgent_gap"):
            self._force = True

    def _purge(self) -> int:
        ttl = self.s.get("ttl_hours") * 3600
        now = time.monotonic()
        before = len(self.queue)
        self.queue[:] = [j for j in self.queue if now - j.created <= ttl]
        n = before - len(self.queue)
        if n:
            self.counters["expired"] = self.counters.get("expired", 0) + n
            logger.info("[QUEUE] %d stale job(s) expired (> %sh)", n, self.s.get("ttl_hours"))
        return n

    def _pick(self):
        self._purge()
        if not self.queue:
            return None
        best = max(self.queue, key=lambda j: (j.score, j.created))
        self.queue.remove(best)
        return best

    def _reset_daily(self):
        today = iraq_now().date()
        if self._day != today:
            self._day, self.daily = today, 0
            self.counters = dict.fromkeys(self.counters, 0)

    async def _maybe_report(self):
        now = iraq_now()
        if not self.s.get("daily_report") or now.hour < 22 or self._report_day == now.date():
            return
        self._report_day = now.date()
        c = self.counters
        lines = ["📊 تقرير اليوم", f"🏆 منشور: {c['posted']} (عاجل: {c['urgent']})",
                 f"🚫 مكرر تم تجاهله: {c['dup']} | مفلتر بالكلمات: {c['filtered']} | محذوف من المصدر: {c['deleted']} | انتهت صلاحيته: {c['expired']}",
                 f"☄️ فشل نشر: {c['fail']} | الطابور الآن: {len(self.queue)}"]
        for r in llm.status_rows():
            if r['configured']:
                lines.append(f"🤖 {r['label']}: نجح {r['ok']} / فشل {r['err']} / مرفوض {r['invalid']}")
        if self.last_error != "":
            lines.append(f"آخر خطأ: {self.last_error[:150]}")
        await self._safe_notify("\n".join(lines))

    def _active(self) -> bool:
        h = iraq_now().hour
        a, b = self.s.get("active_start"), self.s.get("active_end")
        return a <= h < b if b < 24 else a <= h <= 23

    def _factor(self) -> float:
        lim = max(1, self.s.get("daily_limit"))
        r = (lim - self.daily) / lim
        for th, f in ((0.05, 4.0), (0.15, 3.0), (0.25, 2.0), (0.4, 1.5), (0.6, 1.2)):
            if r <= th:
                return f
        return 1.0

    def _interval(self) -> float:
        mn, mx = self.s.get("min_interval"), self.s.get("max_interval")
        base = random.uniform(mn, max(mn, mx)) * self._factor()
        return max(30.0, base + random.uniform(-0.1 * mn, 0.2 * mn))

    async def _sleep(self, seconds: float):
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._stop:
            if self._force:
                self._force = False
                return
            await asyncio.sleep(2)

    def force_next(self):
        self._force = True

    async def _worker(self):
        logger.info("[WORKER] started")
        while not self._stop:
            try:
                await self._maybe_report()
                self._purge()
                if not self.s.get("enabled") or not self._active():
                    self._force = False
                    await asyncio.sleep(20)
                    continue
                self._reset_daily()
                if self.daily >= self.s.get("daily_limit"):
                    await self._sleep(300)
                    continue
                job = self._pick()
                if job is None:
                    self._force = False
                    await asyncio.sleep(3)
                    continue
                outcome = await self._process(job)
                if outcome == "retry":
                    job.attempts += 1
                    if job.attempts < 3:
                        self.queue.insert(0, job)
                    await self._sleep(60)
                elif outcome == "posted":
                    iv = self._interval()
                    logger.info("[SCHED] next post in %.1f min (~%s Iraq)", iv / 60,
                                (iraq_now() + timedelta(seconds=iv)).strftime("%H:%M"))
                    await self._sleep(iv)
                else:
                    await self._sleep(random.uniform(5, 20))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("worker error")
                self.last_error = f"{type(e).__name__}: {e}"
                await asyncio.sleep(30)

    async def _media_extras(self, files, kinds, tmp) -> str:
        try:
            if self.s.get("transcribe") and media.transcription_ready():
                for p, k in zip(files, kinds):
                    if k in ("video", "gif"):
                        spoken = await media.video_speech_text(p, tmp)
                        if spoken:
                            ar, how = await tp.translate_news(spoken)
                            if ar:
                                return "🎙 ترجمة صوتية آلية:\n" + ar[:400]
                        break
            if self.s.get("ocr") and media.vision_ready():
                for p, k in zip(files, kinds):
                    if k == "photo":
                        seen = await media.image_text(p)
                        if seen:
                            return "🖼 النص داخل الصورة:\n" + seen[:400]
                        break
        except Exception as e:
            logger.warning("media extras failed: %s: %s", type(e).__name__, e)
        return ""

    async def _thumb_hash(self, m, tmp):
        try:
            p = await m.download_media(file=os.path.join(tmp, f"th{m.id}"), thumb=-1)
            if p:
                return await asyncio.to_thread(dedupe.dhash, p)
        except Exception as e:
            logger.debug("thumb hash failed: %s", e)
        return None

    @staticmethod
    def _sha256(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 16):
                h.update(chunk)
        return h.hexdigest()

    async def _process(self, job: Job) -> str:
        tmp = None
        try:
            raw = next((m.raw_text for m in job.msgs if m.raw_text), "")
            cleaned = tp.clean_text(raw)
            if job.kind == "text" and not cleaned:
                return "skipped"

            body = cleaned
            if cleaned and self.s.get("translate"):
                body, how = await tp.translate_news(cleaned)
                if how == "skip":
                    logger.info("[SKIP] ad/promo detected by LLM")
                    return "skipped"
                if body is None:
                    logger.warning("[TRANS] all providers failed (attempt %d)", job.attempts + 1)
                    return "retry"

            fp = tp.fingerprint(body)
            if fp and self.hashes.has(fp):
                logger.info("[SKIP] duplicate text")
                self.counters["dup"] += 1
                return "skipped"
            if body:
                is_dup, why = await self.dd.is_dup_text(body)
                if is_dup:
                    logger.info("[SKIP] same news already posted — %s", why)
                    self.counters["dup"] += 1
                    return "skipped"

            files, kinds, metas, media_hashes, phashes = [], [], [], [], []
            group_hash = None
            if job.kind != "text":
                await asyncio.sleep(random.uniform(1, 4))
                limit = config.MAX_MEDIA_MB * 1024 * 1024
                tmp = tempfile.mkdtemp(prefix="job_", dir=config.TMP_DIR)
                dup_items = 0
                for m in job.msgs:
                    kind = "gif" if m.gif else "video" if m.video else "photo"
                    f = getattr(m, "file", None)
                    dur = getattr(f, "duration", 0) or 0
                    if (getattr(f, "size", 0) or 0) > limit:
                        logger.info("[SKIP] media too large (%d MB)", f.size >> 20)
                        return "skipped"
                    ph = None
                    if kind != "photo":
                        ph = await self._thumb_hash(m, tmp)
                        if self.dd.media_dup(ph, "video", dur):
                            dup_items += 1
                            if job.kind == "single":
                                logger.info("[SKIP] same video already posted (visual match)")
                                self.counters["dup"] += 1
                                return "skipped"
                    path = await m.download_media(file=tmp + os.sep)
                    if not path:
                        raise RuntimeError("download returned no file")
                    if kind == "photo":
                        ph = await asyncio.to_thread(dedupe.dhash, path)
                        if self.dd.media_dup(ph, "photo"):
                            dup_items += 1
                    files.append(path)
                    kinds.append(kind)
                    metas.append({k: v for k, v in (("duration", dur), ("width", getattr(f, "width", None)),
                                                    ("height", getattr(f, "height", None))) if v})
                    phashes.append((ph, "photo" if kind == "photo" else "video", dur))
                    media_hashes.append(await asyncio.to_thread(self._sha256, path))
                if dup_items and dup_items * 2 >= len(job.msgs):
                    logger.info("[SKIP] same image/video already posted (visual match)")
                    self.counters["dup"] += 1
                    return "skipped"
                if len(files) == 1:
                    group_hash = media_hashes[0]
                else:
                    c = hashlib.sha256()
                    for h in sorted(media_hashes):
                        c.update(h.encode())
                    group_hash = "g:" + c.hexdigest()
                if self.hashes.has(group_hash) or any(self.hashes.has(h) for h in media_hashes):
                    logger.info("[SKIP] duplicate media")
                    self.counters["dup"] += 1
                    return "skipped"

            extra = ""
            if files and len(body) < 120:
                extra = await self._media_extras(files, kinds, tmp)
                if extra:
                    is_dup, why = await self.dd.is_dup_text(extra)
                    if is_dup:
                        logger.info("[SKIP] spoken/visible text already posted — %s", why)
                        self.counters["dup"] += 1
                        return "skipped"
            body_full = (body + "\n\n" + extra).strip() if extra else body

            has_vid = any(k in ("video", "gif") for k in kinds)
            urgent = job.urgent or filters.urgency(raw or body_full, has_vid) >= 3
            head = "⚡️ عاجل\n" if urgent and "عاجل" not in body_full[:40] else ""
            labels = []
            weak = job.source.lower() in {x.lower() for x in self.s.get("weak_sources")}
            if self.s.get("label_unverified") and (weak or filters.looks_unverified(raw)):
                labels.append("⚠️ خبر غير مؤكد")
            if self.s.get("attribution") and job.title:
                labels.append(f"📡 المصدر: {job.title}")
            tags = filters.smart_hashtags(f"{raw} {body_full}", urgent) if self.s.get("smart_hashtags") else None
            text = tp.build_caption(body_full, 4096 if job.kind == "text" else 1024, hashtags=tags, labels=labels, head=head)
            ents = find_custom(text)
            await self._publish(job.kind, files, kinds, metas, text, ents)

            if job.kind != "text":
                self.hashes.add(group_hash)
                for h in media_hashes:
                    self.hashes.add(h)
                for ph in phashes:
                    self.dd.add_media(*ph)
            if fp:
                self.hashes.add(fp)
            if body_full:
                self.dd.add_text(body_full)
            self.daily += 1
            self.counters["posted"] += 1
            if urgent:
                self.counters["urgent"] += 1
            self.last_post_at = iraq_now()
            self._last_post_mono = time.monotonic()
            logger.info("[POST] %s from %s | today %d/%d", job.kind, job.source, self.daily, self.s.get("daily_limit"))
            return "posted"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.counters["fail"] += 1
            logger.exception("[ERROR] processing failed")
            return "failed"
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    async def _publish(self, kind, files, kinds, metas, text, ents):
        if self.s.get("post_mode") == "user" and self.client:
            await self._retrying(lambda: self._user_call(kind, files, kinds, text, ents))
        else:
            await self._send_bot(kind, files, kinds, metas, text, ents)

    async def _retrying(self, factory, tries=4):
        for i in range(tries):
            try:
                return await factory()
            except pgerr.FloodWait as e:
                await asyncio.sleep(e.value + random.uniform(3, 8))
            except tgerr.FloodWaitError as e:
                await asyncio.sleep(e.seconds + random.uniform(3, 8))
            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                if i == tries - 1:
                    raise
                await asyncio.sleep(2 ** (i + 1) + random.uniform(1, 4))
        raise RuntimeError("send retries exhausted")

    async def _send_bot(self, kind, files, kinds, metas, text, ents):
        use_rich = bool(ents) and time.time() >= self._rich_blocked_until
        try:
            return await self._retrying(lambda: self._bot_call(kind, files, kinds, metas, text, ents if use_rich else None))
        except pgerr.BadRequest as e:
            if use_rich and any(k in str(e).upper() for k in _EMOJI_ERR_KEYS):
                logger.warning("custom emoji rejected by channel via bot (%s) → plain emoji for 6h. "
                               "للإيموجي المتحرك بالقناة اجعل وضع النشر: حسابك.", e)
                self._rich_blocked_until = time.time() + 6 * 3600
                return await self._retrying(lambda: self._bot_call(kind, files, kinds, metas, text, None))
            raise

    async def _bot_call(self, kind, files, kinds, metas, text, ents):
        bot, tgt = self.bot, config.TARGET_CHANNEL
        ce = [MessageEntity(type=MessageEntityType.CUSTOM_EMOJI, offset=o, length=l, custom_emoji_id=i)
              for o, l, i in ents] if ents else None
        if kind == "text":
            return await bot.send_message(tgt, text, entities=ce, **self._nopreview)
        if kind == "single":
            k, p, meta = kinds[0], files[0], metas[0]
            if k == "photo":
                return await bot.send_photo(tgt, p, caption=text, caption_entities=ce)
            if k == "gif":
                return await bot.send_animation(tgt, p, caption=text, caption_entities=ce, **meta)
            return await bot.send_video(tgt, p, caption=text, caption_entities=ce, supports_streaming=True, **meta)
        media = []
        for i, (p, k) in enumerate(zip(files, kinds)):
            cap, cents = (text, ce) if i == 0 else ("", None)
            if k == "photo":
                media.append(InputMediaPhoto(p, caption=cap, caption_entities=cents))
            else:
                media.append(InputMediaVideo(p, caption=cap, caption_entities=cents, supports_streaming=True, **metas[i]))
        return await bot.send_media_group(tgt, media)

    async def _user_call(self, kind, files, kinds, text, ents):
        c, tgt = self.client, config.TARGET_CHANNEL
        fp = _FixedParse(text, [MessageEntityCustomEmoji(offset=o, length=l, document_id=i) for o, l, i in ents])
        if kind == "text":
            return await c.send_message(tgt, text, parse_mode=fp, link_preview=False)
        if kind == "single":
            return await c.send_file(tgt, files[0], caption=text, parse_mode=fp, supports_streaming=True)
        return await c.send_file(tgt, files, caption=[text] + [""] * (len(files) - 1), parse_mode=fp,
                                 supports_streaming=True)

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "account": self.me_name(),
            "enabled": self.s.get("enabled"),
            "queue": len(self.queue),
            "daily": self.daily,
            "limit": self.s.get("daily_limit"),
            "sources": len(self.s.get("sources")),
            "mode": self.s.get("post_mode"),
            "last_post": self.last_post_at.strftime("%H:%M") if self.last_post_at else "-",
            "last_error": self.last_error or "-",
            "rich_blocked": time.time() < self._rich_blocked_until,
            "dedupe": dict(self.dd.stats),
            "counters": dict(self.counters),
            "llm_last": llm.last_used["label"],
        }

    async def self_test(self) -> list:
        out = []
        if config.ON_RAILWAY or config.PERSISTENT:
            out.append(("تخزين دائم (Volume)", config.PERSISTENT,
                        "مربوط ✅" if config.PERSISTENT else "غير مربوط — السجل والسيشن يضيعون مع كل نشر جديد"))
        out.append(("القارئ (حسابك)", self.connected, self.me_name() if self.connected else "غير متصل — استخرج سيشن"))

        text = "⚡️ فحص النشر — سيتم حذف هذه الرسالة"
        ents = find_custom(text)
        for label, mode_ents in (("النشر بالبوت (نص)", None), ("إيموجي متحرك بالقناة (بوت)", ents)):
            try:
                ce = [MessageEntity(type=MessageEntityType.CUSTOM_EMOJI, offset=o, length=l, custom_emoji_id=i)
                      for o, l, i in mode_ents] if mode_ents else None
                m = await self.bot.send_message(config.TARGET_CHANNEL, text, entities=ce,
                                                disable_notification=True, **self._nopreview)
                await asyncio.sleep(1.5)
                try:
                    await m.delete()
                except Exception:
                    pass
                out.append((label, True, "ناجح"))
            except Exception as e:
                out.append((label, False, f"{type(e).__name__}: {str(e)[:120]}"))

        if self.client:
            try:
                fp = _FixedParse(text, [MessageEntityCustomEmoji(offset=o, length=l, document_id=i) for o, l, i in ents])
                m = await self.client.send_message(config.TARGET_CHANNEL, text, parse_mode=fp, silent=True)
                await asyncio.sleep(1.5)
                await m.delete()
                out.append(("النشر بحسابك + إيموجي متحرك", True, "ناجح"))
            except Exception as e:
                out.append(("النشر بحسابك + إيموجي متحرك", False, f"{type(e).__name__}: {str(e)[:120]}"))

        gk = llm.get("groq")
        miss = [x for x, bad in (("ffmpeg", not media.ffmpeg_available()), ("مفتاح Groq", not (gk and gk.key()))) if bad]
        out.append(("تفريغ كلام الفيديو (اختياري)", not miss, "جاهز" if not miss else "ينقص: " + " + ".join(miss)))
        out.append(("قراءة نص الصور (اختياري)", media.vision_ready(),
                    "جاهز" if media.vision_ready() else "ينقص: مفتاح Gemini"))
        try:
            res, how = await tp.translate_news("Breaking: talks resumed in Geneva on Monday, officials said.")
            out.append(("الترجمة", bool(res), f"{llm.last_used['label']} → {res}" if res else "فشلت كل المزودين"))
        except Exception as e:
            out.append(("الترجمة", False, f"{type(e).__name__}: {e}"))
        return out

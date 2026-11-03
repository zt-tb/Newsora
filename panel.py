# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import asyncio
import html
import inspect
import logging
import os
import re
import struct

from pyrogram import errors as pgerr, filters
from pyrogram.enums import MessageEntityType, ParseMode
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity

try:
    from pyrogram.enums import ButtonStyle
except ImportError:
    ButtonStyle = None

import config
import llm
import store
import textproc as tp
from emojis import find_custom, icon, icon_id
from login import LoginManager, make_qr_png

logger = logging.getLogger("panel")

PRIMARY, SUCCESS, DANGER = "primary", "success", "danger"


def _detect_button_features():
    try:
        params = inspect.signature(InlineKeyboardButton.__init__).parameters
    except Exception:
        params = {}
    style_ok = ButtonStyle is not None and "style" in params
    icon_param = next((n for n in ("icon_custom_emoji_id", "custom_emoji_id", "icon") if n in params), None)
    return style_ok, icon_param


STYLE_OK, ICON_PARAM = _detect_button_features()
_STYLE_MAP = {}
if STYLE_OK:
    _STYLE_MAP = {PRIMARY: ButtonStyle.PRIMARY, SUCCESS: ButtonStyle.SUCCESS, DANGER: ButtonStyle.DANGER}
logger.info("[UI] ButtonStyle=%s | icon param=%s", STYLE_OK, ICON_PARAM)
if not STYLE_OK:
    logger.warning("[UI] مكتبتك ما تدعم ButtonStyle. ثبّت:  pip install -U 'kurigram>=2.2.26'  (وامسح pyrogram القديمة)")


class B:
    __slots__ = ("label", "data", "style", "icon")

    def __init__(self, label, data, style, icon_name=None):
        assert style in (PRIMARY, SUCCESS, DANGER), "كل زر لازم يكون ملوّن"
        self.label, self.data, self.style, self.icon = label, data, style, icon_name


def build_markup(rows, icons=True, styled=True):
    out = []
    for row in rows:
        r = []
        for b in row:
            kw = {"callback_data": b.data}
            text = b.label
            if b.icon:
                if icons and ICON_PARAM:
                    kw[ICON_PARAM] = icon_id(b.icon)
                else:
                    text = f"{icon(b.icon)} {b.label}"
            if styled and STYLE_OK:
                kw["style"] = _STYLE_MAP[b.style]
            r.append(InlineKeyboardButton(text, **kw))
        out.append(r)
    return InlineKeyboardMarkup(out)


def mk_entities(text):
    ents = [MessageEntity(type=MessageEntityType.CUSTOM_EMOJI, offset=o, length=l, custom_emoji_id=i)
            for o, l, i in find_custom(text)]
    return ents or None


TIERS = [(True, True, True), (True, False, True), (False, False, True), (False, False, False)]
_UI_KEYS = ("EMOJI", "ENTIT", "BUTTON", "PREMIUM", "STYLE", "DOCUMENT", "KEYBOARD", "MARKUP")


def _is_ui_error(e) -> bool:
    if isinstance(e, (TypeError, ValueError, AttributeError, KeyError, struct.error)):
        return True
    if isinstance(e, pgerr.RPCError):
        return any(k in str(e).upper() for k in _UI_KEYS)
    return False


def _back(to="home"):
    return [B("رجوع", to, PRIMARY)]


class Panel:
    def __init__(self, app, engine, settings):
        self.app, self.engine, self.s = app, engine, settings
        self.login = LoginManager()
        self.pending = None
        self.tier = 0
        self._qr_msg = None

    def register(self):
        owner = filters.user(config.OWNER_ID) & filters.private
        a = self.app
        a.add_handler(MessageHandler(self.on_start, owner & filters.command(["start", "panel"])))
        a.add_handler(MessageHandler(self.on_cancel_cmd, owner & filters.command("cancel")))
        a.add_handler(MessageHandler(self.on_text, owner & filters.text & ~filters.command(["start", "panel", "cancel"])))
        a.add_handler(CallbackQueryHandler(self.on_cb, filters.user(config.OWNER_ID)))

    async def notify(self, text):
        await self._send(text, [[B("فتح اللوحة", "home", PRIMARY, "shield")]])

    async def _tiered(self, make):
        last, i = None, self.tier
        while i < len(TIERS):
            rich, icons, styled = TIERS[i]
            try:
                try:
                    res = await make(rich, icons, styled)
                except pgerr.FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                    res = await make(rich, icons, styled)
                if i > self.tier:
                    logger.warning("[UI] نزلنا للمستوى %d (التفاصيل بالسجل أعلاه)", i)
                    self.tier = i
                return res
            except pgerr.MessageNotModified:
                return None
            except Exception as e:
                if not _is_ui_error(e):
                    raise
                logger.warning("[UI] tier %d failed: %s: %s", i, type(e).__name__, e)
                last, i = e, i + 1
        raise last

    async def _send(self, text, rows=None, chat_id=None):
        chat_id = chat_id or config.OWNER_ID

        async def make(rich, icons, styled):
            return await self.app.send_message(
                chat_id, text, entities=mk_entities(text) if rich else None,
                reply_markup=build_markup(rows, icons, styled) if rows else None)
        return await self._tiered(make)

    async def _edit(self, msg, text, rows=None):
        if msg is None:
            return await self._send(text, rows)

        async def make(rich, icons, styled):
            return await self.app.edit_message_text(
                msg.chat.id, msg.id, text, entities=mk_entities(text) if rich else None,
                reply_markup=build_markup(rows, icons, styled) if rows else None)
        try:
            return await self._tiered(make)
        except pgerr.RPCError as e:
            if _is_ui_error(e):
                raise
            logger.warning("edit failed (%s) → sending new message", e)
            return await self._send(text, rows)

    async def _send_photo(self, path, caption, rows):
        async def make(rich, icons, styled):
            return await self.app.send_photo(
                config.OWNER_ID, path, caption=caption, caption_entities=mk_entities(caption) if rich else None,
                reply_markup=build_markup(rows, icons, styled))
        return await self._tiered(make)

    async def _delete(self, msg):
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass

    async def _autodel(self, msg, seconds):
        await asyncio.sleep(seconds)
        await self._delete(msg)

    def home(self):
        st = self.engine.status()
        en = st["enabled"]
        text = (
            "🛡 لوحة تحكم المطوّر — بوت الأخبار\n"
            "━━━━━━━━━━━━━━\n"
            f"👁 القارئ: {'متصل ✅ ' + st['account'] if st['connected'] else 'غير متصل ❌'}\n"
            f"⚡️ النشر: {'شغّال ✅' if en else 'متوقف ⏸'}\n"
            f"🤖 وضع النشر: {'حسابك' if st['mode'] == 'user' else 'البوت'}\n"
            f"✉️ الطابور: {st['queue']}   🏆 منشور اليوم: {st['daily']}/{st['limit']}\n"
            f"🔍 المصادر: {st['sources']}"
        )
        rows = [
            [B("الحالة", "status", PRIMARY, "eye"), B("فحص شامل", "check", PRIMARY, "search")],
            [B("إيقاف النشر" if en else "تشغيل النشر", "toggle", DANGER if en else SUCCESS, "block" if en else "bolt")],
            [B("المصادر", "src", PRIMARY, "mail"), B("الإعدادات", "set", PRIMARY, "shield")],
            [B("استخراج سيشن", "ses", SUCCESS, "lock"), B("نشر فوري", "force", SUCCESS, "bolt")],
            [B("الذكاء الاصطناعي", "ai", PRIMARY, "robot"), B("ميزات ذكية", "smart", PRIMARY, "hacker")],
            [B("الفلاتر", "flt", PRIMARY, "block"), B("إعادة تشغيل القارئ", "restart", PRIMARY, "comet")],
        ]
        return text, rows

    def status_screen(self):
        st = self.engine.status()
        ui_icons = self.tier == 0 and bool(ICON_PARAM)
        text = (
            "👁 الحالة التفصيلية\n━━━━━━━━━━━━━━\n"
            f"القارئ: {'متصل ✅ ' + st['account'] if st['connected'] else 'غير متصل ❌'}\n"
            f"النشر: {'شغّال' if st['enabled'] else 'متوقف'}  |  وضع النشر: {'حسابك' if st['mode'] == 'user' else 'البوت'}\n"
            f"الترجمة: {tp.provider_name() if self.s.get('translate') else 'معطّلة'}\n"
            f"الطابور: {st['queue']}  |  اليوم: {st['daily']}/{st['limit']}  |  آخر نشر: {st['last_post']}\n"
            f"المصادر: {st['sources']}\n"
            f"الفاصل: {self.s.get('min_interval') // 60}-{self.s.get('max_interval') // 60} دقيقة  |  "
            f"ساعات النشر: {self.s.get('active_start')}-{self.s.get('active_end')} (توقيت العراق)\n"
            f"أزرار ملونة: {'✅' if STYLE_OK else '❌ حدّث kurigram'}  |  أيقونات متحركة بالأزرار: {'✅' if ui_icons else '❌'}\n"
            f"إيموجي متحرك بمنشورات القناة عبر البوت: {'❌ مرفوض (استخدم وضع حسابك)' if st['rich_blocked'] else '✅/غير مفحوص'}\n"
            f"آخر مزوّد ترجمة استُخدم: {st['llm_last']}\n"
            f"🏆 اليوم: منشور {st['counters']['posted']} (عاجل {st['counters']['urgent']}) | مفلتر {st['counters']['filtered']} | "
            f"محذوف من المصدر {st['counters']['deleted']} | فشل {st['counters']['fail']}\n"
            f"🚫 مكرر تم تجاهله — نص: {st['dedupe']['text']} | صور/فيديو: {st['dedupe']['media']} | حكم AI: {st['dedupe']['judge']}\n"
            f"☄️ آخر خطأ: {st['last_error']}"
        )
        return text, [[B("تحديث", "status", SUCCESS, "bolt")], _back()]

    def sources_screen(self):
        srcs = self.s.get("sources")
        lines, total = [], 0
        for i, x in enumerate(srcs, 1):
            line = f"{i}. {x if x.lstrip('-').isdigit() else '@' + x}"
            total += len(line) + 1
            if total > 3300:
                lines.append(f"… و{len(srcs) - i + 1} مصدر آخر")
                break
            lines.append(line)
        text = f"✉️ المصادر ({len(srcs)})\n━━━━━━━━━━━━━━\n" + "\n".join(lines)
        rows = [
            [B("إضافة مصدر", "src_add", SUCCESS, "plus"), B("حذف مصدر", "src_del", DANGER, "trash")],
            [B("انضمام الحساب للمصادر", "src_join", PRIMARY, "user")],
            _back(),
        ]
        return text, rows

    def settings_screen(self):
        s = self.s
        tr, user = s.get("translate"), s.get("post_mode") == "user"
        text = (
            "🛡 الإعدادات\n━━━━━━━━━━━━━━\n"
            f"المزوّد: {tp.provider_name()}\n"
            "• النشر عبر «حسابك» يضمن ظهور الإيموجي المتحرك داخل القناة (حسابك لازم Premium وأدمن بالقناة).\n"
            "• النشر عبر «البوت» أبسط، لكن تيليجرام قد يعرض الإيموجي المتحرك بالقنوات كإيموجي عادي."
        )
        rows = [
            [B(f"الترجمة: {'مفعّلة' if tr else 'معطّلة'}", "set_tr", SUCCESS if tr else DANGER, "bolt")],
            [B(f"النشر عبر: {'حسابك' if user else 'البوت'}", "set_mode", PRIMARY, "robot")],
            [B(f"الفاصل: {s.get('min_interval') // 60}-{s.get('max_interval') // 60} د", "set_int", PRIMARY, "alarm")],
            [B(f"الحد اليومي: {s.get('daily_limit')}", "set_lim", PRIMARY, "trophy")],
            [B(f"عمر الخبر بالطابور: {s.get('ttl_hours'):g} س", "set_ttl", PRIMARY, "bolt")],
            [B(f"ساعات النشر: {s.get('active_start')}-{s.get('active_end')}", "set_hours", PRIMARY, "calendar")],
            _back(),
        ]
        return text, rows

    SMART = [
        ("breaking_bypass", "العاجل ينشر فوراً", "bolt"),
        ("label_unverified", "وسم «خبر غير مؤكد»", "warn"),
        ("attribution", "ذكر اسم المصدر", "mail"),
        ("smart_hashtags", "هاشتاقات حسب الخبر", "search"),
        ("transcribe", "تفريغ كلام الفيديو", "music"),
        ("ocr", "قراءة نص الصور", "eye"),
        ("daily_report", "تقرير يومي 10 مساءً", "calendar"),
    ]

    def smart_screen(self):
        import media
        lines = ["🧠 الميزات الذكية\n━━━━━━━━━━━━━━",
                 "• العاجل: يكتشف الأخبار العاجلة (كلمات + نوع الحدث) وينشرها فوراً بترويسة ⚡️ عاجل.",
                 "• غير مؤكد: يوسم الأخبار اللي فيها «يزعم/بحسب مصادر/reportedly…» أو القادمة من «مصادر غير موثّقة».",
                 "• تفريغ الفيديو: يحتاج ffmpeg ومفتاح Groq — " + ("✅ جاهز" if media.transcription_ready() else "❌ غير جاهز"),
                 "• قراءة الصور: تحتاج مفتاح Gemini — " + ("✅ جاهز" if media.vision_ready() else "❌ غير جاهز"),
                 "الميزتان الأخيرتان تجريبيتان (الدقة تختلف حسب الفيديو/الصورة) فهما مطفأتان افتراضياً."]
        rows = []
        for key, label, ic in self.SMART:
            on = self.s.get(key)
            rows.append([B(f"{label}: {'✅' if on else '⛔'}", f"tg:{key}", SUCCESS if on else DANGER, ic)])
        rows.append(_back())
        return "\n".join(lines), rows

    def filters_screen(self):
        bl, wl, weak = self.s.get("blacklist"), self.s.get("whitelist"), self.s.get("weak_sources")
        text = (
            "🚫 الفلاتر\n━━━━━━━━━━━━━━\n"
            f"الكلمات الممنوعة ({len(bl)}): {'، '.join(bl) if bl else '—'}\n"
            f"الكلمات المطلوبة ({len(wl)}): {'، '.join(wl) if wl else '—'}\n"
            f"المصادر غير الموثّقة ({len(weak)}): {'، '.join(weak) if weak else '—'}\n\n"
            "• أي منشور فيه كلمة ممنوعة يُتجاهل.\n"
            "• إذا حددت كلمات مطلوبة: ينشر فقط المنشورات اللي تحتوي وحدة منها (بأي لغة).\n"
            "• منشورات المصادر غير الموثّقة تأخذ وسم «خبر غير مؤكد»."
        )
        rows = [
            [B("كلمة ممنوعة", "flt_bl", SUCCESS, "plus"), B("مسح الممنوعة", "flt_bl_clear", DANGER, "trash")],
            [B("كلمة مطلوبة", "flt_wl", SUCCESS, "plus"), B("مسح المطلوبة", "flt_wl_clear", DANGER, "trash")],
            [B("مصدر غير موثّق (إضافة/إزالة)", "flt_weak", PRIMARY, "user")],
            _back(),
        ]
        return text, rows

    def ai_screen(self):
        lines = ["🤖 مزوّدو الذكاء الاصطناعي (بالترتيب، إذا فشل واحد ينتقل للتالي)", "━━━━━━━━━━━━━━"]
        for r in llm.status_rows():
            mark = "✅" if r["configured"] else "⚪"
            lines.append(f"{mark} {r['label']} — {r['state']}  (نجح {r['ok']} | فشل {r['err']} | مرفوض {r['invalid']})")
        lines.append("")
        lines.append("آخر خطوة احتياطية دائماً: Google Translate (بدون مفتاح).")
        lines.append("مفاتيح مجانية بدون بطاقة بنكية:")
        lines.append("• Gemini: aistudio.google.com  • Groq: console.groq.com")
        lines.append("• NVIDIA: build.nvidia.com  • OpenRouter: openrouter.ai  • Mistral: console.mistral.ai")
        lines.append("اضغط على المزوّد وأرسل مفتاحه (يُحفظ عندك، ورسالتك تنحذف فوراً).")
        rows, pair = [], []
        for p in llm.KEY_PROVIDERS:
            pair.append(B(("✓ " if p.key() else "") + p.label.split(" (")[0], f"ai_key:{p.name}",
                          SUCCESS if p.key() else PRIMARY, "lock" if p.key() else "plus"))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
        rows.append([B("فحص حقيقي للمزوّدين", "ai_test", SUCCESS, "search")])
        rows.append(_back())
        return "\n".join(lines), rows

    def session_screen(self):
        has = bool(store.load_session())
        text = (
            "🔐 استخراج السيشن (حسابك أنت فقط)\n━━━━━━━━━━━━━━\n"
            f"السيشن المحفوظ: {'موجود ✅' if has else 'لا يوجد ❌'}\n"
            f"القارئ: {'متصل ✅ ' + self.engine.me_name() if self.engine.connected else 'غير متصل'}\n\n"
            "• بالرقم: يوصلك كود بتيليجرام، اكتبه مفصولاً بشرطات (1-2-3-4-5) حتى لا يبطله تيليجرام.\n"
            "• عبر QR (الأضمن): افتح تيليجرام من جهاز ثاني > الإعدادات > الأجهزة > ربط جهاز، وامسح الصورة.\n"
            "السيشن يُحفظ بملفات البوت ويُرسل لك هنا فقط."
        )
        rows = [
            [B("بالرقم", "ses_phone", SUCCESS, "user"), B("عبر QR", "ses_qr", SUCCESS, "lock")],
            [B("تفعيل السيشن المحفوظ", "ses_apply", PRIMARY, "comet"), B("عرض السيشن", "ses_show", PRIMARY, "eye")],
            [B("حذف السيشن", "ses_del", DANGER, "trash")],
            _back(),
        ]
        return text, rows

    async def on_start(self, client, message):
        self.pending = None
        await self.login.cancel()
        await self._send(*self.home())

    async def on_cancel_cmd(self, client, message):
        await self._cancel_all()
        await self._send("تم الإلغاء.", self.home()[1])

    async def _cancel_all(self):
        self.pending = None
        await self.login.cancel()
        await self._delete(self._qr_msg)
        self._qr_msg = None

    async def on_cb(self, client, cq):
        data, msg = cq.data, cq.message
        try:
            await cq.answer()
        except Exception:
            pass
        try:
            await self._route(data, msg)
        except Exception as e:
            logger.exception("callback %s failed", data)
            try:
                await self._send(f"☄️ خطأ: {type(e).__name__}: {str(e)[:300]}", [_back()])
            except Exception:
                pass

    async def _route(self, d, msg):
        e, s = self.engine, self.s
        if d == "home":
            await self._cancel_all()
            return await self._edit(msg, *self.home())
        if d == "status":
            return await self._edit(msg, *self.status_screen())
        if d == "check":
            await self._edit(msg, "🔍 جاري الفحص الحقيقي… (يرسل رسالة صامتة للقناة ويحذفها)", [_back()])
            res = await e.self_test()
            lines = ["🔍 نتيجة الفحص\n━━━━━━━━━━━━━━"]
            for name, ok, info in res:
                lines.append(f"{'✅' if ok else '❌'} {name}: {info}")
            lines.append(f"{'✅' if STYLE_OK else '❌'} الأزرار الملونة (ButtonStyle)")
            lines.append(f"{'✅' if self.tier == 0 and ICON_PARAM else '❌'} أيقونات متحركة على الأزرار")
            return await self._edit(msg, "\n".join(lines), [[B("إعادة الفحص", "check", SUCCESS, "search")], _back()])
        if d == "toggle":
            s.set("enabled", not s.get("enabled"))
            return await self._edit(msg, *self.home())
        if d == "force":
            e.force_next()
            return await self._edit(msg, "⚡️ تم! راح ينشر أحدث خبر بالطابور خلال ثواني (إذا الطابور فيه شي).", [_back()])
        if d == "restart":
            ok, info = await e.start_reader(store.load_session())
            return await self._edit(msg, f"{'✅' if ok else '❌'} {info}", [_back()])

        if d == "src":
            return await self._edit(msg, *self.sources_screen())
        if d == "src_add":
            self.pending = {"kind": "src_add"}
            return await self._edit(msg, "➕ أرسل يوزر القناة أو رابطها (تقدر ترسل أكثر من وحدة، كل وحدة بسطر).",
                                    [[B("إلغاء", "src", DANGER, "block")]])
        if d == "src_del":
            self.pending = {"kind": "src_del"}
            return await self._edit(msg, "🗑 أرسل رقم المصدر (من القائمة) أو يوزره. يمكن عدة أرقام مفصولة بمسافة.",
                                    [[B("إلغاء", "src", DANGER, "block")]])
        if d == "src_join":
            if not e.connected:
                return await self._edit(msg, "❌ القارئ غير متصل. استخرج سيشن أولاً.", [_back("src")])
            asyncio.create_task(self._join_bg())
            return await self._edit(msg, "📥 بدأ الانضمام ببطء (3-7 ثواني بين كل قناة لتجنب القيود). راح أرسل لك النتيجة.", [_back("src")])

        if d == "set":
            return await self._edit(msg, *self.settings_screen())
        if d == "set_tr":
            s.set("translate", not s.get("translate"))
            return await self._edit(msg, *self.settings_screen())
        if d == "set_mode":
            to_user = s.get("post_mode") != "user"
            if to_user and not e.connected:
                return await self._edit(msg, "❌ النشر عبر حسابك يحتاج القارئ متصل. استخرج سيشن أولاً.", [_back("set")])
            s.set("post_mode", "user" if to_user else "bot")
            return await self._edit(msg, *self.settings_screen())
        prompts = {
            "set_int": ("⏱ اكتب الحد الأدنى والأعلى بين المنشورات بالدقائق، مثال:  30 90", "set_int"),
            "set_lim": ("🏆 اكتب الحد اليومي لعدد المنشورات (1-500)، مثال:  20", "set_lim"),
            "set_ttl": ("🗑 اكتب عمر الخبر بالطابور بالساعات (1-48). الخبر الأقدم منه يُحذف تلقائياً. مثال:  2", "set_ttl"),
            "set_hours": ("🗓 اكتب ساعة البداية والنهاية بتوقيت العراق (0-24)، مثال:  7 24", "set_hours"),
        }
        if d in prompts:
            self.pending = {"kind": d}
            return await self._edit(msg, prompts[d][0], [[B("إلغاء", "set", DANGER, "block")]])

        if d == "smart":
            return await self._edit(msg, *self.smart_screen())
        if d.startswith("tg:"):
            key = d.split(":", 1)[1]
            if key in {k for k, _, _ in self.SMART}:
                s.set(key, not s.get(key))
            return await self._edit(msg, *self.smart_screen())
        if d == "flt":
            return await self._edit(msg, *self.filters_screen())
        if d in ("flt_bl", "flt_wl", "flt_weak"):
            self.pending = {"kind": d}
            what = {"flt_bl": "الكلمات الممنوعة", "flt_wl": "الكلمات المطلوبة",
                    "flt_weak": "يوزرات القنوات غير الموثّقة (اللي موجودة تنحذف من القائمة)"}[d]
            return await self._edit(msg, f"✍️ أرسل {what}، واحدة بكل سطر أو مفصولة بفاصلة.",
                                    [[B("إلغاء", "flt", DANGER, "block")]])
        if d in ("flt_bl_clear", "flt_wl_clear"):
            s.set("blacklist" if d == "flt_bl_clear" else "whitelist", [])
            return await self._edit(msg, *self.filters_screen())

        if d == "ai":
            return await self._edit(msg, *self.ai_screen())
        if d.startswith("ai_key:"):
            name = d.split(":", 1)[1]
            p = llm.get(name)
            if not p:
                return
            self.pending = {"kind": "ai_key", "name": name}
            hint = "\nأو اكتب: حذف  — لحذف المفتاح الحالي." if p.key() else ""
            return await self._edit(msg, f"🔐 أرسل مفتاح {p.label} (API key).{hint}", [[B("إلغاء", "ai", DANGER, "block")]])
        if d == "ai_test":
            await self._edit(msg, "🔍 جاري اختبار كل مزوّد فعلياً بترجمة حقيقية…", [_back("ai")])
            sample = "Breaking: officials said 35 people were rescued in Geneva on Monday after talks resumed."
            lines = ["🔍 نتيجة الاختبار الحقيقي\n━━━━━━━━━━━━━━"]
            any_ok = False
            for p in llm.configured():
                res = await llm.complete(
                    tp._SYSTEM_PROMPT, f"<news>\n{sample}\n</news>",
                    validate=lambda o: tp.validate_translation(sample, o), max_tokens=512, only=p.name)
                if res:
                    any_ok = True
                    lines.append(f"✅ {p.label} ({p.last_ms}ms): {res[0][:120]}")
                else:
                    lines.append(f"❌ {p.label}: {p.last_error or 'فشل'}")
            if not llm.configured():
                lines.append("⚪ ما في مفاتيح مضافة؛ يشتغل Google Translate فقط. أضف مفتاح Gemini أو Groq مثلاً.")
            elif not any_ok:
                lines.append("⚠️ كل المزوّدين فشلوا؛ راح يكمل Google Translate.")
            return await self._edit(msg, "\n".join(lines), [[B("إعادة الاختبار", "ai_test", SUCCESS, "search")], _back("ai")])

        if d == "ses":
            await self._cancel_all()
            return await self._edit(msg, *self.session_screen())
        if d == "ses_phone":
            await self.login.cancel()
            self.pending = {"kind": "login_phone"}
            return await self._edit(
                msg, "📱 أرسل رقم هاتف حسابك مع رمز الدولة، مثال:  +9647701234567",
                [[B("إلغاء", "ses_cancel", DANGER, "block")]])
        if d == "ses_qr":
            self.pending = None
            await self._edit(msg, "📷 جاري إنشاء QR…", [[B("إلغاء", "ses_cancel", DANGER, "block")]])
            await self.login.start_qr(self._qr_show, self._qr_password, self._login_done, self._login_fail)
            return
        if d == "ses_cancel":
            await self._cancel_all()
            return await self._edit(msg, *self.session_screen())
        if d == "ses_apply":
            session = store.load_session()
            if not session:
                return await self._edit(msg, "❌ لا يوجد سيشن محفوظ.", [_back("ses")])
            ok, info = await e.start_reader(session)
            return await self._edit(msg, f"{'✅' if ok else '❌'} {info}", [_back("ses")])
        if d == "ses_show":
            session = store.load_session()
            if not session:
                return await self._edit(msg, "❌ لا يوجد سيشن محفوظ.", [_back("ses")])
            m = await self.app.send_message(
                config.OWNER_ID,
                "⚠️ <b>سيشن حسابك — لا تشاركه مع أحد.</b> ينحذف تلقائياً بعد دقيقتين.\n"
                f"<code>{html.escape(session)}</code>", parse_mode=ParseMode.HTML)
            asyncio.create_task(self._autodel(m, 120))
            return
        if d == "ses_del":
            return await self._edit(
                msg, "⚠️ تأكيد: يوقف القارئ ويحذف السيشن المحفوظ. تكمل؟",
                [[B("نعم، احذف", "ses_del_yes", DANGER, "trash"), B("تراجع", "ses", SUCCESS, "shield")]])
        if d == "ses_del_yes":
            await e.stop_reader()
            store.delete_session()
            note = "\n(ملاحظة: متغير SESSION_STRING بـ Railway ما زال موجود وراح يُستخدم عند إعادة التشغيل — احذفه إذا تريد.)" \
                if config.SESSION_STRING_ENV else ""
            return await self._edit(msg, "✅ انحذف السيشن وتوقف القارئ." + note, [_back("ses")])

    async def _join_bg(self):
        res = await self.engine.join_sources()
        if res is None:
            return
        ok, fail = res
        text = f"📥 انتهى الانضمام\n✅ نجح: {len(ok)}"
        if fail:
            text += f"\n❌ فشل ({len(fail)}):\n" + "\n".join(fail[:25])
        await self._send(text, [_back("src")])

    async def on_text(self, client, message):
        p = self.pending
        if not p:
            return
        kind, text = p["kind"], (message.text or "").strip()
        try:
            if kind.startswith("login_"):
                await self._delete(message)
                return await self._login_input(kind, text)
            if kind == "ai_key":
                await self._delete(message)
                name = p["name"]
                self.pending = None
                if text.strip() in ("حذف", "delete"):
                    store.keys.delete(name)
                    note = "🗑 انحذف المفتاح."
                elif len(text.strip()) < 12 or " " in text.strip():
                    return await self._send("❌ هذا ما يشبه مفتاح API. جرّب مرة ثانية.", [[B("إلغاء", "ai", DANGER, "block")]])
                else:
                    store.keys.set(name, text.strip())
                    llm.get(name).bad_key = False
                    llm.get(name).cooldown_until = 0
                    note = "✅ انحفظ المفتاح. اضغط «فحص حقيقي» للتأكد."
                t, r = self.ai_screen()
                return await self._send(note + "\n\n" + t, r)
            if kind in ("flt_bl", "flt_wl", "flt_weak"):
                return await self._in_filter(kind, text)
            if kind == "src_add":
                return await self._in_src_add(text)
            if kind == "src_del":
                return await self._in_src_del(text)
            if kind in ("set_int", "set_lim", "set_hours", "set_ttl"):
                return await self._in_setting(kind, text)
        except Exception as e:
            logger.exception("input failed")
            self.pending = None
            await self._send(f"☄️ خطأ: {type(e).__name__}: {str(e)[:300]}", [_back()])

    async def _in_filter(self, kind, text):
        items = [w.strip() for w in re.split(r"[\n,،]+", text) if w.strip()]
        self.pending = None
        if kind == "flt_weak":
            cur = self.s.get("weak_sources")
            low = [x.lower() for x in cur]
            for it in items:
                n = self.engine.norm_source(it)
                if not n:
                    continue
                if n.lower() in low:
                    cur = [x for x in cur if x.lower() != n.lower()]
                else:
                    cur.append(n.lower())
                low = [x.lower() for x in cur]
            self.s.set("weak_sources", cur)
        else:
            key = "blacklist" if kind == "flt_bl" else "whitelist"
            cur = self.s.get(key)
            for it in items:
                if it.lower() not in [c.lower() for c in cur]:
                    cur.append(it)
            self.s.set(key, cur)
        t, r = self.filters_screen()
        await self._send("✅ تم.\n\n" + t, r)

    async def _in_src_add(self, text):
        cur = self.s.get("sources")
        low = {x.lower() for x in cur}
        added, bad = [], []
        for tok in text.replace(",", "\n").split():
            n = self.engine.norm_source(tok)
            if not n:
                bad.append(tok)
            elif n.lower() not in low:
                cur.append(n)
                low.add(n.lower())
                added.append(n)
        self.s.set("sources", cur)
        self.pending = None
        msg = f"✅ أضفت {len(added)} مصدر" + (": " + " ".join("@" + a for a in added) if added else "")
        if bad:
            msg += "\n❌ غير صالح: " + " ".join(bad)
        if added and self.engine.connected:
            msg += "\n📥 جاري انضمام الحساب لها…"
            asyncio.create_task(self._join_bg_only(added))
        await self._send(msg, [_back("src")])

    async def _join_bg_only(self, only):
        res = await self.engine.join_sources(only=only)
        if res:
            ok, fail = res
            await self._send(f"📥 الانضمام: ✅ {len(ok)}" + (f"\n❌ {', '.join(fail)}" if fail else ""), [_back("src")])

    async def _in_src_del(self, text):
        cur = self.s.get("sources")
        remove = set()
        for tok in text.replace(",", " ").split():
            if tok.isdigit() and 1 <= int(tok) <= len(cur):
                remove.add(cur[int(tok) - 1].lower())
            else:
                n = self.engine.norm_source(tok)
                if n:
                    remove.add(n.lower())
        new = [x for x in cur if x.lower() not in remove]
        self.s.set("sources", new)
        self.pending = None
        await self._send(f"🗑 انحذف {len(cur) - len(new)} مصدر. المتبقي {len(new)}.", [_back("src")])

    async def _in_setting(self, kind, text):
        nums = [int(x) for x in text.replace(",", " ").split() if x.isdigit()]
        err = None
        if kind == "set_int":
            if len(nums) == 2 and 1 <= nums[0] <= nums[1] <= 1440:
                self.s.set("min_interval", nums[0] * 60)
                self.s.set("max_interval", nums[1] * 60)
            else:
                err = "اكتب رقمين بالدقائق (الأدنى ثم الأعلى) مثل:  30 90"
        elif kind == "set_ttl":
            if len(nums) == 1 and 1 <= nums[0] <= 48:
                self.s.set("ttl_hours", nums[0])
            else:
                err = "اكتب رقم ساعات بين 1 و48."
        elif kind == "set_lim":
            if len(nums) == 1 and 1 <= nums[0] <= 500:
                self.s.set("daily_limit", nums[0])
            else:
                err = "اكتب رقم بين 1 و500."
        else:
            if len(nums) == 2 and 0 <= nums[0] < nums[1] <= 24:
                self.s.set("active_start", nums[0])
                self.s.set("active_end", nums[1])
            else:
                err = "اكتب ساعتين مثل:  7 24"
        if err:
            return await self._send("❌ " + err, [[B("إلغاء", "set", DANGER, "block")]])
        self.pending = None
        await self._send("✅ تم الحفظ.", self.settings_screen()[1])

    async def _login_input(self, kind, text):
        cancel = [[B("إلغاء", "ses_cancel", DANGER, "block")]]
        if kind == "login_phone":
            res = await self.login.start_phone(text)
            if res.status == "code":
                self.pending = {"kind": "login_code"}
                return await self._send(
                    "📩 انرسل كود لتطبيق تيليجرام على حسابك.\n"
                    "اكتبه هنا مفصولاً بشرطات مثل:  1-2-3-4-5\n"
                    "(إذا كتبته متصل ممكن تيليجرام يبطله لأنه يعتبره مشارك)", cancel)
            self.pending = None
            return await self._send(f"❌ {res.error}", [[B("حاول مجدداً", "ses", PRIMARY, "lock")]])
        if kind == "login_code":
            res = await self.login.submit_code(text)
        else:
            res = await self.login.submit_password(text)
        if res.status == "done":
            return await self._login_done(res.session, res.me)
        if res.status == "password":
            self.pending = {"kind": "login_password"}
            return await self._send("🔐 حسابك عليه تحقق بخطوتين. أرسل كلمة المرور (راح أحذف رسالتك فوراً).", cancel)
        if res.status == "retry":
            return await self._send(f"⚠️ {res.error}", cancel)
        self.pending = None
        await self._send(f"❌ {res.error}", [[B("حاول مجدداً", "ses", PRIMARY, "lock")]])

    async def _qr_show(self, url):
        await self._delete(self._qr_msg)
        path = await asyncio.to_thread(make_qr_png, url)
        self._qr_msg = await self._send_photo(
            path,
            "📷 امسح هذا الـ QR من تيليجرام (جهاز ثاني): الإعدادات > الأجهزة > ربط جهاز.\n"
            "يتجدد تلقائياً كل ~30 ثانية، والمهلة 3 دقائق.",
            [[B("إلغاء", "ses_cancel", DANGER, "block")]])

    async def _qr_password(self):
        await self._delete(self._qr_msg)
        self._qr_msg = None
        self.pending = {"kind": "login_password"}
        await self._send("🔐 تم مسح الـ QR. حسابك عليه تحقق بخطوتين، أرسل كلمة المرور (راح أحذف رسالتك فوراً).",
                         [[B("إلغاء", "ses_cancel", DANGER, "block")]])

    async def _login_fail(self, error):
        await self._delete(self._qr_msg)
        self._qr_msg = None
        self.pending = None
        await self._send(f"❌ {error}", [[B("حاول مجدداً", "ses", PRIMARY, "lock")]])

    async def _login_done(self, session, me):
        await self._delete(self._qr_msg)
        self._qr_msg = None
        self.pending = None
        store.save_session(session)
        name = (getattr(me, "first_name", "") or "") + (f" @{me.username}" if getattr(me, "username", None) else "")
        m = await self.app.send_message(
            config.OWNER_ID,
            f"✅ <b>تم استخراج السيشن لحساب:</b> {html.escape(name.strip())}\n"
            "انحفظ بملفات البوت. انسخه احتياطاً (ينحذف من هنا بعد 3 دقائق):\n"
            f"<code>{html.escape(session)}</code>", parse_mode=ParseMode.HTML)
        asyncio.create_task(self._autodel(m, 180))
        await self._send(
            "هل تفعّل هذا السيشن الآن كقارئ للأخبار؟",
            [[B("تفعيل الآن", "ses_apply", SUCCESS, "bolt"), B("لاحقاً", "home", PRIMARY)]])

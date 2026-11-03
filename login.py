# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import asyncio
import logging
import os
import re
import time
from collections import namedtuple

from telethon import TelegramClient, errors as E
from telethon.sessions import StringSession

import config

logger = logging.getLogger("login")

Result = namedtuple("Result", "status session me error")
QR_TOTAL_SECONDS = 180
FLOW_TTL = 600


class _Flow:
    def __init__(self, client, mode):
        self.client = client
        self.mode = mode
        self.stage = "init"
        self.phone = None
        self.code_hash = None
        self.task = None
        self.started = time.monotonic()


def make_qr_png(url: str, name: str = "login_qr.png") -> str:
    import qrcode
    path = os.path.join(config.TMP_DIR, name)
    img = qrcode.make(url)
    img.save(path)
    return path


def _client():
    return TelegramClient(
        StringSession(), config.API_ID, config.API_HASH,
        device_model="NewsBot Control Panel", system_version="Linux", app_version="2.0",
        connection_retries=3,
    )


class LoginManager:
    def __init__(self):
        self.flow = None

    @property
    def active(self) -> bool:
        return self.flow is not None and (time.monotonic() - self.flow.started) < FLOW_TTL

    @property
    def stage(self):
        return self.flow.stage if self.flow else None

    async def cancel(self):
        f, self.flow = self.flow, None
        if not f:
            return
        if f.task and not f.task.done() and f.task is not asyncio.current_task():
            f.task.cancel()
        try:
            await f.client.disconnect()
        except Exception:
            pass

    async def _finish(self, client) -> Result:
        me = await client.get_me()
        session = client.session.save()
        try:
            await client.disconnect()
        except Exception:
            pass
        self.flow = None
        return Result("done", session, me, None)

    async def start_phone(self, phone_text: str) -> Result:
        await self.cancel()
        phone = "+" + re.sub(r"\D", "", phone_text)
        if not 9 <= len(phone) <= 16:
            return Result("error", None, None, "الرقم غير صحيح. اكتبه مع رمز الدولة مثل +9647xxxxxxxxx")
        client = _client()
        flow = _Flow(client, "phone")
        self.flow = flow
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
            flow.phone, flow.code_hash, flow.stage = phone, sent.phone_code_hash, "code"
            return Result("code", None, None, None)
        except E.PhoneNumberInvalidError:
            err = "رقم الهاتف غير صحيح."
        except E.PhoneNumberBannedError:
            err = "هذا الرقم محظور من تيليجرام."
        except E.FloodWaitError as e:
            err = f"تيليجرام طلب الانتظار {e.seconds} ثانية قبل طلب كود جديد."
        except E.ApiIdInvalidError:
            err = "API_ID / API_HASH غير صحيحين."
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        await self.cancel()
        return Result("error", None, None, err)

    async def submit_code(self, text: str) -> Result:
        f = self.flow
        if not f or f.stage != "code":
            return Result("error", None, None, "لا توجد عملية تسجيل نشطة.")
        code = re.sub(r"\D", "", text)
        if not 5 <= len(code) <= 6:
            return Result("retry", None, None, "الكود لازم 5 أرقام. اكتبه مفصولاً مثل 1-2-3-4-5")
        try:
            await f.client.sign_in(phone=f.phone, code=code, phone_code_hash=f.code_hash)
            return await self._finish(f.client)
        except E.SessionPasswordNeededError:
            f.stage = "password"
            return Result("password", None, None, None)
        except E.PhoneCodeInvalidError:
            return Result("retry", None, None, "الكود غلط، جرّب مرة ثانية.")
        except (E.PhoneCodeExpiredError, E.PhoneCodeEmptyError):
            err = "انتهت صلاحية الكود (أو أبطله تيليجرام). ابدأ من جديد واكتب الكود مفصولاً بشرطات."
        except E.FloodWaitError as e:
            err = f"انتظر {e.seconds} ثانية."
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        await self.cancel()
        return Result("error", None, None, err)

    async def submit_password(self, password: str) -> Result:
        f = self.flow
        if not f or f.stage != "password":
            return Result("error", None, None, "لا توجد عملية تسجيل نشطة.")
        try:
            await f.client.sign_in(password=password)
            return await self._finish(f.client)
        except E.PasswordHashInvalidError:
            return Result("retry", None, None, "كلمة مرور التحقق بخطوتين غلط.")
        except E.FloodWaitError as e:
            err = f"انتظر {e.seconds} ثانية."
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        await self.cancel()
        return Result("error", None, None, err)

    async def start_qr(self, on_qr, on_password, on_done, on_fail):
        await self.cancel()
        client = _client()
        flow = _Flow(client, "qr")
        flow.stage = "qr"
        self.flow = flow
        try:
            await client.connect()
        except Exception as e:
            await self.cancel()
            await on_fail(f"{type(e).__name__}: {e}")
            return
        flow.task = asyncio.create_task(self._qr_loop(flow, on_qr, on_password, on_done, on_fail))

    async def _qr_loop(self, flow, on_qr, on_password, on_done, on_fail):
        client = flow.client
        try:
            qr = await client.qr_login()
            deadline = time.monotonic() + QR_TOTAL_SECONDS
            await on_qr(qr.url)
            while time.monotonic() < deadline:
                try:
                    await qr.wait(timeout=25)
                    res = await self._finish(client)
                    await on_done(res.session, res.me)
                    return
                except asyncio.TimeoutError:
                    await qr.recreate()
                    await on_qr(qr.url)
                except E.SessionPasswordNeededError:
                    flow.stage = "password"
                    await on_password()
                    return
            await self.cancel()
            await on_fail("انتهت مهلة الـ QR (3 دقائق). ابدأ من جديد.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("qr login failed")
            await self.cancel()
            await on_fail(f"{type(e).__name__}: {e}")

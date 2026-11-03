# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import base64
import logging
import os
import re
import time

import config
import store

logger = logging.getLogger("llm")


def _list_env(name, default):
    v = os.environ.get(name, "").strip()
    return [m.strip() for m in v.split(",") if m.strip()] or list(default)


class ProviderError(Exception):
    def __init__(self, status, body="", retry_after=None):
        super().__init__(f"{status}: {body[:200]}")
        self.status, self.body, self.retry_after = status, body, retry_after


class Provider:
    def __init__(self, name, label, base, env_key, models, hints=(), kind="openai", free=True, vision=False):
        self.name, self.label, self.base, self.env_key = name, label, base, env_key
        self.models = models
        self.hints = hints
        self.kind = kind
        self.free = free
        self.vision = vision
        self.cooldown_until = 0.0
        self.strikes = 0
        self.dead = {}
        self.discovered = []
        self.ok = self.err = self.invalid = 0
        self.last_error = ""
        self.last_ms = 0
        self.bad_key = False
        self._discover_at = 0.0

    def key(self) -> str:
        return (store.keys.get(self.name) or os.environ.get(self.env_key, "")).strip()

    def base_url(self) -> str:
        return self.base

    def candidates(self):
        now = time.time()
        out = [m for m in self.models if self.dead.get(m, 0) <= now]
        out += [m for m in self.discovered if m not in out and self.dead.get(m, 0) <= now]
        return out

    def state(self) -> str:
        if not self.key():
            return "بدون مفتاح"
        if self.bad_key:
            return "مفتاح مرفوض"
        left = int(self.cooldown_until - time.time())
        if left > 0:
            return f"استراحة {left}ث"
        return "جاهز"


class CustomProvider(Provider):
    def base_url(self):
        return os.environ.get("CUSTOM_LLM_BASE", "").rstrip("/")


def _build():
    ps = [
        Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
                 "GEMINI_API_KEY", _list_env("GEMINI_MODELS", ["gemini-2.5-flash", "gemini-2.5-flash-lite"]),
                 hints=("flash", "gemma"), vision=True),
        Provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
                 _list_env("GROQ_MODELS", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]),
                 hints=("gpt-oss", "qwen")),
        Provider("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
                 _list_env("NVIDIA_MODELS", ["nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b"]),
                 hints=("gpt-oss", "nemotron")),
        Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                 _list_env("OPENROUTER_MODELS", ["google/gemma-4-31b-it:free", "nvidia/nemotron-3-super-120b-a12b:free",
                                                 "openrouter/free"]),
                 hints=(":free",)),
        Provider("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
                 _list_env("MISTRAL_MODELS", ["mistral-small-latest"]), hints=("small", "medium")),
        CustomProvider("custom", "مزوّد مخصص", "", "CUSTOM_LLM_KEY",
                       _list_env("CUSTOM_LLM_MODEL", []), hints=()),
        Provider("anthropic", "Claude (مدفوع)", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
                 _list_env("ANTHROPIC_MODELS", [config.LLM_MODEL or "claude-haiku-5-5"]), kind="anthropic", free=False, vision=True),
        Provider("openai", "OpenAI (مدفوع)", config.OPENAI_BASE_URL, "OPENAI_API_KEY",
                 _list_env("OPENAI_MODELS", [config.LLM_MODEL or "gpt-4o-mini"]), free=False, vision=True),
    ]
    order = _list_env("LLM_ORDER", [p.name for p in ps])
    by = {p.name: p for p in ps}
    out = [by[n] for n in order if n in by]
    out += [p for p in ps if p not in out]
    return out


PROVIDERS = _build()
KEY_PROVIDERS = [p for p in PROVIDERS if p.name != "custom"]
last_used = {"label": "-"}


def configured():
    return [p for p in PROVIDERS if p.key() and not (p.name == "custom" and not p.base_url())]


def any_configured() -> bool:
    return bool(configured())


def get(name):
    return next((p for p in PROVIDERS if p.name == name), None)


def _clean_output(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?news>", "", text, flags=re.IGNORECASE)
    text = text.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", text, flags=re.DOTALL)
    if m:
        text = m.group(1).strip()
    return text


async def _call(p: Provider, model, system, user, max_tokens, temperature, image=None):
    import httpx
    b64 = base64.b64encode(image[0]).decode() if image else None
    timeout = httpx.Timeout(60.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            if p.kind == "anthropic":
                r = await c.post(
                    f"{p.base}/messages",
                    headers={"x-api-key": p.key(), "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                          "messages": [{"role": "user", "content": (
                              [{"type": "image", "source": {"type": "base64", "media_type": image[1], "data": b64}},
                               {"type": "text", "text": user}] if image else user)}]})
            else:
                headers = {"Authorization": f"Bearer {p.key()}", "content-type": "application/json"}
                if p.name == "openrouter":
                    headers["X-Title"] = "NewsBot"
                r = await c.post(
                    f"{p.base_url()}/chat/completions", headers=headers,
                    json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": (
                              [{"type": "text", "text": user},
                               {"type": "image_url", "image_url": {"url": f"data:{image[1]};base64,{b64}"}}]
                              if image else user)}]})
    except httpx.HTTPError as e:
        raise ProviderError(0, f"{type(e).__name__}: {e}")
    if r.status_code != 200:
        raise ProviderError(r.status_code, r.text, r.headers.get("retry-after"))
    try:
        data = r.json()
        if p.kind == "anthropic":
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        content = data["choices"][0]["message"].get("content")
        if isinstance(content, list):
            content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
        return content or ""
    except Exception as e:
        raise ProviderError(200, f"bad response shape: {e}")


async def _discover(p: Provider):
    if time.time() - p._discover_at < 3600 or p.kind != "openai":
        return
    p._discover_at = time.time()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{p.base_url()}/models", headers={"Authorization": f"Bearer {p.key()}"})
        if r.status_code != 200:
            return
        ids = [(m.get("id") or "").replace("models/", "") for m in r.json().get("data", [])]
        bad = ("embed", "tts", "whisper", "vision", "image", "guard", "moderation", "audio", "live", "preview-tts")
        good = [i for i in ids if i and any(h in i for h in p.hints) and not any(b in i.lower() for b in bad)]
        p.discovered = good[:3]
        if p.discovered:
            logger.info("[LLM] %s discovered models: %s", p.name, p.discovered)
    except Exception as e:
        logger.debug("discover failed %s: %s", p.name, e)


def _penalize(p: Provider, model, e: ProviderError):
    p.err += 1
    p.last_error = f"{model}: {e}"[:200]
    s, body = e.status, (e.body or "").lower()
    if s == 429 or "rate" in body and "limit" in body or "quota" in body:
        p.strikes += 1
        try:
            wait = float(e.retry_after)
        except (TypeError, ValueError):
            wait = 60.0 * (2 ** min(p.strikes - 1, 5))
        p.cooldown_until = time.time() + min(max(wait, 20.0), 1800.0)
        return "provider"
    if s in (401, 403):
        p.bad_key = True
        p.cooldown_until = time.time() + 3600
        return "provider"
    if s == 402:
        p.cooldown_until = time.time() + 3600
        return "provider"
    if s in (400, 404, 410) and ("model" in body or s in (404, 410)):
        p.dead[model] = time.time() + 3600
        return "model"
    if s == 0 or s >= 500:
        p.cooldown_until = time.time() + 90
        return "provider"
    return "model"


async def complete(system, user, *, validate=None, max_tokens=4096, temperature=0.2, only=None, image=None):
    for p in PROVIDERS:
        if only and p.name != only:
            continue
        if image and not p.vision:
            continue
        if not p.key() or (p.name == "custom" and not p.base_url()):
            continue
        if not only and (time.time() < p.cooldown_until):
            continue
        tried = 0
        for _round in range(2):
            for model in p.candidates():
                tried += 1
                t0 = time.monotonic()
                try:
                    raw = await _call(p, model, system, user, max_tokens, temperature, image)
                except ProviderError as e:
                    logger.warning("[LLM] %s/%s failed: %s", p.name, model, e)
                    if _penalize(p, model, e) == "provider":
                        break
                    continue
                text = _clean_output(raw)
                if not text or (validate and not validate(text)):
                    p.invalid += 1
                    p.last_error = f"{model}: إجابة ما اجتازت التحقق"
                    logger.warning("[LLM] %s/%s answer rejected by validator", p.name, model)
                    continue
                p.ok += 1
                p.strikes = 0
                p.bad_key = False
                p.last_ms = int((time.monotonic() - t0) * 1000)
                last_used["label"] = f"{p.label}/{model}"
                return text, f"{p.label}/{model}"
            else:
                if _round == 0 and time.time() >= p.cooldown_until and any(v > time.time() for v in p.dead.values()):
                    before = set(p.candidates())
                    await _discover(p)
                    if set(p.candidates()) - before:
                        continue
            break
    return None


def status_rows():
    rows = []
    for p in PROVIDERS:
        if p.name == "custom" and not p.base_url():
            continue
        rows.append({
            "name": p.name, "label": p.label, "free": p.free, "configured": bool(p.key()),
            "state": p.state(), "ok": p.ok, "err": p.err, "invalid": p.invalid,
            "last_error": p.last_error, "ms": p.last_ms,
            "models": ", ".join(p.candidates()[:3]) or "-",
        })
    return rows

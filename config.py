# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import os
import sys
from zoneinfo import ZoneInfo


def _need(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.stderr.write(f"[CONFIG] المتغير المطلوب غير موجود: {name}  (ضيفه في Railway > Variables)\n")
        raise SystemExit(1)
    return v


API_ID = int(_need("API_ID"))
API_HASH = _need("API_HASH")
BOT_TOKEN = _need("BOT_TOKEN")
OWNER_ID = int(_need("OWNER_ID"))

_target = _need("TARGET_CHANNEL")
TARGET_CHANNEL = int(_target) if _target.lstrip("-").isdigit() else _target

DATA_DIR = os.environ.get("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
PERSISTENT = bool(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")) or os.path.ismount(os.path.abspath(DATA_DIR))
ON_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"))
TMP_DIR = os.path.join(DATA_DIR, "tmp")
os.makedirs(TMP_DIR, exist_ok=True)

SESSION_STRING_ENV = os.environ.get("SESSION_STRING", "").strip()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()

MAX_MEDIA_MB = int(os.environ.get("MAX_MEDIA_MB", "100"))

IRAQ_TZ = ZoneInfo("Asia/Baghdad")

DEFAULT_SOURCES = []

_sig = os.environ.get("POST_SIGNATURE", "").replace("\\n", "\n").strip()
SIGNATURE = "\n\n" + _sig + "\n" if _sig else ""

HASHTAGS = """

#BreakingNews #News #War #WorldNews
#Ukraine #Russia #Israel #Gaza
#MiddleEast #Iran
"""

DEFAULT_SETTINGS = {
    "enabled": True,
    "translate": True,
    "post_mode": "bot",
    "sources": DEFAULT_SOURCES,
    "min_interval": 1800,
    "max_interval": 5400,
    "daily_limit": 20,
    "active_start": 7,
    "active_end": 24,
    "ttl_hours": 2,
    "queue_max": 40,
    "min_text_len": 40,
    "dedupe_hours": 48,
    "breaking_bypass": True,
    "urgent_gap": 180,
    "label_unverified": True,
    "attribution": False,
    "smart_hashtags": True,
    "transcribe": False,
    "ocr": False,
    "daily_report": True,
    "blacklist": [],
    "whitelist": [],
    "weak_sources": [],
}

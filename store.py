# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import copy
import json
import logging
import os
import threading

import config

logger = logging.getLogger("store")

SETTINGS_FILE = os.path.join(config.DATA_DIR, "settings.json")
SESSION_FILE = os.path.join(config.DATA_DIR, "session.txt")
HASHES_FILE = os.path.join(config.DATA_DIR, "posted_hashes.txt")
KEYS_FILE = os.path.join(config.DATA_DIR, "keys.json")


class Settings:
    def __init__(self, path: str = SETTINGS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.data = copy.deepcopy(config.DEFAULT_SETTINGS)
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                self.data.update({k: v for k, v in saved.items() if k in self.data})
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error("settings load failed: %s", e)

    def get(self, key):
        v = self.data[key]
        return list(v) if isinstance(v, list) else v

    def set(self, key, value):
        if key not in self.data:
            raise KeyError(key)
        with self._lock:
            self.data[key] = value
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)


def load_session() -> str:
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            s = f.read().strip()
            if s:
                return s
    except FileNotFoundError:
        pass
    return config.SESSION_STRING_ENV


def save_session(session: str):
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(session.strip())
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, SESSION_FILE)


def delete_session():
    try:
        os.remove(SESSION_FILE)
    except FileNotFoundError:
        pass


class HashStore:
    COMPACT_EVERY = 50
    MAX_ITEMS = 40000

    def __init__(self, path: str = HASHES_FILE):
        self.path = path
        self.items = {}
        self._since = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for l in f:
                    l = l.strip()
                    if l:
                        self.items[l] = None
        except FileNotFoundError:
            pass
        self._trim()
        logger.info("loaded %d hashes", len(self.items))

    def _trim(self):
        extra = len(self.items) - self.MAX_ITEMS
        if extra > 0:
            for k in list(self.items)[:extra]:
                del self.items[k]

    def has(self, h: str) -> bool:
        return h in self.items

    def add(self, h: str):
        if h in self.items:
            return
        self.items[h] = None
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(h + "\n")
            self._since += 1
            if self._since >= self.COMPACT_EVERY:
                self._trim()
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.items) + "\n")
                os.replace(tmp, self.path)
                self._since = 0
        except OSError as e:
            logger.error("hash write failed: %s", e)


class Keys:

    def __init__(self, path: str = KEYS_FILE):
        self.path = path
        self.data = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data = {k: str(v) for k, v in d.items()}
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error("keys load failed: %s", e)

    def get(self, name: str) -> str:
        return self.data.get(name, "")

    def _write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def set(self, name: str, value: str):
        self.data[name] = value.strip()
        self._write()

    def delete(self, name: str):
        self.data.pop(name, None)
        self._write()


keys = Keys()

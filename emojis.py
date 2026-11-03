# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import re
from typing import List, Tuple

VS16 = "️"

EMOJI = {
    "search": ("🔍", 5318967033570828180),
    "eye": ("👁", 5318906848194114595),
    "hacker": ("👨‍💻", 5319125827101697903),
    "user": ("👤", 5319070666836717201),
    "calendar": ("🗓", 5319303965165267291),
    "laugh": ("🤣", 5319289435290904538),
    "alarm": ("⏰", 5319187086220238140),
    "music": ("🎶", 5289526231052624392),
    "warn": ("⚠️", 5318756275230648287),
    "medal": ("🎖️", 5318799272148247347),
    "robot": ("🤖", 5197706972794731241),
    "scream": ("😱", 5264733609645847811),
    "skull": ("☠️", 5253539825360843975),
    "trophy": ("🏆", 5318879961698835649),
    "heart": ("♥️", 5319151790179002796),
    "bolt": ("⚡️", 5318910786679120500),
    "thought": ("💭", 5319023125843715832),
    "mail": ("✉️", 5319213392894928187),
    "trash": ("🗑", 5318843424412049998),
    "block": ("🚫", 5318942285969270026),
    "plus": ("➕", 5319246288049449206),
    "shield": ("🛡", 5251203410396458957),
    "comet": ("☄️", 5224607267797606837),
    "iraq": ("🇮🇶", 5242360656849578999),
    "spider": ("🕷", 5287665118644052614),
    "lock": ("🔐", 5287470251682866680),
    "hacker2": ("🥷", 5263016700764267251),
}

MAX_CUSTOM_PER_MESSAGE = 90


def _base(s: str) -> str:
    return s.replace(VS16, "")


_MAP = {_base(u): i for u, i in EMOJI.values()}
_MAP["❤"] = EMOJI["heart"][1]

_RE = re.compile(
    "(?:" + "|".join(re.escape(k) for k in sorted(_MAP, key=len, reverse=True)) + ")" + VS16 + "?"
)


def u16len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def icon(name: str) -> str:
    return EMOJI[name][0]


def icon_id(name: str) -> int:
    return EMOJI[name][1]


def find_custom(text: str) -> List[Tuple[int, int, int]]:
    out: List[Tuple[int, int, int]] = []
    last_end = 0
    offset = 0
    for m in _RE.finditer(text):
        offset += u16len(text[last_end:m.start()])
        length = u16len(m.group())
        out.append((offset, length, _MAP[_base(m.group())]))
        offset += length
        last_end = m.end()
        if len(out) >= MAX_CUSTOM_PER_MESSAGE:
            break
    return out

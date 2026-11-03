# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).
import re

_BREAKING = re.compile(
    r"(عاجل|breaking|urgent|\bflash\b|срочно|молния|важно|فوری|خبر فوری|فوري|בהול|דחוף|🚨)", re.IGNORECASE)
_IMPACT = re.compile(
    r"(انفجار|غارة|غارات|هجوم|مقتل|استشهاد|صاروخ|صواريخ|مسيّرة|مسيرة|اغتيال|وقف إطلاق النار|إنذار|اشتباكات|قصف|اعتقال|"
    r"explosion|airstrike|strike|attack|killed|missile|drone|assassinat|ceasefire|siren|shelling|casualt|"
    r"взрыв|удар|ракет|беспилот|обстрел|погиб|"
    r"انفجار|حمله|موشک|پهپاد|ترور|آتش‌بس|شهید|"
    r"פיצוץ|תקיפה|טיל|רחפן|אזעקה|חיסול)", re.IGNORECASE)


def urgency(text: str, has_video: bool = False) -> int:
    t = text or ""
    score = 0
    if _BREAKING.search(t):
        score += 2
    hits = len(set(m.group(0).lower() for m in _IMPACT.finditer(t)))
    score += min(2, hits)
    if has_video:
        score += 1
    if len(t) > 900:
        score -= 1
    return max(0, min(5, score))


_UNVERIFIED = re.compile(
    r"(\b(?:reportedly|allegedly|unconfirmed|unverified|rumou?rs?|claims?|claimed|sources say|"
    r"according to (?:unnamed |anonymous )?sources)\b|"
    r"يزعم|زعم|مزاعم|غير مؤكد|لم يتم التأكد|وفق مصادر|بحسب مصادر|يُقال|أنباء عن|تقارير غير مؤكدة|"
    r"ادعا|گزارش‌ها حاکی|به گفته منابع|تایید نشده|تأیید نشده|شایعه|"
    r"якобы|неподтвержден|по данным источников|слухи|"
    r"לפי דיווחים|על פי דיווחים|לא מאומת)", re.IGNORECASE)


def looks_unverified(text: str) -> bool:
    return bool(_UNVERIFIED.search(text or ""))


def passes_filters(text: str, blacklist, whitelist) -> bool:
    t = (text or "").lower()
    if any(w and w.lower() in t for w in blacklist):
        return False
    if whitelist and not any(w and w.lower() in t for w in whitelist):
        return False
    return True


_TOPICS = [
    (r"إيران|ايران|iran|иран|ایران|طهران|tehran|الحرس الثوري|سپاه|irgc", "#إيران #Iran"),
    (r"إسرائيل|اسرائيل|israel|израил|اسرائیل|ישראל|idf|الجيش الإسرائيلي", "#إسرائيل #Israel"),
    (r"غزة|غزه|gaza|газ[аы]|غزّه|حماس|hamas|فلسطين|palestin", "#غزة #Gaza"),
    (r"لبنان|lebanon|ливан|حزب الله|hezbollah|حزب‌الله", "#لبنان #Lebanon"),
    (r"اليمن|yemen|йемен|الحوثي|houthi|أنصار الله|ansar", "#اليمن #Yemen"),
    (r"العراق|iraq|ирак|بغداد|baghdad|عراق", "#العراق #Iraq"),
    (r"سوريا|syria|сири|دمشق|damascus", "#سوريا #Syria"),
    (r"أوكرانيا|اوكرانيا|ukrain|украин|زيلينسكي|zelensk|کیف|kyiv|kiev", "#أوكرانيا #Ukraine"),
    (r"روسيا|russia|росси|бутин|putin|بوتين|москв|moscow|روسیه", "#روسيا #Russia"),
    (r"أمريكا|امريكا|الولايات المتحدة|usa\b|united states|pentagon|البنتاغون|белый дом|ترامب|trump|آمریکا", "#أمريكا #USA"),
    (r"النووي|nuclear|ядерн|هسته", "#النووي #Nuclear"),
    (r"النفط|oil prices|нефт|نفت|opec|أوبك", "#النفط #Oil"),
]


def smart_hashtags(text: str, urgent: bool = False, limit: int = 6) -> str:
    t = (text or "").lower()
    tags = ["#عاجل #BreakingNews"] if urgent else ["#أخبار #News"]
    for pat, tag in _TOPICS:
        if re.search(pat, t, re.IGNORECASE):
            tags.append(tag)
        if len(tags) >= limit:
            break
    if len(tags) == 1:
        tags.append("#WorldNews")
    return "\n\n" + " ".join(tags) + "\n"

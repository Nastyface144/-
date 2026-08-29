"""Подбор ниши по объявлению и подстановка данных в клише."""

from __future__ import annotations

import random
import re
from typing import Any, Sequence

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def split_keywords(raw: str) -> list[str]:
    return [kw.strip().lower() for kw in raw.replace(";", ",").split(",") if kw.strip()]


def match_niche(niches: Sequence[Any], item_title: str) -> Any | None:
    """Первая активная ниша, все ключевые слова которой встречаются в заголовке.

    Ниши без ключевых слов не матчатся по тексту — они работают только
    как ниша по умолчанию.
    """
    title = (item_title or "").lower()
    best = None
    best_score = 0
    for niche in niches:
        if not niche["is_active"]:
            continue
        keywords = split_keywords(niche["keywords"])
        if not keywords:
            continue
        if all(kw in title for kw in keywords):
            if len(keywords) > best_score:
                best, best_score = niche, len(keywords)
    return best


def pick_template(templates: Sequence[Any], seed: str | None = None) -> Any | None:
    """Выбирает клише из набора. Один и тот же чат всегда получает одно и то же."""
    active = [t for t in templates if t["is_active"]]
    if not active:
        return None
    if seed is None:
        return random.choice(active)
    return active[hash(seed) % len(active)]


def render(body: str, context: dict[str, str]) -> str:
    """Подставляет {item_title}, {interlocutor} и т.п. Неизвестное — пустая строка."""
    return PLACEHOLDER_RE.sub(lambda m: context.get(m.group(1), ""), body).strip()


def known_placeholders() -> list[str]:
    return ["item_title", "item_id", "interlocutor", "niche", "account"]

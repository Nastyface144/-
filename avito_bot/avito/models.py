"""Модели данных Авито, приведённые к внутреннему виду."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


def _ts(value: object) -> dt.datetime | None:
    """Авито отдаёт время unix-секундами; допускаем и ISO-строку."""
    if isinstance(value, (int, float)) and value > 0:
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None


@dataclass(slots=True)
class AvitoMessage:
    id: str
    chat_id: str
    author_id: str
    text: str
    created_at: dt.datetime | None
    direction: str  # in | out

    @classmethod
    def from_api(cls, raw: dict, chat_id: str, self_user_id: str) -> "AvitoMessage":
        author = str(raw.get("author_id", ""))
        content = raw.get("content") or {}
        text = ""
        if isinstance(content, dict):
            text = str(content.get("text") or "")
        return cls(
            id=str(raw.get("id", "")),
            chat_id=chat_id,
            author_id=author,
            text=text,
            created_at=_ts(raw.get("created")),
            direction="out" if author == str(self_user_id) else "in",
        )


@dataclass(slots=True)
class AvitoChat:
    id: str
    item_id: str | None
    item_title: str
    interlocutor: str
    last_message_text: str
    last_message_at: dt.datetime | None
    last_message_direction: str  # in | out | unknown

    @classmethod
    def from_api(cls, raw: dict, self_user_id: str) -> "AvitoChat":
        context = raw.get("context") or {}
        value = context.get("value") or {}
        users = raw.get("users") or []
        interlocutor = ""
        for user in users:
            if str(user.get("id", "")) != str(self_user_id):
                interlocutor = str(user.get("name") or user.get("id") or "")
                break
        last = raw.get("last_message") or {}
        content = last.get("content") or {}
        author = str(last.get("author_id", ""))
        if not author:
            direction = "unknown"
        else:
            direction = "out" if author == str(self_user_id) else "in"
        return cls(
            id=str(raw.get("id", "")),
            item_id=str(value.get("id")) if value.get("id") is not None else None,
            item_title=str(value.get("title") or ""),
            interlocutor=interlocutor,
            last_message_text=str(content.get("text") or "") if isinstance(content, dict) else "",
            last_message_at=_ts(last.get("created")),
            last_message_direction=direction,
        )

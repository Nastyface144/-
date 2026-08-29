"""Симулятор Авито для DRY_RUN: позволяет проверить всю цепочку без реального API.

Состояние живёт в памяти процесса и общее для всех гейтвеев одного аккаунта,
чтобы поллер и отправщик видели одни и те же чаты.
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass, field

from .models import AvitoChat, AvitoMessage

SELF_ID = "1000000"


@dataclass
class _FakeChat:
    id: str
    item_id: str
    item_title: str
    interlocutor: str
    messages: list[AvitoMessage] = field(default_factory=list)
    unread: bool = True


@dataclass
class _FakeState:
    chats: dict[str, _FakeChat] = field(default_factory=dict)
    counter: itertools.count = field(default_factory=lambda: itertools.count(1))


_STATE: dict[int, _FakeState] = {}


def _state(account_id: int) -> _FakeState:
    return _STATE.setdefault(account_id, _FakeState())


def reset(account_id: int | None = None) -> None:
    if account_id is None:
        _STATE.clear()
    else:
        _STATE.pop(account_id, None)


class FakeAvitoGateway:
    """Ведёт себя как AvitoGateway, но ничего никуда не отправляет."""

    def __init__(self, account_id: int = 0, self_id: str = SELF_ID) -> None:
        self.account_id = account_id
        self.self_id = self_id
        self.sent: list[tuple[str, str]] = []

    # ---------------- управление симуляцией ----------------

    def add_incoming(
        self,
        item_title: str,
        text: str,
        interlocutor: str = "Тестовый клиент",
        prefix: str = "demo-chat",
    ) -> str:
        st = _state(self.account_id)
        num = next(st.counter)
        chat_id = f"{prefix}-{num}"
        chat = _FakeChat(
            id=chat_id,
            item_id=f"demo-item-{num}",
            item_title=item_title,
            interlocutor=interlocutor,
        )
        chat.messages.append(
            AvitoMessage(
                id=f"{chat_id}-in-1",
                chat_id=chat_id,
                author_id="2000000",
                text=text,
                created_at=dt.datetime.now(dt.timezone.utc),
                direction="in",
            )
        )
        st.chats[chat_id] = chat
        return chat_id

    def remove_chat(self, chat_id: str) -> None:
        _state(self.account_id).chats.pop(chat_id, None)

    def age_chat(self, chat_id: str, hours: float) -> None:
        """Сдвигает время сообщений в прошлое — для проверки follow-up."""
        st = _state(self.account_id)
        chat = st.chats.get(chat_id)
        if not chat:
            return
        shift = dt.timedelta(hours=hours)
        for msg in chat.messages:
            if msg.created_at:
                msg.created_at -= shift

    # ---------------- интерфейс AvitoGateway ----------------

    async def get_self_id(self) -> str:
        return self.self_id

    async def list_chats(self, limit: int = 50, unread_only: bool = False) -> list[AvitoChat]:
        st = _state(self.account_id)
        out: list[AvitoChat] = []
        for chat in list(st.chats.values())[:limit]:
            if unread_only and not chat.unread:
                continue
            last = chat.messages[-1] if chat.messages else None
            out.append(
                AvitoChat(
                    id=chat.id,
                    item_id=chat.item_id,
                    item_title=chat.item_title,
                    interlocutor=chat.interlocutor,
                    last_message_text=last.text if last else "",
                    last_message_at=last.created_at if last else None,
                    last_message_direction=last.direction if last else "unknown",
                )
            )
        return out

    async def get_messages(self, chat_id: str, limit: int = 20) -> list[AvitoMessage]:
        st = _state(self.account_id)
        chat = st.chats.get(chat_id)
        return list(chat.messages[-limit:]) if chat else []

    async def send_message(self, chat_id: str, text: str) -> str:
        st = _state(self.account_id)
        chat = st.chats.get(chat_id)
        if chat is None:
            raise KeyError(f"Нет такого чата в симуляторе: {chat_id}")
        msg = AvitoMessage(
            id=f"{chat_id}-out-{len(chat.messages) + 1}",
            chat_id=chat_id,
            author_id=self.self_id,
            text=text,
            created_at=dt.datetime.now(dt.timezone.utc),
            direction="out",
        )
        chat.messages.append(msg)
        chat.unread = False
        self.sent.append((chat_id, text))
        return msg.id

    async def mark_read(self, chat_id: str) -> None:
        st = _state(self.account_id)
        chat = st.chats.get(chat_id)
        if chat:
            chat.unread = False

    async def aclose(self) -> None:
        return None

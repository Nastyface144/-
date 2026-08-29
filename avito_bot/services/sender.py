"""Отправка сообщений из очереди с суточным лимитом и равномерным темпом."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..avito.client import AvitoError
from ..config import Settings
from ..db import Database
from .gateways import GatewayPool

log = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]

PAUSED_KEY = "paused"
IDLE_SLEEP = 15


@dataclass(slots=True)
class SendOutcome:
    status: str  # sent | failed | limit | empty | paused | no_account
    detail: str = ""


class Sender:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        pool: GatewayPool,
        notify: Notifier | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.pool = pool
        self.notify = notify

    async def is_paused(self) -> bool:
        return await self.db.get_setting(PAUSED_KEY, "0") == "1"

    async def set_paused(self, value: bool) -> None:
        await self.db.set_setting(PAUSED_KEY, "1" if value else "0")

    async def daily_limit(self) -> int:
        return await self.db.get_int_setting("daily_limit", self.settings.daily_limit)

    async def send_next(self) -> SendOutcome:
        """Отправляет одно сообщение из очереди. Вся проверка лимитов — здесь."""
        if await self.is_paused():
            return SendOutcome("paused")

        account = await self.db.get_active_account()
        if account is None:
            return SendOutcome("no_account", "Нет активного аккаунта Авито")

        account_id = int(account["id"])
        limit = await self.daily_limit()
        sent_today = await self.db.sent_today(account_id)
        if sent_today >= limit:
            return SendOutcome("limit", f"Достигнут лимит {limit} сообщений в сутки")

        row = await self.db.next_queued(account_id)
        if row is None:
            return SendOutcome("empty")

        gateway = self.pool.get(account)
        send_id = int(row["id"])
        try:
            await gateway.send_message(row["avito_chat_id"], row["body"])
        except AvitoError as exc:
            text = str(exc)
            if "429" in text:
                # Лимит на стороне API — вернём в очередь, попробуем в следующий заход.
                await self.db.requeue(send_id)
                return SendOutcome("failed", text)
            await self.db.mark_failed(send_id, text)
            if self.notify:
                await self.notify(f"❌ Не отправлено (чат {row['avito_chat_id']}): {text}")
            return SendOutcome("failed", text)
        except Exception as exc:  # noqa: BLE001
            await self.db.mark_failed(send_id, str(exc))
            log.exception("Ошибка отправки")
            if self.notify:
                await self.notify(f"❌ Ошибка отправки (чат {row['avito_chat_id']}): {exc}")
            return SendOutcome("failed", str(exc))

        await self.db.mark_sent(send_id)
        return SendOutcome("sent", f"{sent_today + 1}/{limit} → чат {row['avito_chat_id']}")

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                outcome = await self.send_next()
            except Exception:  # noqa: BLE001
                log.exception("Ошибка в цикле отправки")
                outcome = SendOutcome("failed")

            if outcome.status == "sent":
                delay = await self.db.get_int_setting(
                    "send_interval_seconds", self.settings.send_interval_seconds
                )
            else:
                delay = IDLE_SLEEP
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(delay, 1))
            except asyncio.TimeoutError:
                continue

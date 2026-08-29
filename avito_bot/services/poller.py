"""Опрос чатов Авито: ставит в очередь автоответы и догоняющие сообщения."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass

from ..config import Settings
from ..db import Database, parse_ts
from . import templates as tpl
from .gateways import GatewayPool

log = logging.getLogger(__name__)

KIND_REPLY = "reply"
KIND_FOLLOWUP = "followup"


@dataclass(slots=True)
class PollResult:
    chats_seen: int = 0
    replies_queued: int = 0
    followups_queued: int = 0
    skipped_no_template: int = 0
    error: str = ""


class Poller:
    def __init__(self, db: Database, settings: Settings, pool: GatewayPool) -> None:
        self.db = db
        self.settings = settings
        self.pool = pool
        self.last_result = PollResult()

    async def poll_once(self) -> PollResult:
        result = PollResult()
        account = await self.db.get_active_account()
        if account is None:
            result.error = "Нет активного аккаунта Авито"
            self.last_result = result
            return result

        gateway = self.pool.get(account)
        try:
            if not account["avito_user_id"]:
                await self.db.set_account_user_id(int(account["id"]), await gateway.get_self_id())
            chats = await gateway.list_chats(limit=100)
        except Exception as exc:  # noqa: BLE001 — показываем причину администратору
            result.error = str(exc)
            log.warning("Опрос чатов не удался: %s", exc)
            self.last_result = result
            return result

        niches = await self.db.list_niches()
        default_niche = await self.db.get_default_niche()
        account_id = int(account["id"])
        followup_after = dt.timedelta(hours=await self._followup_hours())
        now = dt.datetime.now(dt.timezone.utc)

        for chat in chats:
            result.chats_seen += 1
            niche = tpl.match_niche(niches, chat.item_title) or default_niche
            last_in = chat.last_message_at if chat.last_message_direction == "in" else None
            last_out = chat.last_message_at if chat.last_message_direction == "out" else None
            await self.db.upsert_chat(
                account_id,
                chat.id,
                item_id=chat.item_id,
                item_title=chat.item_title,
                interlocutor=chat.interlocutor,
                niche_id=int(niche["id"]) if niche else None,
                last_incoming_at=last_in.isoformat() if last_in else None,
                last_outgoing_at=last_out.isoformat() if last_out else None,
            )
            if niche is None:
                continue

            context = {
                "item_title": chat.item_title,
                "item_id": chat.item_id or "",
                "interlocutor": chat.interlocutor,
                "niche": niche["title"],
                "account": account["title"],
            }

            # 1. Автоответ: клиент написал по нашему объявлению, мы ещё не отвечали.
            if chat.last_message_direction == "in" and not await self.db.has_send(
                account_id, chat.id, KIND_REPLY
            ):
                queued = await self._queue(
                    account_id, chat.id, niche, KIND_REPLY, context, result
                )
                if queued:
                    result.replies_queued += 1
                continue

            # 2. Follow-up: мы ответили, клиент молчит дольше заданного срока.
            if (
                chat.last_message_direction == "out"
                and await self.db.has_send(account_id, chat.id, KIND_REPLY)
                and not await self.db.has_send(account_id, chat.id, KIND_FOLLOWUP)
            ):
                stamp = chat.last_message_at
                if stamp is not None and now - stamp >= followup_after:
                    queued = await self._queue(
                        account_id, chat.id, niche, KIND_FOLLOWUP, context, result
                    )
                    if queued:
                        result.followups_queued += 1

        self.last_result = result
        return result

    async def _followup_hours(self) -> int:
        return await self.db.get_int_setting(
            "followup_after_hours", self.settings.followup_after_hours
        )

    async def _queue(
        self,
        account_id: int,
        chat_id: str,
        niche,
        kind: str,
        context: dict[str, str],
        result: PollResult,
    ) -> bool:
        rows = await self.db.list_templates(int(niche["id"]), kind=kind, only_active=True)
        template = tpl.pick_template(rows, seed=chat_id)
        if template is None:
            result.skipped_no_template += 1
            return False
        body = tpl.render(template["body"], context)
        if not body:
            result.skipped_no_template += 1
            return False
        send_id = await self.db.enqueue(
            account_id, chat_id, int(niche["id"]), int(template["id"]), kind, body
        )
        return send_id is not None

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001
                log.exception("Ошибка в цикле опроса")
            interval = await self.db.get_int_setting(
                "poll_interval_seconds", self.settings.poll_interval_seconds
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(interval, 10))
            except asyncio.TimeoutError:
                continue

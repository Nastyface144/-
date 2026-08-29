"""Сквозная проверка логики без Telegram и без сети."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avito_bot.avito import fake
from avito_bot.avito.fake import FakeAvitoGateway
from avito_bot.config import Settings
from avito_bot.crypto import SecretBox
from avito_bot.db import Database
from avito_bot.services import templates as tpl
from avito_bot.services.gateways import GatewayPool
from avito_bot.services.poller import Poller
from avito_bot.services.sender import Sender


def run(coro):
    return asyncio.run(coro)


@dataclass
class Harness:
    db: Database
    settings: Settings
    pool: GatewayPool
    poller: Poller
    sender: Sender
    account: Any
    gateway: FakeAvitoGateway

    @property
    def account_id(self) -> int:
        return int(self.account["id"])


@asynccontextmanager
async def harness(tmp_path: Path, **overrides):
    """Готовое окружение: БД, симулятор Авито, поллер и отправщик."""
    settings = Settings(
        dry_run=True,
        daily_limit=overrides.pop("daily_limit", 50),
        followup_after_hours=overrides.pop("followup_after_hours", 24),
        db_path=tmp_path / "test.sqlite3",
    )
    db = Database(settings.db_path)
    await db.connect()
    pool = GatewayPool(settings, SecretBox(""))
    try:
        account_id = await db.add_account("Тест", "cid", "secret")
        niche_id = await db.add_niche("kv", "Квартиры сдача длительно", "квартир, сда")
        await db.add_template(niche_id, "reply", "Здравствуйте! По «{item_title}» — свободна.")
        await db.add_template(niche_id, "followup", "Напоминаю про «{item_title}».")
        account = await db.get_account(account_id)
        fake.reset(account_id)
        yield Harness(
            db=db,
            settings=settings,
            pool=pool,
            poller=Poller(db, settings, pool),
            sender=Sender(db, settings, pool),
            account=account,
            gateway=pool.get(account),
        )
    finally:
        # Незакрытое соединение aiosqlite держит поток и не даёт процессу завершиться.
        await pool.aclose()
        await db.close()


# ---------------------------------------------------------------- юниты

def test_match_niche_requires_all_keywords():
    niches = [
        {"id": 1, "is_active": 1, "keywords": "квартир, сда", "title": "Квартиры"},
        {"id": 2, "is_active": 1, "keywords": "гараж", "title": "Гаражи"},
    ]
    assert tpl.match_niche(niches, "Сдам квартиру, 2-к, длительно")["id"] == 1
    assert tpl.match_niche(niches, "Продам квартиру") is None
    assert tpl.match_niche(niches, "Сдам гараж")["id"] == 2
    assert tpl.match_niche(niches, "Продам дом") is None


def test_match_niche_skips_disabled():
    niches = [{"id": 1, "is_active": 0, "keywords": "квартир", "title": "Квартиры"}]
    assert tpl.match_niche(niches, "Сдам квартиру") is None


def test_render_fills_and_drops_placeholders():
    text = tpl.render("Привет, {interlocutor}! Объявление «{item_title}». {unknown}",
                      {"interlocutor": "Иван", "item_title": "Сдам квартиру"})
    assert text == "Привет, Иван! Объявление «Сдам квартиру»."


def test_pick_template_is_stable_per_chat():
    rows = [{"id": 1, "is_active": 1}, {"id": 2, "is_active": 1}]
    first = tpl.pick_template(rows, seed="chat-42")
    assert first is tpl.pick_template(rows, seed="chat-42")


def test_secret_box_roundtrip():
    box = SecretBox(SecretBox.generate_key())
    stored = box.encrypt("s3cret")
    assert stored != "s3cret"
    assert box.decrypt(stored) == "s3cret"


# ---------------------------------------------------------------- сценарии

def test_incoming_message_gets_queued_and_sent(tmp_path):
    async def scenario():
        async with harness(tmp_path) as h:
            h.gateway.add_incoming("Сдам квартиру, 2-к, длительно", "Ещё сдаётся?")

            result = await h.poller.poll_once()
            assert result.chats_seen == 1
            assert result.replies_queued == 1

            outcome = await h.sender.send_next()
            assert outcome.status == "sent", outcome.detail
            assert len(h.gateway.sent) == 1
            assert "Сдам квартиру" in h.gateway.sent[0][1]
            assert await h.db.sent_today(h.account_id) == 1

            # Повторный опрос не должен дублировать автоответ.
            await h.poller.poll_once()
            assert await h.db.queue_size(h.account_id) == 0

    run(scenario())


def test_daily_limit_blocks_further_sends(tmp_path):
    async def scenario():
        async with harness(tmp_path, daily_limit=1) as h:
            h.gateway.add_incoming("Сдам квартиру студию, длительно", "Актуально?")
            h.gateway.add_incoming("Сдам квартиру 1-к, длительно", "Здравствуйте")
            await h.poller.poll_once()
            assert await h.db.queue_size(h.account_id) == 2

            assert (await h.sender.send_next()).status == "sent"
            second = await h.sender.send_next()
            assert second.status == "limit"
            assert len(h.gateway.sent) == 1

    run(scenario())


def test_followup_only_after_silence(tmp_path):
    async def scenario():
        async with harness(tmp_path, followup_after_hours=24) as h:
            chat_id = h.gateway.add_incoming("Сдам квартиру, длительно", "Здравствуйте")
            await h.poller.poll_once()
            await h.sender.send_next()

            # Сразу после ответа follow-up не ставится.
            result = await h.poller.poll_once()
            assert result.followups_queued == 0

            h.gateway.age_chat(chat_id, hours=48)
            result = await h.poller.poll_once()
            assert result.followups_queued == 1

            assert (await h.sender.send_next()).status == "sent"
            assert len(h.gateway.sent) == 2
            assert "Напоминаю" in h.gateway.sent[1][1]

    run(scenario())


def test_pause_stops_sending(tmp_path):
    async def scenario():
        async with harness(tmp_path) as h:
            h.gateway.add_incoming("Сдам квартиру, длительно", "Здравствуйте")
            await h.poller.poll_once()
            await h.sender.set_paused(True)
            assert (await h.sender.send_next()).status == "paused"
            await h.sender.set_paused(False)
            assert (await h.sender.send_next()).status == "sent"

    run(scenario())


def test_chat_without_matching_niche_uses_default(tmp_path):
    async def scenario():
        async with harness(tmp_path) as h:
            # Ниша по умолчанию — та единственная, что создана в harness().
            h.gateway.add_incoming("Сдам гараж", "Здравствуйте")
            result = await h.poller.poll_once()
            assert result.replies_queued == 1

    run(scenario())

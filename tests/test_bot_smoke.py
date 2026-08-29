"""Смоук-тест хендлеров: гоняем настоящие апдейты через Dispatcher.

Сеть не используется: HTTP-сессия бота подменена заглушкой, Авито — симулятором.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from avito_bot.avito import fake
from avito_bot.bot.context import AppContext
from avito_bot.bot.handlers import build_router
from avito_bot.bot import keyboards as kb
from avito_bot.config import Settings
from avito_bot.crypto import SecretBox
from avito_bot.db import Database
from avito_bot.services.gateways import GatewayPool
from avito_bot.services.poller import Poller
from avito_bot.services.sender import Sender

ADMIN_ID = 777
CHAT = Chat(id=ADMIN_ID, type="private")
USER = User(id=ADMIN_ID, is_bot=False, first_name="Админ")


class FakeSession(BaseSession):
    """Ничего не отправляет в Telegram, только собирает исходящие вызовы."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout=None):
        if isinstance(method, SendMessage):
            self.sent.append(method.text)
            return Message(
                message_id=len(self.sent),
                date=dt.datetime.now(dt.timezone.utc),
                chat=CHAT,
                from_user=USER,
                text=method.text,
            )
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage)):
            return True
        return True

    @property
    def last(self) -> str:
        return self.sent[-1] if self.sent else ""


def message_update(text: str, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=dt.datetime.now(dt.timezone.utc),
            chat=CHAT,
            from_user=USER,
            text=text,
        ),
    )


def callback_update(data: str, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=USER,
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=update_id,
                date=dt.datetime.now(dt.timezone.utc),
                chat=CHAT,
                text="menu",
            ),
        ),
    )


@asynccontextmanager
async def bot_harness(tmp_path: Path):
    """Бот с подменённой сессией, чистой БД и симулятором Авито."""
    fake.reset()
    settings = Settings(
        bot_token="123:test",
        admin_ids={ADMIN_ID},
        dry_run=True,
        daily_limit=50,
        db_path=tmp_path / "smoke.sqlite3",
    )
    db = Database(settings.db_path)
    await db.connect()
    box = SecretBox("")
    pool = GatewayPool(settings, box)
    ctx = AppContext(
        db=db,
        settings=settings,
        box=box,
        pool=pool,
        poller=Poller(db, settings, pool),
        sender=Sender(db, settings, pool),
    )
    session = FakeSession()
    bot = Bot(
        token="123:test",
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["ctx"] = ctx
    dp.include_router(build_router())
    try:
        yield bot, dp, session, ctx
    finally:
        await pool.aclose()
        await db.close()
        await bot.session.close()


def test_full_flow_through_dispatcher(tmp_path):
    async def scenario():
        async with bot_harness(tmp_path) as (bot, dp, session, ctx):
            counter = iter(range(1, 500))

            async def send(text: str) -> None:
                await dp.feed_update(bot, message_update(text, next(counter)))

            async def click(data: str) -> None:
                await dp.feed_update(bot, callback_update(data, next(counter)))

            # 1. Старт
            await send("/start")
            assert "Бот сообщений Авито" in session.last

            # 2. Заводим аккаунт через диалог
            await click("acc:add")
            await send("Основной")
            await send("test-client-id")
            await send("test-client-secret")
            accounts = await ctx.db.list_accounts()
            assert len(accounts) == 1 and accounts[0]["is_active"] == 1
            assert accounts[0]["client_secret"] != "test-client-secret"  # хранится не в открытом виде

            # 3. Ниша
            await click("niche:add")
            await send("Квартиры · сдача · длительно")
            await send("квартир, сда")
            niches = await ctx.db.list_niches()
            assert len(niches) == 1

            # 4. Клише
            niche_id = int(niches[0]["id"])
            await click(f"tpl:add:{niche_id}:reply")
            await send("Здравствуйте! «{item_title}» свободна, когда удобно посмотреть?")
            await click(f"tpl:add:{niche_id}:followup")
            await send("Напоминаю про «{item_title}».")
            assert len(await ctx.db.list_templates(niche_id)) == 2

            # 5. Лимит на сутки меняется из бота
            await click("set:num:daily_limit")
            await send("50")
            assert await ctx.db.get_int_setting("daily_limit", 0) == 50

            # 6. Демо: входящее -> опрос -> отправка
            await send(kb.BTN_DEMO)
            await click("demo:new")
            await send("Сдам квартиру, 2-к, длительно, от собственника")
            await click("demo:poll")
            assert "Автоответов в очередь: 1" in session.last
            await click("demo:send")
            assert "Отправлено" in session.last

            gateway = ctx.pool.get(await ctx.db.get_active_account())
            assert len(gateway.sent) == 1
            assert "Сдам квартиру" in gateway.sent[0][1]

            # 7. Статистика показывает факт отправки
            await send(kb.BTN_STATS)
            assert "Отправлено сегодня: <b>1</b> из 50" in session.last

            # 8. Follow-up после молчания
            await click("demo:age")
            await click("demo:poll")
            assert "Follow-up в очередь: 1" in session.last
            await click("demo:send")
            assert len(gateway.sent) == 2

    asyncio.run(scenario())


def test_non_admin_is_ignored(tmp_path):
    async def scenario():
        async with bot_harness(tmp_path) as (bot, dp, session, _ctx):
            stranger = User(id=999, is_bot=False, first_name="Чужой")
            update = Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=dt.datetime.now(dt.timezone.utc),
                    chat=Chat(id=999, type="private"),
                    from_user=stranger,
                    text="/start",
                ),
            )
            await dp.feed_update(bot, update)
            assert session.sent == []

    asyncio.run(scenario())

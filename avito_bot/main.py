"""Точка входа: поднимает бота и фоновые задачи (опрос чатов + отправка)."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .bot.context import AppContext
from .bot.handlers import build_router
from .config import Settings
from .crypto import SecretBox
from .db import Database
from .services.gateways import GatewayPool
from .services.poller import Poller
from .services.sender import Sender

log = logging.getLogger("avito_bot")

DEFAULT_NICHES = [
    (
        "kvartiry-sdacha-dlitelno-sobstvenniki",
        "Квартиры · сдача · длительно · собственники",
        "квартир, сда",
    ),
]

DEFAULT_TEMPLATES = [
    (
        "reply",
        "Здравствуйте! Спасибо за обращение по объявлению «{item_title}».\n"
        "Квартира свободна. Подскажите, на какой срок планируете и когда удобно посмотреть?",
    ),
    (
        "followup",
        "Здравствуйте! Напоминаю про «{item_title}» — вариант ещё актуален.\n"
        "Если интересно, подберу время для просмотра.",
    ),
]


async def seed(db: Database) -> None:
    """Стартовое наполнение справочников — только если база пустая."""
    if await db.list_niches():
        return
    for slug, title, keywords in DEFAULT_NICHES:
        niche_id = await db.add_niche(slug, title, keywords)
        for kind, body in DEFAULT_TEMPLATES:
            await db.add_template(niche_id, kind, body)
    log.info("Созданы стартовая ниша и клише")


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.load()
    if not settings.bot_token:
        log.error("BOT_TOKEN не задан — заполните .env (см. .env.example)")
        sys.exit(1)
    if not settings.admin_ids:
        log.error("ADMIN_IDS не заданы — бот не будет отвечать никому")
        sys.exit(1)

    db = Database(settings.db_path)
    await db.connect()
    await seed(db)

    box = SecretBox(settings.secret_key)
    pool = GatewayPool(settings, box)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    async def notify(text: str) -> None:
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, text)
            except Exception:  # noqa: BLE001 — админ мог не начать диалог с ботом
                log.warning("Не удалось уведомить админа %s", admin_id)

    poller = Poller(db, settings, pool)
    sender = Sender(db, settings, pool, notify=notify)
    ctx = AppContext(db=db, settings=settings, box=box, pool=pool, poller=poller, sender=sender)

    dp = Dispatcher(storage=MemoryStorage())
    dp["ctx"] = ctx
    dp.include_router(build_router())

    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(poller.run(stop), name="poller"),
        asyncio.create_task(sender.run(stop), name="sender"),
    ]
    log.info(
        "Старт: режим %s, лимит %s/сутки",
        "DRY-RUN" if settings.dry_run else "боевой",
        settings.daily_limit,
    )
    try:
        await dp.start_polling(bot)
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.aclose()
        await db.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()

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

    box = SecretBox(settings.secret_key)
    pool = GatewayPool(settings, box)
    await pool.load_mode(db)

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
        "проверка" if pool.dry_run else "боевой",
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


async def check() -> int:
    """Предполётная проверка: настройки, связь с Telegram, база, аккаунт Авито."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    settings = Settings.load()
    problems: list[str] = []

    print("Проверка настроек")
    if settings.bot_token:
        print("  BOT_TOKEN: задан")
    else:
        problems.append("BOT_TOKEN не задан в .env (возьмите токен у @BotFather)")
    if settings.admin_ids:
        print(f"  ADMIN_IDS: {', '.join(str(i) for i in sorted(settings.admin_ids))}")
    else:
        problems.append("ADMIN_IDS не заданы — бот не будет отвечать никому (@userinfobot)")
    if not settings.secret_key:
        print("  SECRET_KEY: не задан — секреты Авито будут храниться в открытом виде")
    else:
        print("  SECRET_KEY: задан")
    dry_run = settings.dry_run
    print(f"  Лимит: {settings.daily_limit} сообщений в сутки")

    if problems:
        print("\nНе хватает настроек:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nСвязь с Telegram")
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        me = await bot.get_me()
        print(f"  Бот на связи: @{me.username} (id {me.id})")
    except Exception as exc:  # noqa: BLE001
        print(f"  Не удалось подключиться: {exc}")
        print("  Причины: неверный BOT_TOKEN, нет интернета или Telegram блокируется сетью.")
        return 1
    finally:
        await bot.session.close()

    print("\nБаза данных")
    db = Database(settings.db_path)
    try:
        await db.connect()
        stored = await db.get_setting("dry_run", "")
        if stored in {"0", "1"}:
            dry_run = stored == "1"
        print("  Режим: " + ("проверка, в Авито ничего не уходит" if dry_run else "боевой"))
        accounts = await db.list_accounts()
        niches = await db.list_niches()
        print(f"  Файл: {settings.db_path}")
        print(f"  Аккаунтов Авито: {len(accounts)}, направлений: {len(niches)}")
        if not accounts:
            print("  Аккаунт подключается в самом боте: команда /start.")
        elif not dry_run:
            active = await db.get_active_account()
            if active is not None:
                pool = GatewayPool(settings, SecretBox(settings.secret_key))
                await pool.load_mode(db)
                try:
                    user_id = await pool.get(active).get_self_id()
                    print(f"  Авито отвечает, user_id: {user_id}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  Авито недоступен: {exc}")
                    return 1
                finally:
                    await pool.aclose()
    finally:
        await db.close()

    print("\nВсё готово. Запуск: python -m avito_bot")
    return 0


def main() -> None:
    if "--check" in sys.argv[1:]:
        sys.exit(asyncio.run(check()))
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()

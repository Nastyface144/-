"""Настройки приложения: читаются из переменных окружения / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "да"}


def _ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    out: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            out.add(int(chunk))
    return out


@dataclass(slots=True)
class Settings:
    bot_token: str = ""
    admin_ids: set[int] = field(default_factory=set)
    dry_run: bool = True
    daily_limit: int = 50
    send_interval_seconds: int = 45
    poll_interval_seconds: int = 60
    followup_after_hours: int = 24
    db_path: Path = Path("data/bot.sqlite3")
    secret_key: str = ""
    avito_api_base: str = "https://api.avito.ru"
    proxy_url: str = ""

    @classmethod
    def load(cls, env_file: str | os.PathLike[str] | None = None) -> "Settings":
        # Без явного пути ищем .env рядом с проектом, а не только в текущей папке:
        # иначе запуск из другого каталога молча остаётся без настроек.
        candidates = (
            [Path(env_file)]
            if env_file
            else [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]
        )
        for candidate in candidates:
            if candidate.exists():
                load_dotenv(candidate)
                break
        return cls(
            bot_token=os.getenv("BOT_TOKEN", "").strip(),
            admin_ids=_ids("ADMIN_IDS"),
            dry_run=_bool("DRY_RUN", True),
            daily_limit=_int("DAILY_LIMIT", 50),
            send_interval_seconds=_int("SEND_INTERVAL_SECONDS", 45),
            poll_interval_seconds=_int("POLL_INTERVAL_SECONDS", 60),
            followup_after_hours=_int("FOLLOWUP_AFTER_HOURS", 24),
            db_path=Path(os.getenv("DB_PATH", "data/bot.sqlite3").strip() or "data/bot.sqlite3"),
            secret_key=os.getenv("SECRET_KEY", "").strip(),
            avito_api_base=os.getenv("AVITO_API_BASE", "https://api.avito.ru").strip().rstrip("/"),
            proxy_url=os.getenv("PROXY_URL", "").strip(),
        )

    def is_admin(self, user_id: int) -> bool:
        # Пустой список админов = закрытый бот: не отвечаем никому.
        return user_id in self.admin_ids

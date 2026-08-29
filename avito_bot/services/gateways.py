"""Создание клиента Авито для аккаунта (реальный API или симулятор).

Режим (проверка/боевой) переключается из бота, поэтому он хранится в базе,
а значение из .env служит только начальным.
"""

from __future__ import annotations

from typing import Any

from ..avito import AvitoGateway, FakeAvitoGateway, HttpAvitoGateway
from ..config import Settings
from ..crypto import SecretBox
from ..db import Database

DRY_RUN_KEY = "dry_run"


def build_gateway(
    account: Any, settings: Settings, box: SecretBox, dry_run: bool
) -> AvitoGateway:
    if dry_run:
        return FakeAvitoGateway(account_id=int(account["id"]))
    return HttpAvitoGateway(
        client_id=account["client_id"],
        client_secret=box.decrypt(account["client_secret"]),
        base_url=settings.avito_api_base,
        proxy_url=settings.proxy_url,
        user_id=account["avito_user_id"] or None,
    )


class GatewayPool:
    """Кэш клиентов по аккаунту, чтобы не пересоздавать HTTP-клиент и токен."""

    def __init__(self, settings: Settings, box: SecretBox) -> None:
        self._settings = settings
        self._box = box
        self._pool: dict[int, AvitoGateway] = {}
        self._dry_run = settings.dry_run

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    async def load_mode(self, db: Database) -> None:
        """Поднимает режим из базы; если там пусто — берёт значение из .env."""
        stored = await db.get_setting(DRY_RUN_KEY, "")
        if stored in {"0", "1"}:
            self._dry_run = stored == "1"

    async def set_dry_run(self, db: Database, value: bool) -> None:
        await db.set_setting(DRY_RUN_KEY, "1" if value else "0")
        if value != self._dry_run:
            self._dry_run = value
            # Клиенты созданы под прежний режим — пересоздадим их при следующем обращении.
            await self.aclose()

    def get(self, account: Any) -> AvitoGateway:
        account_id = int(account["id"])
        gateway = self._pool.get(account_id)
        if gateway is None:
            gateway = build_gateway(account, self._settings, self._box, self._dry_run)
            self._pool[account_id] = gateway
        return gateway

    async def drop(self, account_id: int) -> None:
        gateway = self._pool.pop(account_id, None)
        if gateway is not None:
            await gateway.aclose()

    async def aclose(self) -> None:
        for gateway in list(self._pool.values()):
            await gateway.aclose()
        self._pool.clear()

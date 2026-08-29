"""Общий контекст приложения, доступный хендлерам."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..crypto import SecretBox
from ..db import Database
from ..services.gateways import GatewayPool
from ..services.poller import Poller
from ..services.sender import Sender


@dataclass(slots=True)
class AppContext:
    db: Database
    settings: Settings
    box: SecretBox
    pool: GatewayPool
    poller: Poller
    sender: Sender

    def is_owner(self, user_id: int) -> bool:
        """Владелец — тот, кто указан в ADMIN_IDS. Он раздаёт доступ остальным."""
        return self.settings.is_admin(user_id)

    async def has_access(self, user_id: int) -> bool:
        if self.is_owner(user_id):
            return True
        return user_id in await self.db.extra_admins()

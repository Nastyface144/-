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

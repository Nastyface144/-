"""Клиент официального API Авито (авторизация + мессенджер).

Все пути вынесены в константы: если Авито поменяет версию эндпоинта,
править нужно только здесь. Актуальные версии — в developers.avito.ru.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, Protocol

import httpx

from .models import AvitoChat, AvitoMessage

log = logging.getLogger(__name__)

TOKEN_PATH = "/token/"
SELF_PATH = "/core/v1/accounts/self"
CHATS_PATH = "/messenger/v2/accounts/{user_id}/chats"
MESSAGES_PATH = "/messenger/v3/accounts/{user_id}/chats/{chat_id}/messages/"
SEND_PATH = "/messenger/v1/accounts/{user_id}/chats/{chat_id}/messages"
READ_PATH = "/messenger/v1/accounts/{user_id}/chats/{chat_id}/read"

# Сколько секунд до истечения токена считаем его уже просроченным.
TOKEN_LEEWAY = 60


class AvitoError(RuntimeError):
    """Ошибка обращения к API Авито."""


class AvitoGateway(Protocol):
    """Интерфейс, который использует остальной код (реальный API или симулятор)."""

    async def get_self_id(self) -> str: ...

    async def list_chats(self, limit: int = 50, unread_only: bool = False) -> list[AvitoChat]: ...

    async def get_messages(self, chat_id: str, limit: int = 20) -> list[AvitoMessage]: ...

    async def send_message(self, chat_id: str, text: str) -> str: ...

    async def mark_read(self, chat_id: str) -> None: ...

    async def aclose(self) -> None: ...


class HttpAvitoGateway:
    """Реальный клиент. Токен получается по client_credentials и кэшируется."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        base_url: str = "https://api.avito.ru",
        proxy_url: str = "",
        timeout: float = 20.0,
        user_id: str | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._user_id = user_id
        self._token: str = ""
        self._token_expires_at: dt.datetime | None = None
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            proxy=proxy_url or None,
            headers={"User-Agent": "avito-messenger-bot/0.1"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------------- авторизация ----------------

    async def _ensure_token(self) -> str:
        async with self._lock:
            now = dt.datetime.now(dt.timezone.utc)
            if self._token and self._token_expires_at and self._token_expires_at > now:
                return self._token
            resp = await self._http.post(
                TOKEN_PATH,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                raise AvitoError(f"Не удалось получить токен: {resp.status_code} {resp.text[:200]}")
            payload = resp.json()
            token = payload.get("access_token")
            if not token:
                raise AvitoError("В ответе на запрос токена нет access_token")
            expires_in = int(payload.get("expires_in", 3600))
            self._token = str(token)
            self._token_expires_at = now + dt.timedelta(seconds=max(expires_in - TOKEN_LEEWAY, 60))
            return self._token

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        resp = await self._http.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401:
            # Токен мог протухнуть раньше срока — один повтор с новым токеном.
            self._token = ""
            token = await self._ensure_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = await self._http.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 429:
            raise AvitoError("Превышен лимит запросов к API Авито (429), попробуем позже")
        if resp.status_code >= 400:
            raise AvitoError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise AvitoError(f"Некорректный JSON от {path}") from exc
        return data if isinstance(data, dict) else {"items": data}

    # ---------------- методы ----------------

    async def get_self_id(self) -> str:
        if self._user_id:
            return self._user_id
        data = await self._request("GET", SELF_PATH)
        user_id = data.get("id")
        if user_id is None:
            raise AvitoError("В ответе /core/v1/accounts/self нет id")
        self._user_id = str(user_id)
        return self._user_id

    async def list_chats(self, limit: int = 50, unread_only: bool = False) -> list[AvitoChat]:
        user_id = await self.get_self_id()
        params: dict[str, Any] = {"limit": min(limit, 100), "offset": 0}
        if unread_only:
            params["unread_only"] = "true"
        data = await self._request("GET", CHATS_PATH.format(user_id=user_id), params=params)
        raw_chats = data.get("chats") or data.get("items") or []
        return [AvitoChat.from_api(raw, user_id) for raw in raw_chats]

    async def get_messages(self, chat_id: str, limit: int = 20) -> list[AvitoMessage]:
        user_id = await self.get_self_id()
        data = await self._request(
            "GET",
            MESSAGES_PATH.format(user_id=user_id, chat_id=chat_id),
            params={"limit": min(limit, 100), "offset": 0},
        )
        raw_messages = data.get("messages") or data.get("items") or []
        return [AvitoMessage.from_api(raw, chat_id, user_id) for raw in raw_messages]

    async def send_message(self, chat_id: str, text: str) -> str:
        user_id = await self.get_self_id()
        data = await self._request(
            "POST",
            SEND_PATH.format(user_id=user_id, chat_id=chat_id),
            json={"message": {"text": text}, "type": "text"},
        )
        return str(data.get("id", ""))

    async def mark_read(self, chat_id: str) -> None:
        user_id = await self.get_self_id()
        await self._request("POST", READ_PATH.format(user_id=user_id, chat_id=chat_id))

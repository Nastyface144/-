"""Шифрование секретов аккаунтов Авито перед записью в БД."""

from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

_PLAIN_PREFIX = "plain:"
_ENC_PREFIX = "enc:"


class SecretBox:
    """Обёртка над Fernet. Без SECRET_KEY работает, но пишет в БД как есть."""

    def __init__(self, key: str = "") -> None:
        self._fernet: Fernet | None = None
        if key:
            try:
                self._fernet = Fernet(key.encode())
            except (ValueError, TypeError):
                log.error("SECRET_KEY некорректен, секреты будут храниться в открытом виде")
        if self._fernet is None:
            log.warning(
                "SECRET_KEY не задан: client_secret аккаунтов Авито хранится в БД "
                "в открытом виде. Сгенерируйте ключ и перезапустите бота."
            )

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            return _PLAIN_PREFIX + value
        return _ENC_PREFIX + self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, stored: str) -> str:
        if stored.startswith(_PLAIN_PREFIX):
            return stored[len(_PLAIN_PREFIX):]
        if stored.startswith(_ENC_PREFIX):
            if self._fernet is None:
                raise RuntimeError(
                    "Секрет зашифрован, но SECRET_KEY не задан — задайте прежний ключ."
                )
            try:
                return self._fernet.decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
            except InvalidToken as exc:
                raise RuntimeError("SECRET_KEY не подходит к сохранённым секретам.") from exc
        # Записи, сделанные до появления префиксов.
        return stored

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

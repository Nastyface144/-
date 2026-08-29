"""Генерация SECRET_KEY для шифрования секретов аккаунтов Авито.

Запуск из корня проекта: python tools/gen_key.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avito_bot.crypto import SecretBox  # noqa: E402

if __name__ == "__main__":
    print(SecretBox.generate_key())

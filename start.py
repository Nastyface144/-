"""Установка и запуск бота одной командой: python start.py

Работает одинаково на Windows, macOS и Linux. Ставит зависимости,
спрашивает токен и ваш Telegram ID, пишет .env и запускает бота.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MIN_PYTHON = (3, 10)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def say(text: str) -> None:
    print(f"\n=== {text} ===")


def die(text: str) -> None:
    print(f"\nОшибка: {text}")
    try:
        # Чтобы окно, запущенное двойным кликом, не закрылось мгновенно.
        input("Нажмите Enter, чтобы закрыть...")
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(1)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        die("ввод прерван.")
        return ""


def step_python() -> None:
    say("1/5 Проверяю Python")
    if sys.version_info < MIN_PYTHON:
        die(
            f"нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее, "
            f"а установлен {sys.version.split()[0]}. Обновите Python с python.org."
        )
    print(f"Python {sys.version.split()[0]} — подходит.")


def step_deps() -> None:
    say("2/5 Ставлю зависимости (займёт минуту)")
    if not venv_python().exists():
        try:
            run([sys.executable, "-m", "venv", str(VENV)])
        except subprocess.CalledProcessError:
            die("не удалось создать виртуальное окружение (.venv).")
    pip = [str(venv_python()), "-m", "pip", "install"]
    try:
        run([*pip, "--quiet", "--upgrade", "pip"])
        # Без --quiet: видно, что установка идёт, а не зависла.
        run([*pip, "-r", str(ROOT / "requirements.txt")])
    except subprocess.CalledProcessError:
        die(
            "не удалось установить зависимости.\n"
            "Проверьте интернет, удалите папку .venv и запустите скрипт снова."
        )
    print("Готово.")


def step_env() -> None:
    say("3/5 Настройки")
    env_file = ROOT / ".env"
    if env_file.exists():
        print("Файл .env уже есть — оставляю как есть.")
        print("Чтобы настроить заново, удалите .env и запустите скрипт снова.")
        return

    print("Токен бота берётся у @BotFather в Telegram (команда /newbot).")
    token = ask("Вставьте BOT_TOKEN: ")
    if not token:
        die("токен не может быть пустым.")

    print("\nВаш Telegram ID — это число, его пришлёт @userinfobot.")
    admin_id = ask("Вставьте ваш ID: ")
    if not admin_id.isdigit():
        die("ID должен быть числом, например 123456789.")

    result = subprocess.run(
        [str(venv_python()), str(ROOT / "tools" / "gen_key.py")],
        capture_output=True,
        text=True,
    )
    secret_key = result.stdout.strip()
    if result.returncode != 0 or not secret_key:
        die("не удалось сгенерировать SECRET_KEY.")

    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("BOT_TOKEN="):
            line = f"BOT_TOKEN={token}"
        elif line.startswith("ADMIN_IDS="):
            line = f"ADMIN_IDS={admin_id}"
        elif line.startswith("SECRET_KEY="):
            line = f"SECRET_KEY={secret_key}"
        lines.append(line)
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        env_file.chmod(0o600)
    print("Записал .env — ключи хранятся только в этом файле, на вашем компьютере.")


def step_check() -> None:
    say("4/5 Проверяю связь с Telegram")
    result = subprocess.run([str(venv_python()), "-m", "avito_bot", "--check"], cwd=ROOT)
    if result.returncode != 0:
        die("проверка не прошла, см. сообщение выше.")


def step_start() -> None:
    say("5/5 Запускаю бота")
    print("Откройте своего бота в Telegram и отправьте /start.")
    print("Остановить: Ctrl+C. Запустить снова: python start.py")
    print()
    try:
        subprocess.run([str(venv_python()), "-m", "avito_bot"], cwd=ROOT)
    except KeyboardInterrupt:
        print("\nБот остановлен.")


def main() -> None:
    print("Установка Telegram-бота сообщений Авито")
    step_python()
    step_deps()
    step_env()
    step_check()
    step_start()


if __name__ == "__main__":
    main()

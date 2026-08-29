#!/usr/bin/env bash
# Установка и запуск бота: спрашивает токен и ваш Telegram ID, остальное делает сам.
set -euo pipefail

cd "$(dirname "$0")"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

# ---- 1. Python -------------------------------------------------------------
say "1/5 Проверяю Python"
PY=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
        major=${version%%.*}; minor=${version##*.}
        if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then PY="$candidate"; break; fi
    fi
done
[ -n "$PY" ] || die "нужен Python 3.10+. Установите его и запустите скрипт снова."
echo "Использую $PY ($("$PY" --version))"

# ---- 2. Зависимости --------------------------------------------------------
say "2/5 Ставлю зависимости"
[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
# Без --quiet: видно, что установка идёт, а не зависла.
./.venv/bin/pip install -r requirements.txt
echo "Готово."

# ---- 3. Настройки ----------------------------------------------------------
say "3/5 Настройки"
if [ -f .env ]; then
    warn "Файл .env уже есть — оставляю как есть."
    warn "Чтобы настроить заново: удалите .env и запустите скрипт снова."
else
    echo "Токен бота берётся у @BotFather (команда /newbot)."
    printf 'Вставьте BOT_TOKEN: '
    read -r BOT_TOKEN
    [ -n "$BOT_TOKEN" ] || die "токен не может быть пустым."

    echo
    echo "Ваш Telegram ID — числом, его пришлёт @userinfobot."
    printf 'Вставьте ваш ID: '
    read -r ADMIN_ID
    case "$ADMIN_ID" in
        ''|*[!0-9]*) die "ID должен быть числом, например 123456789." ;;
    esac

    SECRET_KEY=$(./.venv/bin/python tools/gen_key.py)
    sed -e "s|^BOT_TOKEN=.*|BOT_TOKEN=${BOT_TOKEN}|" \
        -e "s|^ADMIN_IDS=.*|ADMIN_IDS=${ADMIN_ID}|" \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" \
        .env.example > .env
    chmod 600 .env
    echo "Записал .env (доступ только вам)."
fi

# ---- 4. Проверка -----------------------------------------------------------
say "4/5 Проверяю связь с Telegram"
./.venv/bin/python -m avito_bot --check || die "проверка не прошла, см. сообщение выше."

# ---- 5. Запуск -------------------------------------------------------------
say "5/5 Запускаю бота"
echo "Откройте своего бота в Telegram и отправьте /start."
echo "Остановить: Ctrl+C. Запустить снова: ./setup.sh"
echo
exec ./.venv/bin/python -m avito_bot

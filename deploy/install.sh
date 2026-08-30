#!/usr/bin/env bash
# Установка бота на сервер (Ubuntu/Debian) одной командой.
#
#   curl -fsSL https://raw.githubusercontent.com/Nastyface144/-/claude/peaceful-wozniak-jbwywm/deploy/install.sh | sudo bash
#
# Или, если репозиторий уже склонирован:  sudo ./deploy/install.sh
#
# Скрипт спросит токен бота и ваш Telegram ID, поставит зависимости,
# настроит автозапуск и запустит бота.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Nastyface144/-.git}"
BRANCH="${BRANCH:-claude/peaceful-wozniak-jbwywm}"
APP_DIR="${APP_DIR:-/opt/avito-bot}"
APP_USER="${APP_USER:-avito}"
SERVICE="avito-bot"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запустите с правами root: sudo $0"

# ---- 1. Системные пакеты ---------------------------------------------------
say "1/6 Ставлю системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates >/dev/null
echo "Готово: $(python3 --version), $(git --version)"

# ---- 2. Пользователь и код -------------------------------------------------
say "2/6 Готовлю каталог $APP_DIR"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

if [ -d "$APP_DIR/.git" ]; then
    echo "Код уже есть — обновляю."
    git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    git -C "$APP_DIR" checkout --quiet "$BRANCH"
    git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
else
    rm -rf "$APP_DIR"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
mkdir -p "$APP_DIR/data"

# ---- 3. Зависимости --------------------------------------------------------
say "3/6 Ставлю зависимости"
[ -x "$APP_DIR/.venv/bin/python" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
echo "Готово."

# ---- 4. Настройки ----------------------------------------------------------
say "4/6 Настройки"
if [ -f "$APP_DIR/.env" ]; then
    warn "Файл .env уже есть — оставляю как есть."
    warn "Чтобы настроить заново: rm $APP_DIR/.env и запустите скрипт снова."
else
    BOT_TOKEN="${BOT_TOKEN:-}"
    ADMIN_IDS="${ADMIN_IDS:-}"
    if [ -z "$BOT_TOKEN" ]; then
        echo "Токен бота — у @BotFather в Telegram (команда /newbot)."
        printf 'Вставьте BOT_TOKEN: '
        read -r BOT_TOKEN </dev/tty
    fi
    [ -n "$BOT_TOKEN" ] || die "токен не может быть пустым."
    if [ -z "$ADMIN_IDS" ]; then
        echo
        echo "Ваш Telegram ID — число, его пришлёт @userinfobot."
        printf 'Вставьте ваш ID: '
        read -r ADMIN_IDS </dev/tty
    fi
    case "$ADMIN_IDS" in
        ''|*[!0-9,\ ]*) die "ID должен быть числом, например 123456789." ;;
    esac

    SECRET_KEY=$("$APP_DIR/.venv/bin/python" "$APP_DIR/tools/gen_key.py")
    sed -e "s|^BOT_TOKEN=.*|BOT_TOKEN=${BOT_TOKEN}|" \
        -e "s|^ADMIN_IDS=.*|ADMIN_IDS=${ADMIN_IDS}|" \
        -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" \
        "$APP_DIR/.env.example" > "$APP_DIR/.env"
    echo "Записал $APP_DIR/.env"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

# ---- 5. Проверка -----------------------------------------------------------
say "5/6 Проверяю связь с Telegram"
CHECK_OK=1
(cd "$APP_DIR" && sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m avito_bot --check) || CHECK_OK=0
if [ "$CHECK_OK" -eq 0 ]; then
    # Не обрываем установку: чаще всего дело в прокси или опечатке в токене,
    # и это правится в .env без повторной установки.
    warn ""
    warn "Проверка не прошла — см. сообщение выше. Установку продолжаю."
    warn "Если Telegram недоступен с этого сервера, добавьте прокси:"
    warn "  nano $APP_DIR/.env      # строка TELEGRAM_PROXY_URL="
    warn "  systemctl restart $SERVICE"
fi

# ---- 6. Автозапуск ---------------------------------------------------------
say "6/6 Настраиваю автозапуск"
sed -e "s|^User=.*|User=${APP_USER}|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=${APP_DIR}|" \
    -e "s|^ExecStart=.*|ExecStart=${APP_DIR}/.venv/bin/python -m avito_bot|" \
    "$APP_DIR/deploy/avito-bot.service" > "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable --quiet --now "$SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl --no-pager --lines=5 status "$SERVICE" || true

if [ "$CHECK_OK" -eq 0 ]; then
    cat <<EOM

Бот установлен, но проверка связи не прошла — сейчас он работать не будет.

  Что показывает бот:  journalctl -u $SERVICE -n 30
  Повторить проверку:  cd $APP_DIR && ./.venv/bin/python -m avito_bot --check
  Настройки:           nano $APP_DIR/.env  (BOT_TOKEN, TELEGRAM_PROXY_URL)
  После правки:        systemctl restart $SERVICE
EOM
    exit 1
fi

cat <<EOM

Готово. Бот работает и сам поднимется после перезагрузки сервера.

  Состояние:   systemctl status $SERVICE
  Логи:        journalctl -u $SERVICE -f
  Перезапуск:  systemctl restart $SERVICE
  Обновление:  $APP_DIR/deploy/install.sh

Откройте бота в Telegram и отправьте /start.
EOM

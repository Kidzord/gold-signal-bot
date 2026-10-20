#!/usr/bin/env bash
# Установка бота на Raspberry Pi OS (Bookworm, 64-bit).
# Запускать из папки проекта:  sudo bash deploy/install-pi.sh
set -euo pipefail

APP_DIR=/opt/gold-signal-bot
BOT_USER=botuser
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== 1/7 пакеты =="
apt-get update
apt-get install -y python3 python3-venv python3-pip

echo "== 2/7 пользователь =="
if ! id -u "$BOT_USER" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$BOT_USER"
fi

echo "== 3/7 копирование проекта =="
mkdir -p "$APP_DIR"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
    cp -r "$SRC_DIR"/. "$APP_DIR"/
fi
mkdir -p "$APP_DIR/cache" "$APP_DIR/materials"

echo "== 4/7 виртуальное окружение =="
cd "$APP_DIR"
if [ ! -x venv/bin/python ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "== 5/7 права =="
chown -R "$BOT_USER":"$BOT_USER" "$APP_DIR"
chmod 600 "$APP_DIR/config.json" 2>/dev/null || true

echo "== 6/7 служба systemd =="
install -m 644 "$APP_DIR/deploy/gold-signal-bot.service" /etc/systemd/system/
touch /var/log/gold-signal-bot.log
chown "$BOT_USER":"$BOT_USER" /var/log/gold-signal-bot.log
systemctl daemon-reload
systemctl enable --now gold-signal-bot

echo "== 7/7 проверка =="
sleep 3
systemctl status gold-signal-bot --no-pager || true
echo
echo "Логи:      tail -f /var/log/gold-signal-bot.log"
echo "Перезапуск: systemctl restart gold-signal-bot"

# Деплой бота на VPS (Ubuntu 22.04 / 24.04)

Бот будет работать круглосуточно, независимо от вашего компьютера.

## 1. Сервер

Минимальный: 1 vCPU, 1 ГБ RAM, 10 ГБ диска (хватит HuggingFace-класса, $3–6/мес).
Подойдёт любой провайдер: Hetzner, Time4VPS, Aeza, Vultr, DigitalOcean.

Создайте сервер с Ubuntu 22.04/24.04 и получите IP + пароль (или SSH-ключ).

## 2. Подключение

```bash
ssh root@ВАШ_IP
```

## 3. Пользователь и зависимости

```bash
adduser --disabled-password --gecos "" botuser
apt update && apt install -y python3 python3-venv python3-pip
mkdir -p /opt/gold-signal-bot
```

## 4. Копирование проекта

С вашего компьютера (PowerShell, из папки проекта):

```powershell
scp -r . root@ВАШ_IP:/opt/gold-signal-bot
```

Исключить кэш и материалы можно так:

```powershell
scp -r bot.py analysis.py strategy.py backtest.py indicators.py market.py `
       storage.py tg.py instruments.py msnr.py msnr_v2.py dbo.py ranges.py `
       asian.py flip.py fvg.py ote.py sweep_bos.py requirements.txt deploy `
       config.json root@ВАШ_IP:/opt/gold-signal-bot
```

`config.json` уже содержит токен и список инструментов — он переносится как есть.

## 5. Окружение

```bash
cd /opt/gold-signal-bot
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r requirements.txt
chown -R botuser:botuser /opt/gold-signal-bot
```

## 6. Проверка

```bash
sudo -u botuser ./venv/bin/python bot.py --check
```

Должно показать токен, инструменты и число подписчиков.

## 7. Служба systemd

```bash
cp deploy/gold-signal-bot.service /etc/systemd/system/
touch /var/log/gold-signal-bot.log
chown botuser:botuser /var/log/gold-signal-bot.log
systemctl daemon-reload
systemctl enable --now gold-signal-bot
systemctl status gold-signal-bot --no-pager
```

Логи:

```bash
tail -f /var/log/gold-signal-bot.log
```

Перезапуск после обновления файлов:

```bash
systemctl restart gold-signal-bot
```

## 8. Важно

- **Остановите бота на домашнем компьютере**, иначе два процесса будут драться за
  `getUpdates` (Telegram отдаст одному из них ошибку 409). Проще всего:
  `Unregister-ScheduledTask -TaskName GoldSignalBot -Confirm:$false`.
- Состояние (`state.json`) хранится на сервере. Если нужно перенести — скопируйте файл.
- Токен лежит в `config.json` на сервере: доступ к нему должен быть только у вас
  (`chmod 600 config.json`).
- Обновления Windows и выключение вашего ПК больше не влияют на сигналы.

## 9. Бэкап (по желанию)

```bash
crontab -u botuser -e
```

Добавить:

```
0 3 * * * cp /opt/gold-signal-bot/state.json /opt/gold-signal-bot/state.backup.json
```

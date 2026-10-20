# Docker: запуск бота в контейнере

Даёт переносимость: одна команда на любой машине с Docker — Linux, Windows, NAS,
Raspberry Pi. Логика бота не меняется.

## 1. Подготовка

```bash
# в папке проекта
cp config.ci.json config.json      # если конфига ещё нет
nano config.json                   # вставить токен ИЛИ использовать .env
echo "TELEGRAM_BOT_TOKEN=ваш_токен" > .env
```

`config.json` и `state.json` монтируются снаружи — переживают пересоздание контейнера.

## 2. Запуск

```bash
docker compose up -d --build
docker compose logs -f
```

Проверка:

```bash
docker compose ps
docker compose exec bot python bot.py --check
```

## 3. Веб-панель

В `config.json` добавьте:

```json
"web": {"enabled": true, "host": "0.0.0.0", "port": 8080}
```

Перезапуск: `docker compose restart`. Панель: `http://127.0.0.1:8080`

Порт в `docker-compose.yml` специально привязан к `127.0.0.1` — снаружи не видно.
Если нужен доступ из сети, поменяйте на `"8080:8080"` и закройте паролем/файрволом:
панель без авторизации.

## 4. Обновление

```bash
git pull
docker compose up -d --build
```

## 5. Остановка

```bash
docker compose down          # остановить
docker compose down -v       # остановить и удалить данные тома (state/cache останутся на хосте)
```

## 6. Важно

- Одновременно должен работать **только один** экземпляр бота (иначе Telegram 409).
  Перед запуском контейнера остановите локального бота и workflow GitHub Actions.
- Контейнер работает от root внутри, но наружу ничего не публикует, кроме панели
  на localhost. Для продакшена добавьте `user:` в compose.
- На Raspberry Pi собирается дольше (ARM), но работает так же.

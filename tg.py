"""Минимальный клиент Telegram Bot API на stdlib (без внешних зависимостей)."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GoldSignalBot/1.0"


class TgError(RuntimeError):
    pass


class Tg:
    def __init__(self, token: str, timeout: int = 65):
        self.token = token
        self.timeout = timeout

    def call(self, method: str, **params):
        url = API.format(token=self.token, method=method)
        body = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                except (ValueError, OSError):
                    raise TgError(f"HTTP {exc.code} on {method}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == 2:
                    raise TgError(f"network error on {method}: {exc}") from exc
                time.sleep(2 * (attempt + 1))
                continue

            if payload.get("ok"):
                return payload.get("result")

            code = payload.get("error_code")
            if code == 429:
                wait = payload.get("parameters", {}).get("retry_after", 3)
                log.warning("429 rate limit on %s, ждём %s c", method, wait)
                time.sleep(float(wait) + 0.5)
                continue
            raise TgError(f"Telegram {code}: {payload.get('description')}")

        raise TgError(f"{method}: не удалось выполнить запрос")

    # --- удобные обёртки
    def get_me(self) -> dict:
        return self.call("getMe")

    def delete_webhook(self) -> bool:
        return bool(self.call("deleteWebhook", drop_pending_updates=False))

    def get_updates(self, offset: int | None = None, timeout: int = 50):
        params = {
            "timeout": timeout,
            "allowed_updates": ["message", "channel_post"],
            "limit": 100,
        }
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", **params)

    def send(self, chat_id, text: str, preview: bool = False):
        return self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=not preview,
        )

    def set_commands(self, commands: list[dict]) -> bool:
        return bool(self.call("setMyCommands", commands=commands))

    # --- файлы (для сбора материалов)
    def get_file(self, file_id: str) -> dict:
        return self.call("getFile", file_id=file_id)

    def download(self, file_id: str, dest: str) -> str:
        """Скачивает файл Telegram в dest, возвращает путь."""
        info = self.get_file(file_id)
        path = info.get("file_path")
        if not path:
            raise TgError("Telegram не вернул file_path")
        url = FILE_API.format(token=self.token, path=path)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
                fh.write(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TgError(f"не удалось скачать файл: {exc}") from exc
        return dest


def split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit:
            parts.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    return parts


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

"""Минимальный клиент Telegram Bot API на stdlib (без внешних зависимостей)."""
from __future__ import annotations

import html
import http.client
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GoldSignalBot/1.0"

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # лимит Bot API: 20 МиБ для getFile, 25 МиБ с запасом
DOWNLOAD_CHUNK = 64 * 1024  # читаем ответ чанками, а не целиком в память


class TgError(RuntimeError):
    pass


def _is_parse_error(exc: BaseException) -> bool:
    """Telegram 400 «can't parse entities» и родственные ошибки разметки."""
    msg = str(exc).lower()
    return "parse" in msg or "entit" in msg


def _html_to_plain(text: str) -> str:
    """Снять теги и раскрыть HTML-сущности — plain-text фолбэк для send()."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


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

    def send(self, chat_id, text: str, preview: bool = False, html: bool = True):
        """Отправляет текст; html=True — parse_mode=HTML с фолбэком на plain-text."""
        common = {"chat_id": chat_id, "disable_web_page_preview": not preview}
        if html:
            try:
                return self.call("sendMessage", text=text, parse_mode="HTML", **common)
            except TgError as exc:
                if not _is_parse_error(exc):
                    raise
                log.warning("HTML отклонён Telegram (%s) — повтор без parse_mode", exc)
        return self.call("sendMessage", text=_html_to_plain(text) if html else text, **common)

    def set_commands(self, commands: list[dict]) -> bool:
        return bool(self.call("setMyCommands", commands=commands))

    # --- файлы (для сбора материалов)
    def get_file(self, file_id: str) -> dict:
        return self.call("getFile", file_id=file_id)

    def download(self, file_id: str, dest: str) -> str:
        """Скачивает файл Telegram в dest, возвращает путь. Лимит — 25 МиБ."""
        info = self.get_file(file_id)
        path = info.get("file_path")
        if not path:
            raise TgError("Telegram не вернул file_path")
        size = info.get("file_size")
        if isinstance(size, int) and size > MAX_DOWNLOAD_BYTES:
            raise TgError(
                f"файл {size} Б больше лимита 25 МиБ ({MAX_DOWNLOAD_BYTES} Б): {file_id}"
            )
        url = FILE_API.format(token=self.token, path=path)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        written = 0
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                length = (resp.headers.get("Content-Length") or "").strip()
                if length.isdigit() and int(length) > MAX_DOWNLOAD_BYTES:
                    raise TgError(
                        f"файл {length} Б больше лимита 25 МиБ "
                        f"({MAX_DOWNLOAD_BYTES} Б): {file_id}"
                    )
                with open(dest, "wb") as fh:
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_DOWNLOAD_BYTES:
                            raise TgError(
                                f"файл превысил лимит 25 МиБ ({MAX_DOWNLOAD_BYTES} Б) "
                                f"при скачивании: {file_id}"
                            )
                        fh.write(chunk)
        except TgError:
            self._drop_partial(dest)
            raise
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            TimeoutError,
            OSError,
        ) as exc:
            self._drop_partial(dest)
            raise TgError(f"не удалось скачать файл: {exc}") from exc
        return dest

    @staticmethod
    def _drop_partial(dest: str) -> None:
        """Убирает недокачанный файл, чтобы обрезанные данные не попали в обработку."""
        try:
            os.remove(dest)
        except OSError:
            pass


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Режет текст на части не длиннее limit, приоритет — границы строк.

    Гарантии: len(part) <= limit для любой части; "".join(parts) == text
    (текст не теряется и не дублируется); строка длиннее limit режется жёстко.
    """
    limit = int(limit)
    if limit <= 0:
        raise ValueError("limit должен быть положительным")
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    rest = text
    half = limit // 2
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)  # последний перевод строки в окне
        cut = cut + 1 if cut >= half else limit  # иначе режем жёстко по limit
        parts.append(rest[:cut])
        rest = rest[cut:]

    # Хвост из одних пробелов Telegram примет за пустое сообщение — подмешиваем
    # к нему конец предыдущей части, не выходя за лимит.
    while parts and rest and not rest.strip():
        prev = parts[-1]
        body = prev.rstrip()
        need = len(prev) - len(body) + 1  # хвостовые пробелы + один живой символ
        if not body or need > limit - len(rest):
            break
        parts[-1] = prev[:-need]
        rest = prev[-need:] + rest

    parts = [part for part in parts if part]
    if rest or not parts:
        parts.append(rest)
    return parts


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

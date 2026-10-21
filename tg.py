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
PHOTO_CAPTION_LIMIT = 1024  # лимит Bot API на подпись к фото
BOUNDARY = "----GoldSignalBotBoundary4f2c7a1d"


class TgError(RuntimeError):
    pass


def _is_parse_error(exc: BaseException) -> bool:
    """Telegram 400 «can't parse entities» и родственные ошибки разметки."""
    msg = str(exc).lower()
    return "parse" in msg or "entit" in msg


def _html_to_plain(text: str) -> str:
    """Снять теги и раскрыть HTML-сущности — plain-text фолбэк для send()."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _multipart(fields: dict[str, str], photo: bytes, filename: str,
               boundary: str = BOUNDARY) -> tuple[bytes, str]:
    """Собирает тело multipart/form-data: текстовые поля + один файл photo."""
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode("utf-8")
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        out += str(value).encode("utf-8") + b"\r\n"
    out += f"--{boundary}\r\n".encode("utf-8")
    out += (
        f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8")
    out += photo + b"\r\n"
    out += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _keyboard(buttons: list[list[tuple[str, str]]] | None) -> dict | None:
    """reply_markup с инлайн-кнопками: [[(подпись, callback_data), ...], ...]."""
    if not buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": str(text), "callback_data": str(data)} for text, data in row]
            for row in buttons
        ]
    }


class Tg:
    def __init__(self, token: str, timeout: int = 65):
        self.token = token
        self.timeout = timeout

    def call(self, method: str, **params):
        body = json.dumps(params).encode("utf-8")
        return self._call_raw(method, body, "application/json")

    def _call_raw(self, method: str, body: bytes, content_type: str):
        url = API.format(token=self.token, method=method)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
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
            "allowed_updates": ["message", "channel_post", "callback_query"],
            "limit": 100,
        }
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", **params)

    def send(self, chat_id, text: str, preview: bool = False, html: bool = True,
             buttons: list[list[tuple[str, str]]] | None = None):
        """Отправляет текст; html=True — parse_mode=HTML с фолбэком на plain-text."""
        common = {"chat_id": chat_id, "disable_web_page_preview": not preview}
        markup = _keyboard(buttons)
        if markup:
            common["reply_markup"] = markup
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

    # --- карточки с кнопками: нажатие приходит как callback_query

    def answer_callback(self, callback_id: str, text: str = "") -> bool:
        """Убирает «часики» на кнопке; text — короткая подсказка (до 200 символов)."""
        return bool(self.call("answerCallbackQuery", callback_query_id=callback_id,
                              text=text[:200]))

    def edit_caption(self, chat_id, message_id: int, caption: str,
                     buttons: list[list[tuple[str, str]]] | None = None, html: bool = True):
        """Меняет подпись под карточкой и её кнопки."""
        params: dict = {"chat_id": chat_id, "message_id": message_id, "caption": caption}
        markup = _keyboard(buttons)
        if markup:
            params["reply_markup"] = markup
        if html:
            try:
                return self.call("editMessageCaption", parse_mode="HTML", **params)
            except TgError as exc:
                if not _is_parse_error(exc):
                    raise
                log.warning("HTML-подпись не принята (%s) — повтор без parse_mode", exc)
                params["caption"] = _html_to_plain(caption)
        return self.call("editMessageCaption", **params)

    def edit_text(self, chat_id, message_id: int, text: str,
                  buttons: list[list[tuple[str, str]]] | None = None, preview: bool = False,
                  html: bool = True):
        """Меняет текст сообщения и его кнопки (для тех, кто писал без карточки)."""
        params: dict = {"chat_id": chat_id, "message_id": message_id, "text": text,
                        "disable_web_page_preview": not preview}
        markup = _keyboard(buttons)
        if markup:
            params["reply_markup"] = markup
        if html:
            try:
                return self.call("editMessageText", parse_mode="HTML", **params)
            except TgError as exc:
                if not _is_parse_error(exc):
                    raise
                log.warning("HTML не принят (%s) — повтор без parse_mode", exc)
                params["text"] = _html_to_plain(text)
        return self.call("editMessageText", **params)

    def send_photo(self, chat_id, path: str, caption: str = "", html: bool = True,
                   buttons: list[list[tuple[str, str]]] | None = None):
        """Отправляет PNG с подписью (multipart). Подпись длиннее лимита отбрасываем."""
        with open(path, "rb") as fh:
            blob = fh.read()
        filename = os.path.basename(path)
        fields = {"chat_id": str(chat_id)}
        if caption and len(caption) <= PHOTO_CAPTION_LIMIT:
            fields["caption"] = caption
            if html:
                fields["parse_mode"] = "HTML"
        markup = _keyboard(buttons)
        if markup:
            fields["reply_markup"] = json.dumps(markup, ensure_ascii=False)

        body, content_type = _multipart(fields, blob, filename)
        try:
            return self._call_raw("sendPhoto", body, content_type)
        except TgError as exc:
            if "parse_mode" not in fields or not _is_parse_error(exc):
                raise
            log.warning("HTML-подпись к фото отклонена Telegram (%s) — повтор без parse_mode", exc)
        fields.pop("parse_mode", None)
        body, content_type = _multipart(fields, blob, filename)
        return self._call_raw("sendPhoto", body, content_type)

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

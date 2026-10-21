"""Состояние бота: подписчики, открытая сделка, история, настройки — в JSON."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

DEFAULT_CONFIG = {
    "telegram_token": "",
    "channel_id": None,
    "display_tz": "Europe/Minsk",
    "scan_seconds": 300,
    "instruments": [],
    "risk_limits": {"daily_r": -2.0, "weekly_r": -3.0, "monthly_r": -7.0},
    "web": {"enabled": False, "host": "127.0.0.1", "port": 8080},
    "max_risk_per_symbol": 2,
    "digest_hour": 18,
}

DEFAULT_STATE = {
    "admin_id": None,
    "subscribers": [],
    "channel_id": None,
    "trades": {},
    "histories": {},
    "last_bars": {},
    "risk_paused": {},
    "started_at": None,
    "sent_ids": [],
    "instrument_overrides": {},
}


def _atomic_write(path: str, payload: dict) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


class Config:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.data = dict(DEFAULT_CONFIG)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data.update(json.load(fh))
        else:
            _atomic_write(path, self.data)

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def save(self) -> None:
        _atomic_write(self.path, self.data)

    @property
    def token(self) -> str:
        return (os.environ.get("TELEGRAM_BOT_TOKEN") or self.data.get("telegram_token") or "").strip()


class State:
    def __init__(self, path: str = STATE_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.data = dict(DEFAULT_STATE)
        self.data["subscribers"] = []
        self.data["history"] = []
        # изменяемые контейнеры не должны делить ссылку с DEFAULT_STATE
        self.data["sent_ids"] = []
        self.data["instrument_overrides"] = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (ValueError, OSError):
                pass
        if not self.data.get("started_at"):
            self.data["started_at"] = datetime.now(timezone.utc).isoformat()

    def _flush(self) -> None:
        # RLock реентрантный: вызовы из уже захваченного with self.lock не ломаются
        with self.lock:
            _atomic_write(self.path, self.data)

    # --- подписчики
    def add_subscriber(self, chat_id: int) -> bool:
        with self.lock:
            if chat_id in self.data["subscribers"]:
                return False
            self.data["subscribers"].append(chat_id)
            self._flush()
            return True

    def remove_subscriber(self, chat_id: int) -> bool:
        with self.lock:
            if chat_id not in self.data["subscribers"]:
                return False
            self.data["subscribers"].remove(chat_id)
            self._flush()
            return True

    @property
    def subscribers(self) -> list[int]:
        return list(self.data["subscribers"])

    # --- сделки по инструментам
    def _trades(self) -> dict:
        self.data.setdefault("trades", {})
        return self.data["trades"]

    def _histories(self) -> dict:
        self.data.setdefault("histories", {})
        return self.data["histories"]

    def _last_bars(self) -> dict:
        self.data.setdefault("last_bars", {})
        return self.data["last_bars"]

    def migrate_legacy(self, default_key: str = "gold") -> None:
        """Однoинструментное состояние -> многoинструментное."""
        with self.lock:
            changed = False
            trades = self._trades()
            if self.data.get("trade") and not trades:
                trades[default_key] = self.data["trade"]
                changed = True
            histories = self._histories()
            if self.data.get("history") and not histories:
                histories[default_key] = self.data["history"]
                changed = True
            last_bars = self._last_bars()
            if self.data.get("last_bar") and not last_bars:
                last_bars[default_key] = self.data["last_bar"]
                changed = True
            if changed:
                self._flush()

    def trade_for(self, key: str) -> dict | None:
        return self._trades().get(key)

    def set_trade(self, key: str, value: dict | None) -> None:
        with self.lock:
            trades = self._trades()
            if value is None:
                trades.pop(key, None)
            else:
                trades[key] = value
            self._flush()

    def close_trade(self, key: str, trade: dict) -> None:
        with self.lock:
            self._histories().setdefault(key, []).append(trade)
            self._trades().pop(key, None)
            self._flush()

    def history_for(self, key: str) -> list[dict]:
        return list(self._histories().get(key, []))

    def last_bar_for(self, key: str) -> str | None:
        return self._last_bars().get(key)

    # --- идемпотентность отправки сигналов
    def mark_sent(self, signal_id: str, limit: int = 500) -> bool:
        """True — id новый (можно отправлять), False — уже отправляли."""
        with self.lock:
            ids = self.data.get("sent_ids")
            if not isinstance(ids, list):
                ids = self.data["sent_ids"] = []
            sid = str(signal_id)
            if sid in ids:
                return False
            ids.append(sid)
            if limit > 0:
                del ids[:-limit]
            self._flush()
            return True

    def was_sent(self, signal_id: str) -> bool:
        return str(signal_id) in (self.data.get("sent_ids") or [])

    def set_last_bar(self, key: str, value: str) -> None:
        with self.lock:
            self._last_bars()[key] = value
            self._flush()

    def all_trades(self) -> dict:
        return dict(self._trades())

    def all_histories(self) -> dict:
        return dict(self._histories())

    # --- совместимость со старой одноинструментной схемой (золото)
    @property
    def trade(self) -> dict | None:
        return self.trade_for("gold")

    @trade.setter
    def trade(self, value: dict | None) -> None:
        self.set_trade("gold", value)

    @property
    def history(self) -> list[dict]:
        return self.history_for("gold")

    @property
    def last_bar(self) -> str | None:
        return self.last_bar_for("gold")

    @last_bar.setter
    def last_bar(self, value: str) -> None:
        self.set_last_bar("gold", value)

    @property
    def admin_id(self):
        return self.data.get("admin_id")

    @admin_id.setter
    def admin_id(self, value) -> None:
        with self.lock:
            self.data["admin_id"] = value
            self._flush()

    @property
    def channel_id(self):
        return self.data.get("channel_id")

    @channel_id.setter
    def channel_id(self, value) -> None:
        with self.lock:
            self.data["channel_id"] = value
            self._flush()

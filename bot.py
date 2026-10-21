"""Telegram-бот торговых сигналов: один бот — несколько инструментов.

По умолчанию:
  * XAUUSD (GC=F)  — H1, пробой канала 24 бара;
  * EURUSD         — H4, пробой канала 48 баров;
  * GBPUSD         — H4, пробой канала 24 бара.

Запуск: python bot.py [--check] [--scan-once]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import pandas as pd

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import analysis
import instruments as inst_mod
import storage
import strategy as st
import tg
from tg import Tg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "bot.log")
MATERIALS_DIR = os.path.join(BASE_DIR, "materials")
REPORT_DIR = os.path.join(BASE_DIR, "report")

_handlers = [RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3,
                                  encoding="utf-8")]
if sys.stdout:
    _handlers.insert(0, logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("bot")

COMMANDS = [
    {"command": "start", "description": "Настройки: депозит, риск, дневной стоп"},
    {"command": "signal", "description": "Обзор рынка / по инструменту"},
    {"command": "stats", "description": "Статистика стратегии"},
    {"command": "params", "description": "Правила стратегии"},
    {"command": "strategy", "description": "Сменить стратегию (админ)"},
    {"command": "risk", "description": "Риск-лимиты и текущий результат"},
    {"command": "materials", "description": "Собранные посты (админ)"},
    {"command": "status", "description": "Состояние бота и данных"},
    {"command": "unsubscribe", "description": "Отписаться"},
    {"command": "help", "description": "Справка"},
]

HELP_TEXT = (
    "📖 <b>Команды</b>\n"
    "/start — настройки: депозит, риск, дневной стоп, стратегия\n"
    "/signal — обзор по всем инструментам\n"
    "/signal gold — детально по инструменту\n"
    "/stats gold — статистика стратегии\n"
    "/params gold — правила стратегии\n"
    "/strategy gold breakout — сменить стратегию (админ)\n"
    "/risk — риск-лимиты и текущий результат\n"
    "/status — живость бота и свежесть данных\n"
    "/materials — собранные посты (админ)\n"
    "/unsubscribe — отписаться\n\n"
    "Инструменты: gold (XAUUSD H1), eurusd (H4), gbpusd (H4)."
)

STRATEGY_TEXT = (
    "⚙️ <b>Пробой канала + тренд</b>\n\n"
    "Вход: закрытие за максимумом/минимумом предыдущих N баров,\n"
    "тренд согласован (цена и EMA50 по одну сторону от EMA200),\n"
    "ADX &gt; 18, ATR выше 0.8 медианы ATR(200).\n\n"
    "Выход: стоп 1.5×ATR, тейк 2R, лимит по времени.\n"
    "Золото H1: N=24. EURUSD H4: N=48. GBPUSD H4: N=24."
)

MSNR_TEXT = (
    "⚙️ <b>Стратегия MSNR</b>\n\n"
    "Уровни — подтверждённые пивоты линейного графика (по close).\n"
    "Вход: фитиль коснулся свежего уровня, закрытие вернулось на исходную сторону.\n"
    "Стоп: за фитиль/уровень + 0.25 ATR. Цель: следующий свежий уровень или 3R.\n"
    "Фильтр: storyline (направление старшего графика).\n\n"
    "Бэктест: 257 сделок, 30% побед, PF 1.27, ожидание +0.20R."
)

MSNR_TREND_TEXT = (
    "⚙️ <b>MSNR + высокий RR</b>\n\n"
    "Дневные зоны MSNR, стоп за зоной, цель 8R, удержание до 5 суток.\n"
    "Бэктест: 68 сделок, 34% побед, PF 2.16, ожидание +0.76R.\n"
    "⚠️ Вся прибыль на покупках — это ставка на растущий тренд."
)

SMT_TEXT = (
    "⚙️ <b>SMT: расхождение золото/серебро</b> (экспериментальная)\n\n"
    "Пивоты ищутся фракталом (k баров слева и справа). Если на экстремуме золото\n"
    "обновляет предыдущий максимум, а серебро — нет (или наоборот по минимумам),\n"
    "это расхождение и вход по золоту в сторону серебра.\n\n"
    "⚠️ Бэктест H1 (730 дн.): 206 сделок, 33% побед, PF 1.16, ожидание +0.11R —\n"
    "слабее breakout (PF 1.41, +0.24R), walk-forward нестабилен. По умолчанию выключена."
)

RISK_LIMITS_DEFAULT = {"daily_r": -2.0, "weekly_r": -3.0, "monthly_r": -7.0}

# --- персональные настройки: варианты в приветственном окне
DEPOSIT_PRESETS = (5000, 10000, 25000)
RISK_PRESETS = (0.5, 1.0, 2.0)
DAY_LIMIT_PRESETS = (3.0, 5.0, 10.0)

# одна общая стратегия на всех; в списке только те, у кого есть честный бэктест
STRATEGY_CHOICES = [
    ("breakout", "🎯 Пробой канала"),
    ("msnr", "📐 MSNR отбой"),
    ("msnr_trend", "🚀 MSNR 8R"),
]

STRATEGY_PROS_CONS = {
    "breakout": ("PF 1.41, 302 сделки за 2 года — просто и стабильно, сигналов больше всех.",
                 "Винрейт ~35%, ложные пробои в узком рынке, нужен тренд."),
    "msnr": ("PF 1.27, 257 сделок, вход от уровня — короткий и понятный стоп.",
             "Винрейт 30%, сделок меньше, нужны свежие уровни."),
    "msnr_trend": ("PF 2.16, ожидание +0.76R, цель 8R — редкие, но крупные сделки.",
                   "Всего 68 сделок, вся прибыль на покупках."),
}

NY = ZoneInfo("America/New_York")


def _trading_day(ts: datetime):
    """Торговый день проп-фирмы: граница в 17:00 по Нью-Йорку (00:00 сервера)."""
    return (ts.astimezone(NY) - timedelta(hours=17)).date()


def _money(value: float) -> str:
    """Сумма в долларах с пробелами между разрядами: 5000 -> «$5 000»."""
    return f"${value:,.0f}".replace(",", " ")


def _signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}${abs(value):,.0f}".replace(",", " ")


def _parse_amount(text: str) -> float | None:
    """Разбор суммы из сообщения: «5000», «5 000», «$12k», «7,5k»."""
    cleaned = (text or "").strip().lower().replace("$", "").replace("\u00a0", "").replace(" ", "")
    factor = 1.0
    if cleaned.endswith("k"):
        factor, cleaned = 1000.0, cleaned[:-1]
    cleaned = cleaned.replace(",", ".")
    try:
        value = float(cleaned) * factor
    except ValueError:
        return None
    return value if value > 0 else None


class Bot:
    def __init__(self, config: storage.Config | None = None, state: storage.State | None = None):
        self.config = config or storage.Config()
        self.state = state or storage.State()
        self.state.migrate_legacy()
        admin = self.config.get("admin_id") or os.environ.get("ADMIN_ID")
        if admin:
            self.state.admin_id = int(admin)
        # владелец получает сигналы всегда, даже если state.json потерялся
        if self.state.admin_id and not self.state.data.get("admin_unsubscribed"):
            self.state.add_subscriber(int(self.state.admin_id))
        self.instruments = inst_mod.from_config(self.config.get("instruments"))
        if not self.config.get("instruments"):
            self._persist_instruments()
        self._apply_instrument_overrides()
        self._migrate_legacy_slots()
        self.api: Tg | None = None
        self.me: dict = {}
        self.snapshot: dict = {}
        self.web_server = None
        self._stop = threading.Event()
        self._bt_cache: dict[str, dict] = {}
        self._started = time.time()
        self._scan_lock = threading.Lock()

    # ------------------------------------------------------------ утилиты

    @property
    def tz(self) -> str:
        return self.config.get("display_tz", "Europe/Minsk")

    # совместимость: стратегия первого инструмента (золото)
    @property
    def strategy(self) -> str:
        return self.instruments[0].strategy if self.instruments else "breakout"

    @strategy.setter
    def strategy(self, value: str) -> None:
        if self.instruments:
            self.instruments[0].strategy = value

    def _targets(self) -> list[int | str]:
        targets: list[int | str] = list(self.state.subscribers)
        channel = self.state.channel_id or self.config.get("channel_id")
        if channel and channel not in targets:
            targets.append(channel)
        return targets

    def broadcast(self, text: str, preview: bool = False, photo: str | None = None,
                  skip_paused: bool = False, personalize=None) -> int:
        """Рассылает текст всем получателям; photo — картинка-карточка с подписью.

        skip_paused=True — пропустить подписчиков, у которых сработал дневной стоп.
        personalize — функция (chat_id) -> str: личная версия текста (например, % от
        депозита подписчика). Для канала берётся общий текст.
        """
        sent = 0
        for chat_id in self._targets():
            if skip_paused and isinstance(chat_id, int) and self._is_paused(chat_id):
                log.info("Подписчик %s на дневной паузе — сигнал не шлю", chat_id)
                continue
            body = text
            if personalize and isinstance(chat_id, int):
                custom = personalize(chat_id)
                if custom:
                    body = custom
            try:
                if photo and self._send_photo(chat_id, photo, body):
                    sent += 1
                else:
                    for part in tg.split_message(body):
                        self.api.send(chat_id, part, preview=preview)
                        sent += 1
                time.sleep(0.05)
            except tg.TgError as exc:
                log.warning("Не удалось отправить в %s: %s", chat_id, exc)
                msg = str(exc).lower()
                if chat_id in self.state.subscribers and any(
                        k in msg for k in ("403", "blocked", "deactivated", "chat not found")):
                    self.state.remove_subscriber(chat_id)
                    log.info("Подписчик %s удалён (бот заблокирован)", chat_id)
        return sent

    def _send_photo(self, chat_id, path: str, caption: str, buttons=None) -> bool:
        """Фото с подписью. False — не вышло (вызывающий откатится на текст).

        Подпись длиннее лимита Telegram карточка не примет — тогда текст уходит
        отдельным сообщением, чтобы сигнал не потерялся.
        """
        if not os.path.exists(path):
            return False
        try:
            self.api.send_photo(chat_id, path, caption=caption, buttons=buttons)
        except tg.TgError as exc:
            log.warning("Карточка не отправлена в %s: %s", chat_id, exc)
            return False
        if caption and len(caption) > tg.PHOTO_CAPTION_LIMIT:
            for part in tg.split_message(caption):
                self.api.send(chat_id, part, buttons=buttons)
        return True

    def _reply(self, chat_id, reply: str | dict) -> None:
        """Ответ на команду: строку — текстом, {'photo','text','buttons'} — картинкой с подписью."""
        if isinstance(reply, dict):
            photo = reply.get("photo")
            text = reply.get("text") or ""
            buttons = reply.get("buttons")
            if photo and self._send_photo(chat_id, photo, text, buttons=buttons):
                return
            parts = tg.split_message(text) if text else []
            for position, part in enumerate(parts):
                last = position == len(parts) - 1
                self.api.send(chat_id, part, buttons=buttons if last else None)
            return
        for part in tg.split_message(reply):
            self.api.send(chat_id, part)

    def _instrument(self, key: str | None) -> inst_mod.Instrument | None:
        if not key:
            return None
        return inst_mod.find(self.instruments, key)

    # ------------------------------------------------------------ персональные настройки

    def _profile(self, chat_id) -> dict:
        """Депозит, риск на сделку и дневной стоп подписчика (из state.json)."""
        return self.state.profile_for(chat_id, self.config.get("default_profile"))

    def _current_strategy(self) -> str:
        if not self.instruments:
            return st.DEFAULT_STRATEGY
        inst = self.instruments[0]
        return (inst.strategies or [inst.strategy])[0]

    def _is_paused(self, chat_id) -> bool:
        """True — у подписчика сработал дневной стоп (в % от депозита)."""
        profile = self._profile(chat_id)
        limit = abs(float(profile["day_limit"]))
        if limit <= 0:
            return False
        day = _trading_day(datetime.now(timezone.utc)).isoformat()
        pct = self.state.day_r_for(chat_id, day) * float(profile["risk"])
        return pct <= -limit

    def _settings_text(self, chat_id) -> str:
        """Приветственное окно: текущие настройки и результат дня."""
        p = self._profile(chat_id)
        deposit = float(p["deposit"])
        risk = float(p["risk"])
        day_limit = abs(float(p["day_limit"]))
        strategy = self._current_strategy()
        pros, cons = STRATEGY_PROS_CONS.get(strategy, ("", ""))

        names = ", ".join(f"{i.name} ({i.timeframe})" for i in self.instruments)
        day = _trading_day(datetime.now(timezone.utc)).isoformat()
        pct_today = self.state.day_r_for(chat_id, day) * risk
        money_today = _signed_money(deposit * pct_today / 100)
        if day_limit > 0 and self._is_paused(chat_id):
            today = (f"⏸ Дневной стоп: <b>{pct_today:+.2f}%</b> ({money_today}) — "
                     "пауза до конца дня.")
        else:
            today = (f"📊 Сегодня: <b>{pct_today:+.2f}%</b> ({money_today}) "
                     f"из −{day_limit:.2f}% лимита.")

        edge = f"\n<i>+ {tg.esc(pros)}\n− {tg.esc(cons)}</i>" if pros else ""
        return (
            f"👋 <b>Сигналы · {tg.esc(names)}</b>\n\n"
            f"🧩 Стратегия: <b>{tg.esc(self._title(strategy))}</b>{edge}\n\n"
            "<b>Ваши настройки</b>\n"
            f"💰 Депозит: <b>{_money(deposit)}</b>\n"
            f"📉 Риск на сделку: <b>{risk:.2f}%</b> · {_money(deposit * risk / 100)}\n"
            f"🛡 Дневной стоп: <b>{day_limit:.2f}%</b> · {_money(deposit * day_limit / 100)}\n"
            f"{today}\n\n"
            "Все сигналы приходят со стопом, целью и итогом <b>в % от депозита и в "
            "долларах</b>. При дневном стопе новые сигналы для вас на паузе до конца дня.\n\n"
            "<b>Выберите значения кнопками ниже</b> 👇\n"
            "<i>Не является индивидуальной инвестиционной рекомендацией.</i>"
        )

    def _settings_buttons(self, chat_id) -> list[list[tuple[str, str]]]:
        p = self._profile(chat_id)
        deposit, risk, day_limit = float(p["deposit"]), float(p["risk"]), float(p["day_limit"])
        strategy = self._current_strategy()

        def mark(value: float, current: float) -> str:
            return "✅ " if abs(value - current) < 1e-6 else ""

        rows: list[list[tuple[str, str]]] = [
            [("💰 Депозит", "noop")],
            [(f"{mark(float(d), deposit)}{_money(d)}", f"dep:{d}") for d in DEPOSIT_PRESETS],
        ]
        custom = all(abs(deposit - float(d)) > 1e-6 for d in DEPOSIT_PRESETS)
        rows.append([(f"✅ ✍️ Своя: {_money(deposit)}" if custom else "✍️ Своя сумма",
                      "dep:custom")])
        rows.append([("📉 Риск на сделку", "noop")])
        rows.append([(f"{mark(r, risk)}{r:g}%", f"risk:{r}") for r in RISK_PRESETS])
        rows.append([("🛡 Дневной стоп", "noop")])
        rows.append([(f"{mark(d, day_limit)}{d:g}%", f"day:{d}") for d in DAY_LIMIT_PRESETS])
        rows.append([(f"🧩 Стратегия: {self._title(strategy)}", "noop")])
        rows.append([(("✅ " if key == strategy else "") + label, f"strat:{key}")
                     for key, label in STRATEGY_CHOICES])
        rows.append([("♻️ Сбросить настройки", "reset")])
        return rows

    def _redraw_window(self, chat_id, message_id: int, has_photo: bool) -> None:
        """Перерисовывает окно настроек после нажатия кнопки."""
        text = self._settings_text(chat_id)
        buttons = self._settings_buttons(chat_id)
        try:
            if has_photo:
                self.api.edit_caption(chat_id, message_id, text, buttons=buttons)
            else:
                self.api.edit_text(chat_id, message_id, text, buttons=buttons)
        except tg.TgError as exc:
            log.info("Окно настроек не обновлено: %s", exc)

    def _set_strategy(self, key: str) -> None:
        """Одна общая стратегия: применяется ко всем инструментам."""
        for inst in self.instruments:
            inst.strategies = [key]
            inst.strategy = key
            # в GitHub Actions config.json пересоздаётся каждый запуск — выбор держим в state.json
            self.state.data.setdefault("instrument_overrides", {})[inst.key] = [key]
        self._persist_instruments()
        self.state._flush()
        self._bt_cache.clear()

    def handle_callback(self, cb: dict) -> None:
        """Нажатие инлайн-кнопки в окне настроек."""
        data = str(cb.get("data") or "")
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        message_id = msg.get("message_id")
        user_id = (cb.get("from") or {}).get("id", 0)
        if chat_id is None or self.api is None:
            return

        note = ""
        redraw = False
        if data == "noop":
            note = "Выберите значение кнопкой ниже"
        elif data.startswith("dep:"):
            value = data.split(":", 1)[1]
            if value == "custom":
                self.state.set_pending(chat_id, "deposit")
                note = "Введите сумму числом"
                self.api.send(chat_id, self._deposit_prompt())
            else:
                amount = _parse_amount(value) or 0.0
                if amount > 0:
                    self.state.set_profile(chat_id, deposit=amount)
                    note = f"Депозит: {_money(amount)}"
                    redraw = True
        elif data.startswith("risk:"):
            amount = _parse_amount(data.split(":", 1)[1]) or 0.0
            if 0 < amount <= 100:
                self.state.set_profile(chat_id, risk=amount)
                note = f"Риск на сделку: {amount:g}%"
                redraw = True
        elif data.startswith("day:"):
            amount = _parse_amount(data.split(":", 1)[1]) or 0.0
            if 0 < amount <= 100:
                self.state.set_profile(chat_id, day_limit=amount)
                note = f"Дневной стоп: {amount:g}%"
                redraw = True
        elif data.startswith("strat:"):
            key = data.split(":", 1)[1]
            if user_id != self.state.admin_id:
                note = "Стратегию задаёт автор канала"
            elif key not in st.CATALOG:
                note = "Нет такой стратегии"
            else:
                self._set_strategy(key)
                note = f"Стратегия: {self._title(key)}"
                redraw = True
        elif data == "reset":
            self.state.set_profile(chat_id, **storage.DEFAULT_PROFILE)
            note = "Настройки сброшены"
            redraw = True

        try:
            self.api.answer_callback(str(cb.get("id") or ""), note)
        except tg.TgError as exc:
            log.warning("answerCallbackQuery: %s", exc)

        if redraw and message_id:
            self._redraw_window(chat_id, message_id, bool(msg.get("photo")))

    def _deposit_prompt(self) -> str:
        return ("✍️ Введите сумму депозита числом, например <b>5000</b>, <b>12k</b> "
                "или <b>7,5k</b>.\nОтмена — /start.")

    def _apply_pending_text(self, chat_id, text: str) -> None:
        """Подписчик вводит «свою сумму» в ответ на приглашение кнопки."""
        field = self.state.pending_for(chat_id)
        self.state.set_pending(chat_id, None)
        amount = _parse_amount(text)
        if amount is None or not 100 <= amount <= 10_000_000:
            self.api.send(chat_id, "❌ Не понял сумму. Введите число, например <b>5000</b>.\n"
                                   "Отмена — /start.")
            return
        if field == "deposit":
            self.state.set_profile(chat_id, deposit=amount)
        try:
            self.api.send(chat_id, self._settings_text(chat_id),
                          buttons=self._settings_buttons(chat_id))
        except tg.TgError as exc:
            log.warning("Окно настроек в %s не отправлено: %s", chat_id, exc)

    def _pause_text(self, profile: dict, pct: float) -> str:
        deposit = float(profile["deposit"])
        limit = abs(float(profile["day_limit"]))
        return (
            "🛑 <b>Дневной стоп сработал</b>\n\n"
            f"Результат дня: <b>{pct:.2f}%</b> ({_signed_money(deposit * pct / 100)}) — "
            f"достигнут ваш лимит {limit:.2f}%.\n"
            "Новые сигналы для вас на паузе до конца торгового дня.\n"
            "<i>Открытые сделки продолжаю сопровождать. Настроить: /start</i>"
        )

    def _track_day_result(self, r: float, notify: bool) -> None:
        """Учитывает закрытую сделку в дневном результате каждого подписчика."""
        day = _trading_day(datetime.now(timezone.utc)).isoformat()
        for chat_id in self.state.subscribers:
            profile = self._profile(chat_id)
            limit = abs(float(profile["day_limit"]))
            total = self.state.add_day_r(chat_id, r, day)
            if limit <= 0:
                continue
            pct = total * float(profile["risk"])
            if pct > -limit or self.state.pause_notice_seen(chat_id) == day:
                continue
            self.state.set_pause_notice(chat_id, day)
            log.info("Дневной стоп у %s: %.2f%% — пауза до конца дня", chat_id, pct)
            if notify:
                try:
                    self.api.send(chat_id, self._pause_text(profile, pct))
                except tg.TgError as exc:
                    log.warning("Уведомление о паузе в %s: %s", chat_id, exc)

    # ------------------------------------------------------------ риск-лимиты

    def _risk_limits(self) -> dict:
        limits = dict(RISK_LIMITS_DEFAULT)
        limits.update(self.config.get("risk_limits") or {})
        return limits

    def _risk_status(self, inst: inst_mod.Instrument) -> dict:
        """Сумма реализованных R по инструменту (все стратегии) за день/неделю/месяц."""
        limits = self._risk_limits()
        now = datetime.now(timezone.utc)
        today = _trading_day(now)
        day = today.isoformat()
        week = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
        month = today.strftime("%Y-%m")

        sums = {"day": 0.0, "week": 0.0, "month": 0.0}
        keys = [self._slot_key(inst, s) for s in inst.slots]
        for key in keys:
            for trade in self.state.history_for(key):
                try:
                    ts = datetime.fromisoformat(str(trade["exit_time"]))
                    r = float(trade.get("r", 0.0))
                except (KeyError, TypeError, ValueError):
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                d = _trading_day(ts)
                if d.isoformat() == day:
                    sums["day"] += r
                if f"{d.isocalendar().year}-W{d.isocalendar().week:02d}" == week:
                    sums["week"] += r
                if d.strftime("%Y-%m") == month:
                    sums["month"] += r

        blocked: tuple[str, str] | None = None
        if limits.get("daily_r") is not None and sums["day"] <= limits["daily_r"]:
            blocked = ("day", day)
        elif limits.get("weekly_r") is not None and sums["week"] <= limits["weekly_r"]:
            blocked = ("week", week)
        elif limits.get("monthly_r") is not None and sums["month"] <= limits["monthly_r"]:
            blocked = ("month", month)

        return {"sums": sums, "blocked": blocked, "limits": limits}

    def _risk_message(self, inst: inst_mod.Instrument, period: str, status: dict) -> str:
        word = {"day": "дневной", "week": "недельный", "month": "месячный"}[period]
        limit_key = {"day": "daily_r", "week": "weekly_r", "month": "monthly_r"}[period]
        limit = status["limits"][limit_key]
        until = {
            "day": "до завтра",
            "week": "до следующей недели",
            "month": "до следующего месяца",
        }[period]
        return (
            f"⏸ <b>{inst.name}</b>: достигнут {word} лимит {limit:+.1f}R "
            f"(факт {status['sums'][period]:+.2f}R).\n"
            f"Новые сигналы по инструменту приостановлены {until}.\n"
            f"<i>Открытая сделка, если она есть, продолжает отслеживаться.</i>"
        )

    # ------------------------------------------------------------ сканер

    @staticmethod
    def _slot_key(inst: inst_mod.Instrument, strategy: str) -> str:
        return f"{inst.key}:{strategy}"

    def _migrate_legacy_slots(self) -> None:
        """Однoстратегийные ключи (gold) -> слоты (gold:breakout)."""
        for inst in self.instruments:
            legacy = inst.key
            target = self._slot_key(inst, inst.slots[0])
            if legacy == target:
                continue
            moved = False
            trade = self.state.trade_for(legacy)
            if trade is not None and self.state.trade_for(target) is None:
                self.state.set_trade(target, trade)
                self.state.set_trade(legacy, None)
                moved = True
            legacy_hist = self.state.history_for(legacy)
            if legacy_hist and not self.state.history_for(target):
                self.state._histories()[target] = legacy_hist
                self.state._histories()[legacy] = []
                moved = True
            legacy_bar = self.state.last_bar_for(legacy)
            if legacy_bar and not self.state.last_bar_for(target):
                self.state.set_last_bar(target, legacy_bar)
                moved = True
            if legacy_bar and self.state.last_bar_for(target):
                self.state._last_bars().pop(legacy, None)
            if moved:
                self.state._flush()
                log.info("Состояние %s перенесено в слот %s", legacy, target)

    def _apply_instrument_overrides(self) -> None:
        """Стратегии, выбранные админом, живут в state.json.

        В GitHub Actions config.json пересоздаётся из config.ci.json на каждом запуске,
        поэтому выбор из /strategy там иначе терялся бы через 10 минут.
        """
        overrides = self.state.data.get("instrument_overrides") or {}
        for inst in self.instruments:
            keys = overrides.get(inst.key)
            if isinstance(keys, list) and keys and all(k in st.CATALOG for k in keys):
                inst.strategies = [str(k) for k in keys]
                inst.strategy = inst.strategies[0]

    # насколько старым может быть последний закрытый бар, прежде чем новые входы запрещаются
    MAX_DATA_AGE = {"1h": 4 * 3600, "4h": 12 * 3600}

    def _data_fresh(self, inst: inst_mod.Instrument, df) -> bool:
        """Проверка, что фид не отдаёт устаревшие бары.

        Если последний бар старее 4 ч (H1) / 12 ч (H4), вход по нему уже неактуален:
        открытая сделка продолжает сопровождаться, но новые сигналы не выдаются.
        """
        if df.empty:
            return False
        limit = self.MAX_DATA_AGE.get(inst.timeframe, 12 * 3600)
        last = df.index[-1]
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        age = (pd.Timestamp.now(tz="UTC") - last).total_seconds()
        if age <= limit:
            return True
        log.warning("Данные %s устарели: последний бар %s, %.1f ч назад",
                    inst.key, last, age / 3600)
        return False

    def _symbol_open(self, symbol: str) -> int:
        """Сколько сделок открыто по символу во всех инструментах и стратегиях."""
        count = 0
        for inst in self.instruments:
            if inst.symbol != symbol:
                continue
            for strategy in inst.slots:
                if self.state.trade_for(self._slot_key(inst, strategy)):
                    count += 1
        return count

    def _missed_signals(self, inst: inst_mod.Instrument, strategy: str, df, key: str) -> list[dict]:
        """Сигналы, сработавшие, пока бот не работал (между последним баром и текущим)."""
        last = self.state.last_bar_for(key)
        if not last:
            return []
        try:
            last_ts = pd.Timestamp(last)
        except ValueError:
            return []
        missed_bars = df.index[(df.index > last_ts) & (df.index < df.index[-1])]
        if len(missed_bars) == 0:
            return []

        sig = st.signals_for(strategy, df, inst.params)
        out = []
        for ts in missed_bars:
            row = sig.loc[ts]
            side = "long" if bool(row["long_signal"]) else ("short" if bool(row["short_signal"]) else None)
            if side:
                out.append({"time": ts, "side": side})
        return out

    def _missed_text(self, missed: list[tuple]) -> str:
        lines = ["⚠️ <b>Пропущенные сигналы</b>", "<i>бот не работал в это время</i>", ""]
        for inst, strategy, item in missed[:8]:
            local = analysis._local(item["time"], self.tz)
            word = "покупка" if item["side"] == "long" else "продажа"
            lines.append(f"• {inst.name} {inst.timeframe} · {strategy} — {word}, {local}")
        if len(missed) > 8:
            lines.append(f"… и ещё {len(missed) - 8}")
        lines += ["", "<i>Сделки не открывались, цены входа уже неактуальны. "
                      "Это только информация.</i>"]
        return "\n".join(lines)

    def _digest_text(self) -> str:
        snap = self.snapshot or {}
        lines = [f"🗓 <b>Дайджест · {snap.get('updated', '')}</b>", ""]
        for item in snap.get("instruments", []):
            digits = item.get("digits", 2)
            trades = item.get("trades") or []
            trade_txt = (
                " · ".join(f"{t['strategy']} {t['side']} {t['r_now']:+.2f}R" for t in trades)
                if trades else "сделок нет"
            )
            risk = item.get("risk", {})
            lines.append(
                f"<b>{item['name']}</b> {item['timeframe']}: {item['price']:.{digits}f} · "
                f"{tg.esc(item.get('trend', '—'))}\n"
                f"    {trade_txt}\n"
                f"    день {risk.get('day', 0):+.1f}R · неделя {risk.get('week', 0):+.1f}R · "
                f"месяц {risk.get('month', 0):+.1f}R"
            )
        return "\n".join(lines)

    def _maybe_digest(self, notify: bool) -> None:
        hour = self.config.get("digest_hour")
        if hour is None or not notify:
            return
        # digest_hour задаётся в display_tz, а не в UTC
        now = datetime.now(timezone.utc).astimezone(ZoneInfo(self.tz))
        if now.hour != int(hour):
            return
        today = now.date().isoformat()
        if self.state.data.get("last_digest") == today:
            return
        self.state.data["last_digest"] = today
        self.state._flush()
        log.info("Отправляю дайджест за %s", today)
        self.broadcast(self._digest_text())

    def scan_once(self, notify: bool = True) -> dict:
        with self._scan_lock:
            return self._scan_once(notify)

    def _scan_once(self, notify: bool = True) -> dict:
        report: dict = {"ok": True, "signals": [], "closed": [], "errors": [], "missed": []}
        snapshot: dict = {
            "updated": analysis._local(datetime.now(timezone.utc), self.tz),
            "subscribers": len(self.state.subscribers),
            "username": self.me.get("username", "—"),
            "instruments": [],
        }
        for inst in self.instruments:
            try:
                df = analysis.load_frame(inst.symbol, timeframe=inst.timeframe)
                if df.empty or len(df) < 250:
                    continue
                fresh = self._data_fresh(inst, df)
                if not fresh:
                    report.setdefault("stale", []).append(inst.key)
                for strategy in inst.slots:
                    self._scan_slot(inst, strategy, df, notify, report, allow_new=fresh)
                snapshot["instruments"].append(self._instrument_snapshot(inst, df))
            except Exception as exc:  # noqa: BLE001 — один инструмент не должен ронять остальные
                log.exception("Ошибка сканирования %s", inst.key)
                report["ok"] = False
                report["errors"].append(f"{inst.key}: {exc}")
        self.snapshot = snapshot
        if notify:
            if report.get("missed"):
                self.broadcast(self._missed_text(report["missed"]))
            self._maybe_digest(notify)
        return report

    def _instrument_snapshot(self, inst: inst_mod.Instrument, df) -> dict:
        ms = analysis.market_state(df)
        trades = []
        for strategy in inst.slots:
            trade = self.state.trade_for(self._slot_key(inst, strategy))
            if trade:
                trades.append({
                    "strategy": strategy,
                    "side": trade["side"],
                    "entry": trade["entry"],
                    "r_now": analysis.current_risk(trade, ms["price"]),
                })
        risk = self._risk_status(inst)
        return {
            "key": inst.key,
            "name": inst.name,
            "timeframe": inst.timeframe,
            "strategies": list(inst.slots),
            "digits": inst.digits,
            "price": ms["price"],
            "trend": ms["trend"],
            "last_bar": analysis._local(df.index[-1], self.tz),
            "trades": trades,
            "risk": {
                "day": risk["sums"]["day"],
                "week": risk["sums"]["week"],
                "month": risk["sums"]["month"],
                "blocked": bool(risk["blocked"]),
            },
        }

    def start_web(self) -> None:
        cfg = self.config.get("web") or {}
        if not cfg.get("enabled"):
            return
        from web import start_server

        host = cfg.get("host", "127.0.0.1")
        port = int(cfg.get("port", 8080))
        try:
            self.web_server = start_server(lambda: self.snapshot, host, port)
            log.info("Веб-панель: http://%s:%s", host, port)
        except OSError as exc:
            log.warning("Веб-панель не запустилась: %s", exc)

    @staticmethod
    def _title(strategy: str) -> str:
        try:
            meta, _ = st.get_strategy(strategy)
            return meta.title
        except KeyError:
            return strategy

    # ------------------------------------------------------------ карточки

    @staticmethod
    def _card() -> object | None:
        """Модуль карточек; None — если Pillow не установлен (шлём текстом)."""
        try:
            import card
        except ImportError:
            log.info("Pillow не установлен — оформление идёт текстом")
            return None
        return card

    def _signal_card(self, inst: inst_mod.Instrument, signal: dict, df) -> str | None:
        module = self._card()
        if not module:
            return None
        path = os.path.join(REPORT_DIR, f"signal_{inst.key}.png")
        try:
            return module.render_signal_card(
                signal, df, inst.name, inst.timeframe, inst.digits, self.tz, path)
        except Exception:  # noqa: BLE001 — картинка не должна ломать отправку сигнала
            log.exception("Карточка сигнала %s не нарисована", inst.key)
            return None

    def _close_card(self, inst: inst_mod.Instrument, trade: dict, result: dict) -> str | None:
        module = self._card()
        if not module:
            return None
        path = os.path.join(REPORT_DIR, f"close_{inst.key}.png")
        try:
            return module.render_result_card(
                trade, result, inst.name, inst.timeframe, inst.digits, self.tz, path)
        except Exception:  # noqa: BLE001
            log.exception("Карточка закрытия %s не нарисована", inst.key)
            return None

    def _welcome_card(self) -> str | None:
        module = self._card()
        if not module:
            return None
        try:
            return module.render_welcome_card(self.instruments, os.path.join(REPORT_DIR, "welcome.png"))
        except Exception:  # noqa: BLE001
            log.exception("Приветственная карточка не нарисована")
            return None

    def _scan_slot(self, inst: inst_mod.Instrument, strategy: str, df, notify: bool,
                   report: dict, allow_new: bool = True) -> None:
        key = self._slot_key(inst, strategy)
        max_parallel = int(self.config.get("max_parallel", 2))

        trade = self.state.trade_for(key)
        if trade:
            result = analysis.check_open_trade(trade, df)
            if result:
                closed = {**trade, **result, "status": "closed"}
                self.state.close_trade(key, closed)
                report["closed"].append((key, result))
                log.info("Сделка %s закрыта: %s %.2fR", key, result["reason"], result["r"])
                self._track_day_result(result["r"], notify)
                if notify:
                    title = self._title(strategy)
                    card = self._close_card(inst, trade, result)
                    self.broadcast(
                        analysis.format_close(trade, result, inst.name, self.tz, inst.digits,
                                              strategy_title=title),
                        photo=card,
                        personalize=lambda cid: analysis.format_close(
                            trade, result, inst.name, self.tz, inst.digits,
                            strategy_title=title, profile=self._profile(cid)),
                    )
            return

        if not allow_new:  # фид устарел — новые входы не открываем
            return

        bar_key = df.index[-1].isoformat()
        if self.state.last_bar_for(key) == bar_key:
            return

        missed = self._missed_signals(inst, strategy, df, key)
        if missed:
            report.setdefault("missed", []).extend((inst, strategy, m) for m in missed)

        self.state.set_last_bar(key, bar_key)

        open_now = [s for s in inst.slots if self.state.trade_for(self._slot_key(inst, s))]
        if len(open_now) >= max_parallel:
            return

        # общий риск по символу: не больше max_risk_per_symbol одновременных сделок
        max_symbol = int(self.config.get("max_risk_per_symbol", 2))
        if self._symbol_open(inst.symbol) >= max_symbol:
            log.info("Лимит риска по %s: уже %s сделок, пропускаю %s",
                     inst.symbol, self._symbol_open(inst.symbol), key)
            return

        risk = self._risk_status(inst)
        if risk["blocked"]:
            period, period_key = risk["blocked"]
            paused = self.state.data.setdefault("risk_paused", {})
            if paused.get(inst.key) != period_key:
                paused[inst.key] = period_key
                self.state._flush()
                log.info("Риск-лимит %s (%s): новые входы остановлены", inst.key, period)
                if notify:
                    self.broadcast(self._risk_message(inst, period, risk))
            return

        signal = analysis.detect_signal(
            df, strategy, inst.params, max_bars=inst.max_bars, spread=inst.spread
        )
        if not signal:
            return
        signal.update({"instrument": inst.key, "strategy": strategy,
                       "slot": key, "status": "open"})
        signal["detected_at"] = datetime.now(timezone.utc).isoformat()
        self.state.set_trade(key, signal)
        report["signals"].append((key, signal))
        # id сигнала (side-бар) не содержит инструмент: три слота на одном баре дали бы один id
        dedupe_key = f"{key}:{signal['id']}"
        if notify and self.state.mark_sent(dedupe_key):
            title = self._title(strategy)
            card = self._signal_card(inst, signal, df)
            sent = self.broadcast(
                analysis.format_signal(signal, inst.name, self.tz, inst.timeframe, inst.digits,
                                       strategy_title=title),
                photo=card,
                skip_paused=True,
                personalize=lambda cid: analysis.format_signal(
                    signal, inst.name, self.tz, inst.timeframe, inst.digits,
                    strategy_title=title, profile=self._profile(cid)),
            )
            log.info("Сигнал %s/%s %s @ %.4f -> %s получателей",
                     inst.key, strategy, signal["side"], signal["entry"], sent)
        elif notify:
            log.info("Сигнал %s уже отправлялся — повторно не шлю", dedupe_key)

    def scanner_loop(self) -> None:
        interval = int(self.config.get("scan_seconds", 300))
        log.info("Сканер запущен, интервал %s c", interval)
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001
                log.exception("Ошибка в сканере")
            self._stop.wait(interval)

    # ------------------------------------------------------------ сбор материалов

    @staticmethod
    def _material_files() -> list[str]:
        if not os.path.isdir(MATERIALS_DIR):
            return []
        return [
            os.path.join(root, f)
            for root, _, files in os.walk(MATERIALS_DIR)
            for f in files
            if not f.endswith(".meta.json")
        ]

    def save_material(self, msg: dict) -> str | None:
        """Пересланный пост от админа или пост из канала, где бот админ — в materials/."""
        user_id = (msg.get("from") or {}).get("id", 0)
        chat = msg.get("chat") or {}
        is_channel = chat.get("type") == "channel"
        if not is_channel and (user_id != self.state.admin_id or chat.get("type") != "private"):
            return None

        text = msg.get("text") or msg.get("caption") or ""
        photo = msg.get("photo") or []
        doc = msg.get("document")
        if not text and not photo and not doc:
            return None

        when = datetime.fromtimestamp(int(msg.get("date") or time.time()), tz=timezone.utc)
        folder = os.path.join(MATERIALS_DIR, when.strftime("%Y-%m-%d"))
        os.makedirs(folder, exist_ok=True)
        base = f"{when.strftime('%H%M%S')}_{msg.get('message_id', int(time.time()))}"
        saved: list[str] = []

        if text:
            with open(os.path.join(folder, f"{base}.txt"), "w", encoding="utf-8") as fh:
                fh.write(text)
            saved.append(f"{base}.txt")

        if photo:
            dest = os.path.join(folder, f"{base}.jpg")
            try:
                self.api.download(photo[-1]["file_id"], dest)
                saved.append(f"{base}.jpg")
            except tg.TgError as exc:
                log.warning("Фото не скачалось: %s", exc)

        if doc:
            ext = os.path.splitext(doc.get("file_name") or "")[1] or ".bin"
            dest = os.path.join(folder, f"{base}{ext}")
            try:
                self.api.download(doc["file_id"], dest)
                saved.append(f"{base}{ext}")
            except tg.TgError as exc:
                log.warning("Файл не скачался: %s", exc)

        if not saved:
            return None

        origin = msg.get("forward_origin") or {}
        source = (
            (origin.get("chat") or {}).get("title")
            or (origin.get("sender_user") or {}).get("first_name")
            or (chat.get("title") if is_channel else "")
        )
        meta = {
            "date": when.isoformat(),
            "message_id": msg.get("message_id"),
            "source": source,
            "text": text,
            "files": saved,
        }
        with open(os.path.join(folder, f"{base}.meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

        total = len(self._material_files())
        return f"✅ Сохранено: {', '.join(saved)}\nВсего материалов: {total}"

    # ------------------------------------------------------------ команды

    def handle_command(self, chat_id: int, user_id: int, text: str,
                       username: str = "") -> str | dict | None:
        parts = text.strip().split()
        cmd = parts[0][1:].split("@")[0].lower() if parts else ""
        args = parts[1:]

        if cmd == "start":
            self.state.set_pending(chat_id, None)
            added = self.state.add_subscriber(chat_id)
            if not self.state.admin_id:
                self.state.admin_id = user_id  # первый подписчик становится админом
            if chat_id == self.state.admin_id and self.state.data.get("admin_unsubscribed"):
                self.state.data["admin_unsubscribed"] = False
                self.state._flush()
            head = f"👋 Привет{', ' + username if username else ''}!\n\n" if added else ""
            return {
                "photo": self._welcome_card(),
                "text": head + self._settings_text(chat_id),
                "buttons": self._settings_buttons(chat_id),
            }

        if cmd == "help":
            return HELP_TEXT

        if cmd == "subscribe":
            added = self.state.add_subscriber(chat_id)
            return "✅ Подписка активна." if added else "Вы уже подписаны."

        if cmd in {"stop", "unsubscribe"}:
            removed = self.state.remove_subscriber(chat_id)
            if chat_id == self.state.admin_id:
                # чтобы автоподписка владельца не отменяла явный /unsubscribe
                self.state.data["admin_unsubscribed"] = True
                self.state._flush()
            return "Подписка отключена. Вернуться: /start" if removed else "Вы не были подписаны."

        if cmd == "signal":
            inst = self._instrument(args[0] if args else None)
            if args and not inst:
                return f"Нет такого инструмента. Доступны: {self._keys()}"
            return self._signal_text(inst)

        if cmd == "stats":
            inst = self._instrument(args[0] if args else None)
            if args and not inst:
                return f"Нет такого инструмента. Доступны: {self._keys()}"
            if inst:
                return self._stats_text(inst)
            return "\n\n".join(self._stats_text(i) for i in self.instruments)

        if cmd == "params":
            inst = self._instrument(args[0] if args else None) or self.instruments[0]
            if inst.strategy == "msnr":
                return MSNR_TEXT
            if inst.strategy == "msnr_trend":
                return MSNR_TREND_TEXT
            if inst.strategy == "smt":
                return SMT_TEXT
            return STRATEGY_TEXT

        if cmd == "strategy":
            if user_id != self.state.admin_id:
                return "⛔️ Команда только для админа."
            available = ", ".join(st.CATALOG)
            if not args:
                lines = [f"<b>{i.name}</b> ({i.timeframe}): {', '.join(i.slots)}" for i in self.instruments]
                return (
                    "Текущие стратегии:\n" + "\n".join(lines) +
                    f"\n\nДоступны: {available}\n"
                    "Сменить: /strategy eurusd channel\n"
                    "Несколько параллельно: /strategy gold breakout asian"
                )
            if len(args) == 1 and args[0].lower() in st.CATALOG:
                inst = self.instruments[0]
                keys = [args[0].lower()]
            else:
                inst = self._instrument(args[0])
                if not inst:
                    return f"Нет такого инструмента. Доступны: {self._keys()}"
                if len(args) == 1:
                    return f"{inst.name}: стратегии <b>{', '.join(inst.slots)}</b>"
                keys = [k.lower() for k in args[1:] if k]
            bad = [k for k in keys if k not in st.CATALOG]
            if bad:
                return f"Нет такой стратегии: {', '.join(bad)}. Доступны: {available}"
            inst.strategies = keys
            inst.strategy = keys[0]
            self._persist_instruments()
            # в GitHub Actions config.json пересоздаётся каждый запуск — держим выбор в state.json
            self.state.data.setdefault("instrument_overrides", {})[inst.key] = list(keys)
            self.state._flush()
            for cache_key in [k for k in self._bt_cache if k.startswith(f"{inst.key}:")]:
                self._bt_cache.pop(cache_key, None)
            titles = ", ".join(self._title(k) for k in keys)
            return f"✅ {inst.name}: стратегии — <b>{titles}</b>"

        if cmd == "risk":
            lines = ["🛡 <b>Риск-лимиты</b>"]
            for inst in self.instruments:
                status = self._risk_status(inst)
                lim, sums = status["limits"], status["sums"]
                state_txt = "⏸ пауза" if status["blocked"] else "работаем"
                lines.append(
                    f"• <b>{inst.name}</b>: день {sums['day']:+.1f}/{lim['daily_r']:+.1f}R · "
                    f"неделя {sums['week']:+.1f}/{lim['weekly_r']:+.1f}R · "
                    f"месяц {sums['month']:+.1f}/{lim['monthly_r']:+.1f}R — {state_txt}"
                )
            return "\n".join(lines)

        if cmd == "status":
            lines = ["🩺 <b>Состояние</b>", f"Бот: @{self.me.get('username', '—')}"]
            for inst in self.instruments:
                bar = "—"
                try:
                    df = analysis.load_frame(inst.symbol, max_age=60, timeframe=inst.timeframe)
                    bar = analysis._local(df.index[-1], self.tz)
                except Exception as exc:  # noqa: BLE001
                    bar = f"ошибка: {exc}"
                opens = [(s, self.state.trade_for(self._slot_key(inst, s))) for s in inst.slots]
                opens = [(s, t) for s, t in opens if t]
                trade_txt = (
                    ", ".join(f"{s}: {t['side']} @ {t['entry']:.{inst.digits}f}" for s, t in opens)
                    if opens else "нет"
                )
                lines.append(f"• <b>{inst.name}</b> {inst.timeframe}: {bar} · {trade_txt}")
            uptime = int(time.time() - self._started)
            lines += [
                f"Аптайм: {uptime // 3600} ч {uptime % 3600 // 60} мин",
                f"Подписчиков: {len(self.state.subscribers)}",
            ]
            return "\n".join(lines)

        if cmd == "materials":
            if user_id != self.state.admin_id:
                return "⛔️ Команда только для админа."
            files = self._material_files()
            if not files:
                return (
                    "📚 Материалов пока нет.\n"
                    "Перешлите мне посты из канала (текст, скриншоты, PDF) — сохраню в materials/."
                )
            files.sort(key=os.path.getmtime, reverse=True)
            tail = "\n".join(f"• {os.path.relpath(p, MATERIALS_DIR)}" for p in files[:8])
            return f"📚 Материалов: {len(files)}\n{tail}"

        if cmd == "channel":
            if user_id != self.state.admin_id:
                return "⛔️ Команда только для админа."
            if not args:
                return f"Текущий канал: {self.state.channel_id or 'не задан'}"
            value = args[0]
            if value.lower() in {"off", "none", "-"}:
                self.state.channel_id = None
                return "Канал отключён."
            self.state.channel_id = value
            return f"Канал установлен: {value}. Добавьте бота админом канала."

        return None

    # ------------------------------------------------------------ тексты

    def _keys(self) -> str:
        return ", ".join(i.key for i in self.instruments)

    def _persist_instruments(self) -> None:
        self.config.data["instruments"] = [i.to_dict() for i in self.instruments]
        self.config.save()

    def _signal_text(self, inst: inst_mod.Instrument | None) -> str:
        if inst:
            df = analysis.load_frame(inst.symbol, timeframe=inst.timeframe)
            open_trade = None
            for s in inst.slots:
                open_trade = self.state.trade_for(self._slot_key(inst, s))
                if open_trade:
                    break
            state = {"trade": open_trade}
            return analysis.format_state(
                df, state, inst.name, self.tz, inst.slots[0],
                timeframe=inst.timeframe, params=inst.params, digits=inst.digits,
            )
        lines = ["📊 <b>Обзор</b>", ""]
        for i in self.instruments:
            try:
                df = analysis.load_frame(i.symbol, timeframe=i.timeframe)
                s = analysis.market_state(df)
                opens = [self.state.trade_for(self._slot_key(i, st_name)) for st_name in i.slots]
                opens = [t for t in opens if t]
                if opens:
                    tail = " · " + ", ".join(
                        f"{t['strategy']} {t['side'].upper()} {analysis.current_risk(t, s['price']):+.2f}R"
                        for t in opens
                    )
                else:
                    tail = " · сделок нет"
                lines.append(
                    f"<b>{i.name}</b> {i.timeframe}: {s['price']:.{i.digits}f} · "
                    f"{tg.esc(s['trend'])}{tail}"
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"<b>{i.name}</b>: ошибка данных ({exc})")
        lines += ["", f"Детально: /signal {self.instruments[0].key}"]
        return "\n".join(lines)

    def _backtest_for(self, inst: inst_mod.Instrument, strategy: str) -> dict:
        """Бэктест слота с теми же параметрами, с которыми он работает в live."""
        key = self._slot_key(inst, strategy)
        if key not in self._bt_cache:
            df = analysis.load_frame(inst.symbol, timeframe=inst.timeframe)
            self._bt_cache[key] = analysis.backtest_summary(
                df, strategy, inst.params, spread=inst.spread, max_bars=inst.max_bars
            )
        return self._bt_cache[key]

    def _stats_text(self, inst: inst_mod.Instrument) -> str:
        history = [t for s in inst.slots for t in self.state.history_for(self._slot_key(inst, s))]
        title = f"{inst.name} [{', '.join(inst.slots)}]"
        multiple = len(inst.slots) > 1
        blocks = []
        for position, strategy in enumerate(inst.slots):
            name = f"{title} · {strategy}" if multiple else title
            blocks.append(analysis.format_stats(
                self._backtest_for(inst, strategy),
                history,
                name,
                inst.timeframe,
                show_live=position == 0,
            ))
        return "\n\n".join(blocks)

    # ------------------------------------------------------------ цикл

    def setup(self) -> None:
        token = self.config.token
        if not token:
            token = self._ask_token()
        self.api = Tg(token)
        self.me = self.api.get_me()
        log.info("Бот: @%s (%s)", self.me.get("username"), self.me.get("first_name"))
        self.api.delete_webhook()
        try:
            self.api.set_commands(COMMANDS)
        except tg.TgError as exc:
            log.warning("setMyCommands: %s", exc)

    def _ask_token(self) -> str:
        if sys.stdout:
            print("Токен бота от @BotFather (вида 123456789:AA...):")
        try:
            token = input("> ").strip() if sys.stdin and sys.stdin.isatty() else ""
        except (EOFError, KeyboardInterrupt, RuntimeError):
            token = ""
        if not token:
            raise SystemExit(
                "Не задан токен.\n"
                "1) Создайте бота у @BotFather, скопируйте токен.\n"
                "2) Вставьте его в config.json в поле \"telegram_token\" "
                "или задайте переменную окружения TELEGRAM_BOT_TOKEN.\n"
                "3) Запустите: python bot.py"
            )
        self.config.data["telegram_token"] = token
        self.config.save()
        return token

    def handle_update(self, upd: dict) -> None:
        """Обрабатывает одно обновление Telegram (команда, материал, пост канала, кнопка)."""
        if "callback_query" in upd:
            try:
                self.handle_callback(upd["callback_query"])
            except Exception:  # noqa: BLE001 — нажатие кнопки не должно ронять цикл
                log.exception("Ошибка обработки нажатия кнопки")
            return

        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if "id" not in chat:
            return
        text = msg.get("text") or ""
        in_channel = chat.get("type") == "channel"

        if not text.startswith("/"):
            if not in_channel and self.state.pending_for(chat["id"]):
                try:
                    self._apply_pending_text(chat["id"], text)
                except tg.TgError as exc:
                    log.warning("Ввод суммы в %s не обработан: %s", chat["id"], exc)
                return
            try:
                note = self.save_material(msg)
            except Exception:  # noqa: BLE001
                log.exception("Ошибка сохранения материала")
                note = None
            if note and not in_channel:
                try:
                    self.api.send(chat["id"], note)
                except tg.TgError as exc:
                    log.warning("Подтверждение не доставлено: %s", exc)
            return

        try:
            reply = self.handle_command(
                chat["id"], (msg.get("from") or {}).get("id", 0), text,
                (msg.get("from") or {}).get("first_name", ""),
            )
        except Exception:  # noqa: BLE001
            log.exception("Ошибка обработки команды %s", text)
            reply = "⚠️ Внутренняя ошибка, попробуйте позже."
        if reply:
            try:
                self._reply(chat["id"], reply)
            except tg.TgError as exc:
                log.warning("Ответ в %s не доставлен: %s", chat["id"], exc)

    def run_once(self) -> dict:
        """Один проход для запуска по расписанию (cron / GitHub Actions)."""
        self.setup()
        log.info("Подписчиков: %s, админ: %s, инструментов: %s",
                 len(self.state.subscribers), self.state.admin_id, len(self.instruments))
        report = self.scan_once(notify=True)
        try:
            updates = self.api.get_updates(self.state.data.get("update_offset"), timeout=0)
        except tg.TgError as exc:
            log.warning("getUpdates: %s", exc)
            updates = []
        for upd in updates:
            self.state.data["update_offset"] = upd["update_id"] + 1
            self.state._flush()
            self.handle_update(upd)
        log.info("Один проход завершён: сигналов %s, закрытий %s",
                 len(report["signals"]), len(report["closed"]))
        return report

    def run(self) -> None:
        self.setup()
        log.info("Инструменты: %s", ", ".join(
            f"{i.key}/{i.timeframe}[{','.join(i.slots)}]" for i in self.instruments))
        self.start_web()
        thread = threading.Thread(target=self.scanner_loop, daemon=True)
        thread.start()
        try:
            self.scan_once()
        except Exception:  # noqa: BLE001
            log.exception("Первый проход сканера")

        log.info("Слушаю команды (Ctrl+C для выхода)")
        offset = self.state.data.get("update_offset")
        while not self._stop.is_set():
            try:
                updates = self.api.get_updates(offset, timeout=50)
            except tg.TgError as exc:
                log.warning("getUpdates: %s", exc)
                time.sleep(5)
                continue
            except KeyboardInterrupt:
                break
            except Exception:  # noqa: BLE001 — сеть/таймауты не должны ронять бота
                log.exception("getUpdates: неожиданная ошибка")
                time.sleep(10)
                continue

            for upd in updates:
                offset = upd["update_id"] + 1
                self.state.data["update_offset"] = offset
                self.state._flush()
                self.handle_update(upd)

        self._stop.set()
        thread.join(timeout=5)
        log.info("Остановлено")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram-бот сигналов")
    parser.add_argument("--check", action="store_true", help="проверить токен и данные и выйти")
    parser.add_argument("--scan-once", action="store_true", help="один проход сканера без Telegram")
    parser.add_argument("--once", action="store_true",
                        help="один проход: сигналы + обработка команд, затем выход (для cron)")
    args = parser.parse_args()

    bot = Bot()

    if args.once:
        bot.run_once()
        return

    if args.scan_once:
        bot.api = Tg(bot.config.token or "0:0")
        report = bot.scan_once(notify=False)
        print(report)
        return

    if args.check:
        bot.setup()
        print(f"Бот: @{bot.me.get('username')}")
        for inst in bot.instruments:
            df = analysis.load_frame(inst.symbol, timeframe=inst.timeframe)
            s = analysis.market_state(df)
            print(f"  {inst.name:8s} {inst.timeframe}: {s['price']:.{inst.digits}f}, "
                  f"баров {len(df)}, стратегия {inst.strategy}")
        print(f"Подписчиков: {len(bot.state.subscribers)}")
        return

    try:
        bot.run()
    except KeyboardInterrupt:
        bot._stop.set()
        log.info("Прервано пользователем")


if __name__ == "__main__":
    main()

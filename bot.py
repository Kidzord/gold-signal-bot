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
from datetime import datetime, timezone

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

_handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
if sys.stdout:
    _handlers.insert(0, logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("bot")

COMMANDS = [
    {"command": "start", "description": "Подписаться на сигналы"},
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
    "/start — подписаться на сигналы\n"
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

RISK_LIMITS_DEFAULT = {"daily_r": -2.0, "weekly_r": -3.0, "monthly_r": -7.0}


class Bot:
    def __init__(self, config: storage.Config | None = None, state: storage.State | None = None):
        self.config = config or storage.Config()
        self.state = state or storage.State()
        self.state.migrate_legacy()
        self.instruments = inst_mod.from_config(self.config.get("instruments"))
        if not self.config.get("instruments"):
            self._persist_instruments()
        self._migrate_legacy_slots()
        self.api: Tg | None = None
        self.me: dict = {}
        self.snapshot: dict = {}
        self.web_server = None
        self._stop = threading.Event()
        self._bt_cache: dict[str, dict] = {}
        self._started = time.time()

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

    def broadcast(self, text: str, preview: bool = False) -> int:
        sent = 0
        for chat_id in self._targets():
            try:
                for part in tg.split_message(text):
                    self.api.send(chat_id, part, preview=preview)
                    sent += 1
                time.sleep(0.05)
            except tg.TgError as exc:
                log.warning("Не удалось отправить в %s: %s", chat_id, exc)
        return sent

    def _instrument(self, key: str | None) -> inst_mod.Instrument | None:
        if not key:
            return None
        return inst_mod.find(self.instruments, key)

    # ------------------------------------------------------------ риск-лимиты

    def _risk_limits(self) -> dict:
        limits = dict(RISK_LIMITS_DEFAULT)
        limits.update(self.config.get("risk_limits") or {})
        return limits

    def _risk_status(self, inst: inst_mod.Instrument) -> dict:
        """Сумма реализованных R по инструменту (все стратегии) за день/неделю/месяц."""
        limits = self._risk_limits()
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        month = now.strftime("%Y-%m")

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
                if ts.date().isoformat() == day:
                    sums["day"] += r
                if f"{ts.isocalendar().year}-W{ts.isocalendar().week:02d}" == week:
                    sums["week"] += r
                if ts.strftime("%Y-%m") == month:
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
        limit = status["limits"][f"{period}_r"]
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

    def scan_once(self, notify: bool = True) -> dict:
        report: dict = {"ok": True, "signals": [], "closed": [], "errors": []}
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
                for strategy in inst.slots:
                    self._scan_slot(inst, strategy, df, notify, report)
                snapshot["instruments"].append(self._instrument_snapshot(inst, df))
            except Exception as exc:  # noqa: BLE001 — один инструмент не должен ронять остальные
                log.exception("Ошибка сканирования %s", inst.key)
                report["ok"] = False
                report["errors"].append(f"{inst.key}: {exc}")
        self.snapshot = snapshot
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

    def _scan_slot(self, inst: inst_mod.Instrument, strategy: str, df, notify: bool,
                   report: dict) -> None:
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
                if notify:
                    self.broadcast(analysis.format_close(
                        trade, result, inst.name, self.tz, inst.digits,
                        strategy_title=self._title(strategy)))
            return

        bar_key = df.index[-1].isoformat()
        if self.state.last_bar_for(key) == bar_key:
            return
        self.state.set_last_bar(key, bar_key)

        open_now = [s for s in inst.slots if self.state.trade_for(self._slot_key(inst, s))]
        if len(open_now) >= max_parallel:
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
        if notify:
            sent = self.broadcast(analysis.format_signal(
                signal, inst.name, self.tz, inst.timeframe, inst.digits,
                strategy_title=self._title(strategy)))
            log.info("Сигнал %s/%s %s @ %.4f -> %s получателей",
                     inst.key, strategy, signal["side"], signal["entry"], sent)

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

    def handle_command(self, chat_id: int, user_id: int, text: str, username: str = "") -> str | None:
        parts = text.strip().split()
        cmd = parts[0][1:].split("@")[0].lower() if parts else ""
        args = parts[1:]

        if self.state.admin_id is None and cmd in {"start", "help"}:
            self.state.admin_id = user_id
            log.info("Админ назначен: %s (%s)", user_id, username)

        if cmd == "start":
            added = self.state.add_subscriber(chat_id)
            head = f"👋 Привет{', ' + username if username else ''}!\n\n" if added else "Вы уже подписаны.\n\n"
            return head + self._welcome()

        if cmd == "help":
            return HELP_TEXT

        if cmd == "subscribe":
            added = self.state.add_subscriber(chat_id)
            return "✅ Подписка активна." if added else "Вы уже подписаны."

        if cmd in {"stop", "unsubscribe"}:
            removed = self.state.remove_subscriber(chat_id)
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
            self._bt_cache.pop(inst.key, None)
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

    def _stats_text(self, inst: inst_mod.Instrument) -> str:
        if inst.key not in self._bt_cache:
            df = analysis.load_frame(inst.symbol, timeframe=inst.timeframe)
            self._bt_cache[inst.key] = analysis.backtest_summary(
                df, inst.slots[0], inst.params, spread=inst.spread, max_bars=inst.max_bars
            )
        history = [t for s in inst.slots for t in self.state.history_for(self._slot_key(inst, s))]
        title = f"{inst.name} [{', '.join(inst.slots)}]"
        return analysis.format_stats(self._bt_cache[inst.key], history, title, inst.timeframe)

    def _welcome(self) -> str:
        names = ", ".join(f"{i.name} ({i.timeframe})" for i in self.instruments)
        return (
            f"Я присылаю сигналы по: {names}.\n\n"
            "<b>Как это работает</b>\n"
            "• пробой канала в направлении тренда (ADX + ATR фильтры);\n"
            "• стоп 1.5×ATR, тейк 2R, лимит по времени;\n"
            "• проверяю закрытие каждого бара, сигналов 2–4 в неделю;\n"
            "• присылаю и вход, и закрытие сделки.\n\n"
            "<b>Бэктест:</b> золото H1 — 302 сделки, PF 1.41; "
            "EURUSD H4 — 89 сделок, PF 1.33; GBPUSD H4 — 107 сделок, PF 1.40.\n\n"
            "Команды: /signal, /stats, /params, /status, /unsubscribe\n\n"
            "<i>Это не инвестиционная рекомендация: сигналы не учитывают ваш депозит и риск-профиль.</i>"
        )

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
        """Обрабатывает одно обновление Telegram (команда, материал, пост канала)."""
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if "id" not in chat:
            return
        text = msg.get("text") or ""
        in_channel = chat.get("type") == "channel"

        if not text.startswith("/"):
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
                self.api.send(chat["id"], reply)
            except tg.TgError as exc:
                log.warning("Ответ в %s не доставлен: %s", chat["id"], exc)

    def run_once(self) -> dict:
        """Один проход для запуска по расписанию (cron / GitHub Actions)."""
        self.setup()
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

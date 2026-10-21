"""Карточки для Telegram: свечной график сигнала и текстовые карточки-обложки.

Требуется Pillow. Если библиотеки нет, импорт модуля упадёт, а вызывающий код
откатится на обычный текст — бот из-за картинок падать не должен.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

import analysis

W, H = 1080, 640
HEADER_H = 92
FOOTER_H = 78
PAD_L, PAD_R = 64, 40

BG = (15, 18, 24)
PANEL = (25, 30, 40)
GRID = (36, 42, 54)
TEXT = (232, 236, 244)
MUTED = (138, 148, 166)
UP = (38, 178, 116)
DOWN = (228, 78, 78)
ENTRY = (92, 160, 220)


def _font(size: int, bold: bool = False):
    """Шрифт с кириллицей: Windows (Segoe UI), Linux (DejaVu/Liberation)."""
    win = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    lin = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ) if bold else (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )
    for path in [rf"C:\Windows\Fonts\{n}" for n in win] + list(lin):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _ellipsis(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    """Обрезает строку по ширине, добавляя многоточие."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    cut = text
    while cut and draw.textlength(cut + "…", font=font) > max_w:
        cut = cut[:-1]
    return cut + "…"


def _text_card(title: str, subtitle: str, lines: list[str], out_path: str,
               accent=UP, headline: str = "") -> str:
    """Обложка/итог: заголовок, подзаголовок и список строк."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_title, f_sub, f_body, f_head = _font(46, True), _font(22), _font(24), _font(64, True)

    d.rectangle([0, 0, W, 6], fill=accent)
    d.text((PAD_L, 54), title, font=f_title, fill=TEXT)
    if subtitle:
        d.text((PAD_L, 116), _ellipsis(d, subtitle, f_sub, W - PAD_L - PAD_R), font=f_sub, fill=MUTED)

    y = 190
    if headline:
        d.text((PAD_L, y), headline, font=f_head, fill=accent)
        y += 96
    for line in lines:
        d.text((PAD_L, y), _ellipsis(d, line, f_body, W - PAD_L - PAD_R), font=f_body, fill=TEXT)
        y += 40

    d.text((PAD_L, H - 46), "не инвестиционная рекомендация", font=_font(18), fill=MUTED)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path)
    return out_path


def render_welcome_card(instruments: list, out_path: str) -> str:
    """Приветственная обложка: по каким инструментам шлём сигналы и как это работает."""
    lines = [f"{i.name} — {i.timeframe.upper()}, {', '.join(i.slots)}" for i in instruments]
    lines += [
        "",
        "Вход: пробой канала в сторону тренда",
        "Риск на сделку: стоп 1.5×ATR, тейк 2R",
        "Пишу и вход, и закрытие сделки",
    ]
    return _text_card("GOLD SIGNAL BOT", "сигналы по золоту и форексу", lines, out_path, accent=ENTRY)


def render_result_card(trade: dict, result: dict, name: str, timeframe: str,
                       digits: int, tz_name: str, out_path: str) -> str:
    """Карточка закрытия сделки с крупным итогом в R."""
    win = result["r"] >= 0
    head = {"TP": "ТЕЙК ВЗЯТ", "SL": "СТОП", "TIME": "ЗАКРЫТО ПО ВРЕМЕНИ"}[result["reason"]]
    lines = [
        f"{name} · {timeframe.upper()} · {'LONG' if trade['side'] == 'long' else 'SHORT'}",
        f"Вход {trade['entry']:.{digits}f} → выход {result['exit']:.{digits}f}",
        f"В сделке {result['bars']} бар. · {analysis._local(result['exit_time'], tz_name)}",
    ]
    sign = "+" if win else "−"
    return _text_card(head, name, lines, out_path,
                      accent=UP if win else DOWN, headline=f"{sign}{abs(result['r']):.2f}R")


def render_signal_card(sig: dict, df, name: str, timeframe: str, digits: int,
                       tz_name: str, out_path: str, bars: int = 96) -> str:
    """Свечной график с уровнями входа, стопа и тейка."""
    long_ = sig["side"] == "long"
    accent = UP if long_ else DOWN
    view = df.tail(bars)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_head, f_badge, f_small, f_tick = _font(30, True), _font(34, True), _font(18), _font(17)

    # ---- шапка
    d.rectangle([0, 0, W, HEADER_H], fill=PANEL)
    d.rectangle([0, HEADER_H, W, HEADER_H + 3], fill=accent)
    d.text((PAD_L, 28), f"СИГНАЛ · {name} {timeframe.upper()}", font=f_head, fill=TEXT)
    badge = "▲ ПОКУПКА" if long_ else "▼ ПРОДАЖА"
    d.text((W - PAD_R - d.textlength(badge, font=f_badge), 24), badge, font=f_badge, fill=accent)

    # ---- область графика
    top, bottom = HEADER_H + 26, H - FOOTER_H - 16
    lo = float(min(view["low"].min(), sig["stop"], sig["tp"]))
    hi = float(max(view["high"].max(), sig["stop"], sig["tp"]))
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad

    def y_of(value: float) -> float:
        return top + (bottom - top) * (hi - value) / (hi - lo)

    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        value = lo + (hi - lo) * frac
        y = y_of(value)
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=GRID)
        label = f"{value:.{digits}f}"
        d.text((W - PAD_R - d.textlength(label, font=f_tick) - 6, y - 20), label, font=f_tick, fill=MUTED)

    # ---- свечи
    step = (W - PAD_L - PAD_R) / max(len(view), 1)
    body_w = max(2.0, step * 0.62)
    for i, (_, row) in enumerate(view.iterrows()):
        x = PAD_L + step * (i + 0.5)
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = UP if c >= o else DOWN
        d.line([(x, y_of(h)), (x, y_of(l))], fill=color, width=1)
        y1, y2 = y_of(max(o, c)), y_of(min(o, c))
        d.rectangle([x - body_w / 2, y1, x + body_w / 2, max(y2, y1 + 1)], fill=color)

    # ---- уровни
    for value, label, color in (
        (sig["tp"], f"тейк {sig['tp']:.{digits}f}", UP),
        (sig["entry"], f"вход {sig['entry']:.{digits}f}", ENTRY),
        (sig["stop"], f"стоп {sig['stop']:.{digits}f}", DOWN),
    ):
        y = y_of(value)
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=color, width=2)
        d.rectangle([PAD_L, y - 13, PAD_L + d.textlength(label, font=f_tick) + 16, y + 13], fill=color)
        d.text((PAD_L + 8, y - 10), label, font=f_tick, fill=(12, 14, 18))

    # ---- подвал
    r_dist = abs(sig["entry"] - sig["stop"])
    rr = abs(sig["tp"] - sig["entry"]) / r_dist if r_dist else 0.0
    reason = str(sig.get("reason", ""))
    foot = f"риск/прибыль 1 : {rr:.1f}   ·   ADX {sig['adx']:.0f}   ·   тренд {sig['trend']}"
    d.text((PAD_L, H - FOOTER_H + 12), _ellipsis(d, foot, f_small, W - PAD_L - PAD_R - 260), font=f_small, fill=TEXT)
    stamp = analysis._local(sig["bar_time"], tz_name)
    d.text((W - PAD_R - d.textlength(stamp, font=f_small), H - FOOTER_H + 12), stamp, font=f_small, fill=MUTED)
    if reason:
        d.text((PAD_L, H - FOOTER_H + 38), _ellipsis(d, reason, f_small, W - PAD_L - PAD_R), font=f_small, fill=MUTED)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    frame = analysis.load_frame("GC=F")
    sig = analysis.detect_signal(frame, "breakout")
    print("сигнал:", "есть" if sig else "нет")
    if not sig:
        last = float(frame["close"].iloc[-1])
        atr = float(frame["atr"].iloc[-1])
        sig = {"side": "long", "entry": last, "stop": last - 1.5 * atr, "tp": last + 3 * atr,
               "rr": 2.0, "adx": float(frame["adx"].iloc[-1]), "trend": "вверх",
               "reason": "демонстрационная карточка", "bar_time": frame.index[-1].isoformat()}
    out = render_signal_card(sig, frame, "XAUUSD", "1h", 2, "Europe/Minsk", "report/card.png")
    print("карточка:", out)

"""Строит график доходности стратегии (PNG) по результатам бэктеста."""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont

import market

W, H = 1280, 620
PAD_L, PAD_R, PAD_T, PAD_B = 90, 40, 70, 70
BG = (250, 250, 252)
GRID = (225, 228, 235)
TEXT = (45, 50, 62)
MUTED = (120, 128, 142)
LINE = (32, 122, 78)
FILL = (220, 240, 228)
DD = (240, 214, 214)


def font(size: int):
    for path in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def main() -> None:
    import backtest as bt
    import indicators
    import strategy as st

    raw = market.get_history("GC=F", "1h", "730d", max_age_seconds=600)
    raw = market.closed_bars(raw, "1h")
    frame = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])
    sig = st.breakout(frame)
    tr = bt.simulate(frame, sig, bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None))

    r = tr["r"].to_numpy()
    equity = r.cumsum()
    peak = equity.copy()
    for i in range(1, len(equity)):
        peak[i] = max(peak[i - 1], equity[i])
    dd = peak - equity

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_title, f_sub, f_axis, f_small = font(30), font(18), font(16), font(14)

    d.text((PAD_L, 26), "Золото H1 · пробой канала: эквити в R", font=f_title, fill=TEXT)
    s = bt.stats(tr)
    d.text(
        (PAD_L, 62),
        f"{s['trades']} сделок · побед {s['winrate']:.0f}% · PF {s['pf']:.2f} · "
        f"ожидание {s['expectancy_r']:+.2f}R · итог {s['total_r']:+.0f}R · макс. просадка {s['max_dd_r']:.0f}R",
        font=f_sub, fill=MUTED,
    )

    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    lo = min(equity.min(), 0.0) - 5
    hi = max(equity.max(), 1.0) + 5
    step = 10 if hi - lo <= 140 else 20
    lo = (int(lo) // step) * step
    hi = -(-int(hi) // step) * step

    def xy(i: int, value: float) -> tuple[float, float]:
        x = PAD_L + plot_w * (i / max(len(equity) - 1, 1))
        y = PAD_T + plot_h * (hi - value) / (hi - lo)
        return x, y

    # сетка и подписи оси Y
    value = lo
    while value <= hi + 1e-9:
        _, y = xy(0, value)
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=GRID)
        d.text((22, y - 8), f"{value:.0f}", font=f_small, fill=MUTED)
        value += step

    # просадка
    for i in range(len(equity)):
        x, y_eq = xy(i, equity[i])
        _, y_pk = xy(i, peak[i])
        if y_eq > y_pk:
            d.line([(x, y_pk), (x, y_eq)], fill=DD)

    # заливка под кривой
    points = [xy(i, v) for i, v in enumerate(equity)]
    base_y = xy(0, 0)[1]
    poly = [(PAD_L, base_y)] + points + [(points[-1][0], base_y)]
    d.polygon(poly, fill=FILL)

    # нулевая линия и кривая
    d.line([(PAD_L, base_y), (W - PAD_R, base_y)], fill=(180, 186, 196), width=1)
    d.line(points, fill=LINE, width=3, joint="curve")

    # подписи дат
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        i = min(int((len(equity) - 1) * frac), len(equity) - 1)
        x, _ = xy(i, lo)
        label = tr["exit_time"].iloc[i].strftime("%m.%Y")
        d.text((x - 22, H - PAD_B + 12), label, font=f_small, fill=MUTED)

    d.text((PAD_L, H - 34), "по горизонтали — сделки, по вертикали — накопленный результат в R (1R = риск на сделку)",
           font=f_small, fill=MUTED)

    os.makedirs("report", exist_ok=True)
    out = os.path.join("report", "equity.png")
    img.save(out)
    print("Сохранено:", out, f"| сделок {len(tr)}, итог {s['total_r']:.1f}R")


if __name__ == "__main__":
    main()

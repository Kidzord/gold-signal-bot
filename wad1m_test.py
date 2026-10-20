"""Проверка идей из канала Fx_wad1m (уровни, пробой, ретест, ATR-фильтр) на золоте H1."""
from __future__ import annotations

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market
import strategy as st

pd.set_option("display.width", 220)

CFG = bt.BtConfig(spread=0.30, max_bars=48, be_after_r=None, session=None)


def day_range_ratio(df: pd.DataFrame) -> pd.Series:
    """Пройденный диапазон дня в единицах ATR (сколько уже проехали сегодня)."""
    day = df.index.tz_convert("UTC").date
    hi = df.groupby(day)["high"].cummax()
    lo = df.groupby(day)["low"].cummin()
    return (hi - lo) / df["atr"]


def retest_signals(df, base: pd.DataFrame, wait: int = 6, tol: float = 0.3) -> pd.DataFrame:
    """Вход не сразу за пробоем, а на возврате к пробитому уровню (ретест)."""
    n = len(df)
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = df["atr"].to_numpy(float)
    hi_lvl = df["don_hi"].to_numpy(float)
    lo_lvl = df["don_lo"].to_numpy(float)

    long_sig = np.zeros(n, bool)
    short_sig = np.zeros(n, bool)
    pending: list[dict] = []

    for i in range(1, n):
        pending = [p for p in pending if i - p["bar"] <= wait]

        if bool(base["long_signal"].iloc[i - 1]):
            pending.append({"side": "long", "level": hi_lvl[i - 1], "bar": i - 1})
        if bool(base["short_signal"].iloc[i - 1]):
            pending.append({"side": "short", "level": lo_lvl[i - 1], "bar": i - 1})

        for p in list(pending):
            if p["side"] == "long":
                touched = l[i] <= p["level"] + tol * atr[i]
                held = c[i] > p["level"]
                if touched and held:
                    long_sig[i] = True
                    pending.remove(p)
                    break
            else:
                touched = h[i] >= p["level"] - tol * atr[i]
                held = c[i] < p["level"]
                if touched and held:
                    short_sig[i] = True
                    pending.remove(p)
                    break

    out = base.copy()
    out["long_signal"] = long_sig
    out["short_signal"] = short_sig
    out["reason"] = "ретест пробитого уровня 24ч"
    return out


def main() -> None:
    raw = market.closed_bars(market.get_history("GC=F", "1h", "730d", max_age_seconds=600), "1h")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])
    base = st.breakout(df)

    b = bt.stats(bt.simulate(df, base, CFG))
    print(f"БАЗА: {b['trades']} сделок · {b['winrate']:.0f}% · PF {b['pf']:.2f} · {b['expectancy_r']:+.3f}R · {b['total_r']:+.0f}R\n")

    # 1. ATR-фильтр: не входить, если день уже прошёл большую часть ATR
    ratio = day_range_ratio(df)
    print("=== Фильтр «день уже прошёл N ATR»")
    for k in (0.5, 0.8, 1.0, 1.3, 1.6):
        sig = base.copy()
        sig.loc[ratio > k, ["long_signal", "short_signal"]] = False
        s = bt.stats(bt.simulate(df, sig, CFG))
        print(f"  max {k:.1f} ATR: {s['trades']:4d} сделок · {s['winrate']:4.1f}% · PF {s['pf']:.2f} · "
              f"{s['expectancy_r']:+.3f}R · {s['total_r']:+.0f}R · DD {s['max_dd_r']:.1f}R")

    # 2. Вход на ретесте вместо входа за пробоем
    print("\n=== Вход на ретесте уровня (wait / tolerance)")
    for wait in (3, 6, 10):
        for tol in (0.2, 0.4):
            sig = retest_signals(df, base, wait=wait, tol=tol)
            s = bt.stats(bt.simulate(df, sig, CFG))
            print(f"  wait {wait:2d}ч · tol {tol:.1f} ATR: {s['trades']:4d} сделок · {s['winrate']:4.1f}% · "
                  f"PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R · {s['total_r']:+.0f}R · DD {s['max_dd_r']:.1f}R")

    # 3. Комбинация: ретест + ATR-фильтр
    print("\n=== Ретест + фильтр ATR дня")
    best = None
    for wait in (3, 6, 10):
        for tol in (0.2, 0.4):
            for k in (0.8, 1.0, 1.3):
                sig = retest_signals(df, base, wait=wait, tol=tol)
                sig.loc[ratio > k, ["long_signal", "short_signal"]] = False
                s = bt.stats(bt.simulate(df, sig, CFG))
                row = (s["expectancy_r"], wait, tol, k, s)
                if best is None or row[0] > best[0]:
                    best = row
    if best:
        exp, wait, tol, k, s = best
        print(f"  лучший: wait {wait} · tol {tol} · max {k} ATR → {s['trades']} сделок · "
              f"{s['winrate']:.1f}% · PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R · {s['total_r']:+.0f}R")


if __name__ == "__main__":
    main()

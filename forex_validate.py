"""Валидация H4-пробоя на EURUSD/GBPUSD: фолды, годы, издержки, параметры, бутстрэп."""
from __future__ import annotations

import itertools
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

import backtest as bt
import indicators
import market

pd.set_option("display.width", 220)


def channel_signals(df: pd.DataFrame, n: int, stop: float = 1.5, rr: float = 2.0) -> pd.DataFrame:
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    up = (df["close"] > df["ema200"]) & (df["ema50"] > df["ema200"])
    dn = (df["close"] < df["ema200"]) & (df["ema50"] < df["ema200"])
    vol_ok = df["atr"] > 0.8 * df["atr_median"]
    out = pd.DataFrame(index=df.index)
    out["long_signal"] = (df["close"] > hi) & up & vol_ok & (df["adx"] > 18)
    out["short_signal"] = (df["close"] < lo) & dn & vol_ok & (df["adx"] > 18)
    out["stop_atr"] = stop
    out["rr"] = rr
    out["reason"] = ""
    return out


def load(symbol: str) -> pd.DataFrame:
    h1 = market.closed_bars(market.get_history(symbol, "1h", "730d", max_age_seconds=600), "1h")
    h4 = h1.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()
    return indicators.enrich(h4).dropna(subset=["ema200", "atr", "adx", "atr_median"])


def main() -> None:
    for symbol, name, channel, pip in (
        ("EURUSD=X", "EURUSD", 48, 0.0001),
        ("GBPUSD=X", "GBPUSD", 24, 0.0001),
    ):
        df = load(symbol)
        cfg = bt.BtConfig(spread=1.0 * pip, max_bars=30, be_after_r=None, session=None)
        sig = channel_signals(df, channel)
        tr = bt.simulate(df, sig, cfg)
        s = bt.stats(tr)
        print(f"\n{'=' * 70}\n{name} H4, канал {channel}: {s['trades']} сделок · {s['winrate']:.1f}% · "
              f"PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R")

        edges = [int(len(df) * i / 4) for i in range(5)]
        print("  фолды:", end=" ")
        for i in range(4):
            part = df.iloc[edges[i]:edges[i + 1]]
            fs = bt.stats(bt.simulate(part, channel_signals(part, channel), cfg))
            print(f"{fs['expectancy_r']:+.2f}R ({fs['trades']})", end="  ")
        print()

        tr2 = tr.copy()
        tr2["year"] = pd.to_datetime(tr2["entry_time"]).dt.year
        print("  по годам:", {int(y): (round(g["r"].mean(), 2), len(g)) for y, g in tr2.groupby("year")})

        print("  по сторонам:", {k: (round(v["r"].mean(), 2), len(v)) for k, v in tr.groupby("side")})
        print("  издержки:", end=" ")
        for sp in (0.3, 0.5, 1.0, 1.5, 2.0):
            ss = bt.stats(bt.simulate(df, sig, bt.BtConfig(spread=sp * pip, max_bars=30, be_after_r=None, session=None)))
            print(f"{sp:.1f}п={ss['expectancy_r']:+.2f}R", end="  ")
        print()

        print("  параметры (стоп/RR):", end=" ")
        for stop, rr in itertools.product((1.2, 1.5, 2.0), (1.5, 2.0, 3.0)):
            ss = bt.stats(bt.simulate(df, channel_signals(df, channel, stop, rr),
                                      bt.BtConfig(spread=1.0 * pip, max_bars=30, be_after_r=None, session=None, tp_r=rr)))
            print(f"st{stop}/rr{rr}={ss['expectancy_r']:+.2f}", end="  ")
        print()

        r = tr["r"].to_numpy()
        rng = np.random.default_rng(7)
        boots = np.array([rng.choice(r, len(r), replace=True).sum() for _ in range(3000)])
        print(f"  бутстрэп: 5% {np.percentile(boots, 5):+.1f}R · 50% {np.percentile(boots, 50):+.1f}R · "
              f"95% {np.percentile(boots, 95):+.1f}R · доля>0 {(boots > 0).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()

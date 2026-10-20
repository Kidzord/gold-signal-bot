"""Проверка пробоя канала на H4 для EURUSD/GBPUSD."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

import backtest as bt
import indicators
import market

pd.set_option("display.width", 200)


def channel_signals(df: pd.DataFrame, n: int, rr: float = 2.0) -> pd.DataFrame:
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    up = (df["close"] > df["ema200"]) & (df["ema50"] > df["ema200"])
    dn = (df["close"] < df["ema200"]) & (df["ema50"] < df["ema200"])
    vol_ok = df["atr"] > 0.8 * df["atr_median"]
    out = pd.DataFrame(index=df.index)
    out["long_signal"] = (df["close"] > hi) & up & vol_ok & (df["adx"] > 18)
    out["short_signal"] = (df["close"] < lo) & dn & vol_ok & (df["adx"] > 18)
    out["stop_atr"] = 1.5
    out["rr"] = rr
    out["reason"] = ""
    return out


def main() -> None:
    rows = []
    for symbol, name, pip in (("EURUSD=X", "EURUSD", 0.0001), ("GBPUSD=X", "GBPUSD", 0.0001)):
        h1 = market.closed_bars(market.get_history(symbol, "1h", "730d", max_age_seconds=600), "1h")
        h4 = h1.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last", "volume": "sum"}).dropna()
        df = indicators.enrich(h4).dropna(subset=["ema200", "atr", "adx", "atr_median"])
        print(f"\n=== {name} H4: {len(df)} баров, ATR {df['atr'].mean() / pip:.1f} пипсов")
        for n in (12, 24, 48):
            for sp in (0.5, 1.5):
                sig = channel_signals(df, n)
                cfg = bt.BtConfig(spread=sp * pip, max_bars=30, be_after_r=None, session=None)
                s = bt.stats(bt.simulate(df, sig, cfg))
                rows.append({"pair": name, "tf": "H4", "channel": n, "spread": sp,
                             "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                             "exp": round(s["expectancy_r"], 3), "dd": round(s["max_dd_r"], 1)})
                print(f"  ch{n:2d} спред {sp:.1f} п: {s['trades']:3d} сделок · {s['winrate']:4.1f}% · "
                      f"PF {s['pf']:.2f} · {s['expectancy_r']:+.3f}R · DD {s['max_dd_r']:.1f}R")
    pd.DataFrame(rows).sort_values("exp", ascending=False).to_csv("cache/forex_h4.csv", index=False)


if __name__ == "__main__":
    main()

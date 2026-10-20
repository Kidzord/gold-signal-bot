"""Проверка устойчивости фильтров вокруг базовой идеи пробоя (без агрессивного подбора)."""
from __future__ import annotations

import itertools

import pandas as pd

import backtest as bt
import indicators
import market

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)


def signals(df: pd.DataFrame, channel: int, align: bool, adx_min: float, buffer_atr: float) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    hi = df["high"].rolling(channel).max().shift(1)
    lo = df["low"].rolling(channel).min().shift(1)
    vol_ok = df["atr"] > 0.8 * df["atr_median"]

    up = df["close"] > df["ema200"]
    dn = df["close"] < df["ema200"]
    if align:
        up &= df["ema50"] > df["ema200"]
        dn &= df["ema50"] < df["ema200"]

    buf = buffer_atr * df["atr"]
    out["long_signal"] = (df["close"] > hi + buf) & up & vol_ok & (df["adx"] > adx_min)
    out["short_signal"] = (df["close"] < lo - buf) & dn & vol_ok & (df["adx"] > adx_min)
    out["stop_atr"] = 1.5
    out["rr"] = 2.0
    return out


def folds(df: pd.DataFrame, sig: pd.DataFrame, n: int = 4) -> float:
    edges = [int(len(df) * k / n) for k in range(n + 1)]
    return min(
        bt.stats(bt.simulate(df.iloc[edges[k]:edges[k + 1]], sig.iloc[edges[k]:edges[k + 1]],
                             bt.BtConfig(be_after_r=None, session=None, tp_r=2.0)))["expectancy_r"]
        for k in range(n)
    )


def main() -> None:
    df = indicators.enrich(market.fetch_candles("GC=F", "1h", "730d")).dropna(
        subset=["ema200", "atr", "adx", "atr_median"]
    )
    rows = []
    for channel, align, adx_min, buf in itertools.product((12, 24, 48), (False, True), (15, 18, 22), (0.0, 0.1)):
        sig = signals(df, channel, align, adx_min, buf)
        tr = bt.simulate(df, sig, bt.BtConfig(be_after_r=None, session=None, tp_r=2.0))
        s = bt.stats(tr)
        if s["trades"] < 40:
            continue
        rows.append(
            {
                "ch": channel, "align": align, "adx": adx_min, "buf": buf,
                "n": s["trades"], "wr": round(s["winrate"], 1), "pf": round(s["pf"], 2),
                "exp": round(s["expectancy_r"], 3), "total": round(s["total_r"], 1),
                "dd": round(s["max_dd_r"], 1), "per_month": round(s["trades_per_month"], 1),
                "fold_min": round(folds(df, sig), 3),
            }
        )
    res = pd.DataFrame(rows).sort_values("exp", ascending=False)
    print(res.to_string(index=False))
    res.to_csv("cache/variants.csv", index=False)


if __name__ == "__main__":
    main()

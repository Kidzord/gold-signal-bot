"""Диагностика: есть ли вообще предсказательная сила у типов сигналов.

Считаем средний форвардный доход в единицах ATR на горизонтах 6/12/24/48 баров
и сравниваем с безусловным средним по всей выборке.
"""
from __future__ import annotations

import pandas as pd

import indicators
import market
import strategy as st

HORIZONS = (6, 12, 24, 48)


def fwd_returns(df: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    c = df["close"]
    for hzn in horizons:
        out[f"f{hzn}"] = (c.shift(-hzn) - c) / df["atr"]
    return out


def summarize(df: pd.DataFrame, mask: pd.Series, label: str) -> None:
    rows = []
    base = df[[f"f{h}" for h in HORIZONS]].median()
    for h in HORIZONS:
        vals = df.loc[mask, f"f{h}"].dropna()
        if len(vals) < 5:
            continue
        rows.append(
            {
                "signal": label,
                "h": h,
                "n": len(vals),
                "mean_ATR": vals.mean(),
                "median_ATR": vals.median(),
                "hit>0": (vals > 0).mean() * 100,
                "base_median": base[f"f{h}"],
            }
        )
    if rows:
        print(pd.DataFrame(rows).round(3).to_string(index=False))


def main() -> None:
    raw = market.fetch_candles("GC=F", "1h", "730d")
    df = indicators.enrich(raw).dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])

    rets = df["close"].pct_change()
    big = rets.abs() > 0.02
    print(f"Баров: {len(df)} | однобаровых скачков >2%: {int(big.sum())}")
    print("Крупнейшие скачки:")
    print(rets[big].sort_values(key=abs, ascending=False).head(5).round(4).to_string())

    df = df.join(fwd_returns(df))

    for key, (meta, fn) in st.CATALOG.items():
        sig = fn(df)
        print(f"\n### {key} ({meta.title})")
        summarize(df, sig["long_signal"], "long")
        summarize(df, sig["short_signal"], "short")

    print("\n### Базовая линия (все бары)")
    print(f"median fwd в ATR: {df[[f'f{h}' for h in HORIZONS]].median().round(3).to_dict()}")
    print(f"средний fwd в ATR: {df[[f'f{h}' for h in HORIZONS]].mean().round(3).to_dict()}")

    # тренд: сколько заработал бы buy&hold и как велика доля положительных баров
    print(f"\nЦена: {df['close'].iloc[0]:.0f} -> {df['close'].iloc[-1]:.0f} "
          f"({(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:.0f}%)")
    print(f"Доля баров с ростом: {(rets > 0).mean()*100:.1f}%")


if __name__ == "__main__":
    main()

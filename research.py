"""РСЃСЃР»РµРґРѕРІР°С‚РµР»СЊСЃРєРёР№ РїСЂРѕРіРѕРЅ: СЃСЂР°РІРЅРµРЅРёРµ СЃС‚СЂР°С‚РµРіРёР№ Рё walk-forward. РќРµ РІС…РѕРґРёС‚ РІ Р±РѕС‚Р°."""
from __future__ import annotations

import pandas as pd

import backtest as bt
import indicators
import market
import strategy as st

SYMBOL = "GC=F"
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def main() -> None:
    raw = market.get_history(SYMBOL, "1h", "730d", max_age_seconds=600)
    raw = market.closed_bars(raw, "1h")
    print(f"РЎРІРµС‡РµР№: {len(raw)}  {raw.index[0]} .. {raw.index[-1]}")
    days = raw.groupby(raw.index.date).size()
    print(f"Р‘Р°СЂРѕРІ РІ РґРµРЅСЊ: СЃСЂРµРґРЅРµРµ {days.mean():.1f}, РјРёРЅ {days.min()}, РјР°РєСЃ {days.max()}")
    print(f"Р”РёР°РїР°Р·РѕРЅ С†РµРЅС‹: {raw['low'].min():.1f} .. {raw['high'].max():.1f}")
    deltas = raw.index.to_series().diff().dropna().dt.total_seconds() / 3600
    print("Р Р°Р·СЂС‹РІС‹ > 2С‡:", int((deltas > 2).sum()), "| РјР°РєСЃРёРјР°Р»СЊРЅС‹Р№ СЂР°Р·СЂС‹РІ, С‡:", round(deltas.max(), 1))

    df = indicators.enrich(raw)
    print(f"NaN РґРѕ: {len(df)}, РїРѕСЃР»Рµ РїСЂРѕРіСЂРµРІР°: {len(df.dropna(subset=['ema200', 'atr', 'adx', 'atr_median', 'don_hi']))}")
    df = df.dropna(subset=["ema200", "atr", "adx", "atr_median", "don_hi"])

    rows = []
    for key, (meta, fn) in st.CATALOG.items():
        sig = fn(df)
        print(f"\n=== {key}: {meta.title} | СЃРёРіРЅР°Р»РѕРІ long {int(sig.long_signal.sum())}, short {int(sig.short_signal.sum())}")
        for sess_label, sess in (("all", None), ("07-20", (7, 20))):
            for spread in (0.30, 0.80):
                cfg = bt.BtConfig(spread=spread, session=sess, be_after_r=None)
                tr = bt.simulate(df, sig, cfg)
                s = bt.stats(tr)
                s.update({"strategy": key, "session": sess_label, "spread": spread})
                rows.append(s)

    table = pd.DataFrame(rows)[
        ["strategy", "session", "spread", "trades", "winrate", "pf", "expectancy_r",
         "total_r", "max_dd_r", "trades_per_month", "avg_bars", "long_trades", "short_trades"]
    ]
    print("\n", table.round(2).to_string(index=False))

    table.to_csv("cache/research_results.csv", index=False)

    print("\n\n=== Walk-forward (4 С„РѕР»РґР°, СЃРµСЃСЃРёСЏ 07-20, СЃРїСЂРµРґ 0.30)")
    for key, (_meta, fn) in st.CATALOG.items():
        def runner(part, fn=fn):
            sig = fn(part)
            return bt.simulate(part, sig, bt.BtConfig(spread=0.30, session=None, be_after_r=None))

        folds = bt.fold_report(df, runner, folds=4)
        print(f"\n--- {key}")
        print(pd.DataFrame(folds)[["from", "to", "trades", "winrate", "pf", "expectancy_r", "total_r"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()

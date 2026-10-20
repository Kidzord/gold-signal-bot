"""Поиск похожих ботов на GitHub и разбор их возможностей."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com"

QUERIES = [
    "telegram trading signals bot",
    "telegram forex signals bot",
    "gold signal bot telegram",
    "xauusd trading bot",
    "trading signals python telegram",
    "crypto signal bot telegram",
    "tradingview webhook telegram bot",
    "smc trading bot python",
]

FEATURES = {
    "backtest": ("backtest", "бэктест"),
    "telegram": ("telegram", "telegram"),
    "risk": ("risk management", "risk", "position size"),
    "multi": ("multi-symbol", "multiple symbols", "multi symbol", "portfolio"),
    "indicators": ("rsi", "macd", "ema", "atr", "bollinger"),
    "ml": ("machine learning", "lstm", "neural", "xgboost", "sklearn"),
    "webhook": ("webhook", "tradingview"),
    "mt5": ("metatrader", "mt5", "mt4"),
    "docker": ("docker",),
    "tests": ("pytest", "unittest", "tests"),
}


def api(path: str, raw: bool = False, retries: int = 3):
    for attempt in range(retries):
        req = urllib.request.Request(API + path)
        req.add_header("Authorization", "Bearer " + TOKEN)
        req.add_header("Accept", "application/vnd.github.raw" if raw else "application/vnd.github+json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                return body.decode("utf-8", errors="replace") if raw else json.loads(body.decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                time.sleep(5 * (attempt + 1))
                continue
            if raw:
                return ""
            raise
    return "" if raw else {}


def main() -> None:
    repos: dict[str, dict] = {}
    for query in QUERIES:
        path = f"/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc&per_page=15"
        data = api(path)
        for item in data.get("items", []):
            repos[item["full_name"]] = {
                "name": item["full_name"],
                "stars": item["stargazers_count"],
                "lang": item.get("language") or "—",
                "desc": (item.get("description") or "")[:110],
                "updated": (item.get("updated_at") or "")[:10],
            }
        time.sleep(1)

    top = sorted(repos.values(), key=lambda r: -r["stars"])[:20]
    print(f"найдено уникальных репозиториев: {len(repos)}\n")
    for i, r in enumerate(top, 1):
        print(f"{i:2d}. {r['name']}  ★{r['stars']}  {r['lang']}  {r['updated']}")
        print(f"    {r['desc']}")

    print("\n=== разбор README (топ-12) ===")
    rows = []
    for r in top[:12]:
        readme = api(f"/repos/{r['name']}/readme", raw=True).lower()
        found = [key for key, words in FEATURES.items() if any(w in readme for w in words)]
        rows.append({"repo": r["name"], "stars": r["stars"], "features": ", ".join(found) or "—",
                     "len": len(readme)})
        time.sleep(0.5)

    print(f"{'репозиторий':45s} {'★':>6s}  функции")
    for row in rows:
        print(f"{row['repo']:45s} {row['stars']:6d}  {row['features']}")

    with open("cache/github_compare.json", "w", encoding="utf-8") as fh:
        json.dump({"top": top, "features": rows}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

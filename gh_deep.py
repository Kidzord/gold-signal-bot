"""Детальный разбор выбранных репозиториев: README, стек, тесты, лицензия."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com"

REPOS = [
    "fabston/TradingView-Webhook-Bot",
    "GifariKemal/xaubot-ai",
    "zero-was-here/tradingbot",
    "3aLaee/xauusd-trading-bot",
    "b-fg/nuatsbot",
    "triqbit/mt5-ai-xauusd-trader",
]

KEYS = ["backtest", "win rate", "winrate", "risk", "stop loss", "take profit",
        "telegram", "strategy", "mt5", "binance", "docker", "pytest", "license"]


def api(path: str, raw: bool = False):
    req = urllib.request.Request(API + path)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github.raw" if raw else "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return body if raw else json.loads(body)
    except Exception as exc:  # noqa: BLE001
        return "" if raw else {"error": str(exc)}


def main() -> None:
    for full in REPOS:
        meta = api(f"/repos/{full}")
        readme = api(f"/repos/{full}/readme", raw=True)
        low = readme.lower()

        tree = api(f"/repos/{full}/git/trees/{meta.get('default_branch', 'main')}?recursive=1")
        files = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob"]
        tests = [f for f in files if "test" in f.lower()]
        has_backtest = any("backtest" in f.lower() for f in files)

        print("=" * 78)
        print(f"{full}  ★{meta.get('stargazers_count')}  {meta.get('language')}  "
              f"лицензия: {(meta.get('license') or {}).get('spdx_id', '—')}")
        print(f"  файлов: {len(files)}, тесты: {len(tests)}, файл с backtest: {has_backtest}, "
              f"README: {len(readme)} символов")
        print(f"  описание: {meta.get('description')}")

        hits = {k: low.count(k) for k in KEYS if low.count(k)}
        print(f"  упоминания: {hits}")

        # ключевые фразы про результат
        for line in readme.splitlines():
            s = line.strip()
            if 20 < len(s) < 200 and re.search(r"(win rate|winrate|profit|accuracy|RR|backtest)", s, re.I):
                print("   >", s[:180])
        if not readme:
            print("  README недоступен")


if __name__ == "__main__":
    main()

"""Скачивает лог последнего запуска Actions и ищет ключевые строки."""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["GH_TOKEN"]
REPO = "Kidzord/gold-signal-bot"


def api_json(path: str):
    import json

    req = urllib.request.Request("https://api.github.com" + path)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    runs = api_json(f"/repos/{REPO}/actions/runs?per_page=1")
    run = runs["workflow_runs"][0]
    print(f"run {run['id']}: {run['status']} / {run.get('conclusion')}")

    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/actions/runs/{run['id']}/logs")
    req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=60) as resp:
        blob = resp.read()

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            if "Один проход" not in name and "run" not in name.lower():
                continue
            text = zf.read(name).decode("utf-8", errors="replace")
            for line in text.splitlines():
                if any(k in line for k in ("Подписчиков", "Инструменты", "Один проход",
                                           "Сигнал", "закрыта", "Traceback", "Error")):
                    print(" ", line.strip()[:200])


if __name__ == "__main__":
    main()

"""Загружает файлы проекта в GitHub через Contents API (без git)."""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://api.github.com"
REPO = "Kidzord/gold-signal-bot"
TOKEN = os.environ["GH_TOKEN"]
BASE = os.path.dirname(os.path.abspath(__file__))


def put_file(path: str, message: str) -> tuple[int, str]:
    full = os.path.join(BASE, path)
    with open(full, "rb") as fh:
        content = base64.b64encode(fh.read()).decode()
    payload = {"message": message, "content": content}
    data = json.dumps(payload).encode()
    url = f"{API}/repos/{REPO}/contents/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            msg = json.loads(body).get("message", body)
        except ValueError:
            msg = body
        return exc.code, msg


def main() -> None:
    files: list[str] = []
    for name in sorted(os.listdir(BASE)):
        if name.endswith(".py"):
            files.append(name)
    files += [
        "README.md", "REPORT.md", "requirements.txt", "requirements-bot.txt",
        "config.ci.json", "run.bat", "setup_autostart.ps1", ".gitignore",
    ]
    for folder in ("deploy", ".github/workflows"):
        folder_path = os.path.join(BASE, folder)
        if os.path.isdir(folder_path):
            for name in sorted(os.listdir(folder_path)):
                full = os.path.join(folder_path, name)
                if os.path.isfile(full):
                    files.append(f"{folder}/{name}".replace("\\", "/"))

    ok, failed = 0, []
    for i, path in enumerate(files, 1):
        status, err = put_file(path, f"add: {path}")
        if status in (200, 201):
            ok += 1
        else:
            failed.append((path, status, err))
            print(f"  FAIL {path}: {status} {err}")
        if i % 10 == 0:
            print(f"  ... {i}/{len(files)}")
        time.sleep(0.15)

    print(f"\nзагружено: {ok} из {len(files)}")
    if failed:
        print("ошибки:")
        for path, status, err in failed:
            print(f"  {path}: {status} {err}")


if __name__ == "__main__":
    main()

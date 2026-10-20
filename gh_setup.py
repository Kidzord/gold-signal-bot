"""Ставит секрет TELEGRAM_BOT_TOKEN в GitHub и запускает workflow."""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from nacl import public

API = "https://api.github.com"
REPO = "Kidzord/gold-signal-bot"
TOKEN = os.environ["GH_TOKEN"]
BASE = os.path.dirname(os.path.abspath(__file__))


def api(method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode() or "{}"
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"message": body}


def main() -> None:
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as fh:
        bot_token = json.load(fh)["telegram_token"]
    if not bot_token:
        raise SystemExit("в config.json нет токена бота")

    status, key = api("GET", f"/repos/{REPO}/actions/secrets/public-key")
    if status != 200:
        raise SystemExit(f"не получил ключ секретов: {status} {key}")
    key_id, pub_key = key["key_id"], key["key"]

    sealed = public.SealedBox(public.PublicKey(base64.b64decode(pub_key)))
    encrypted = base64.b64encode(sealed.encrypt(bot_token.encode())).decode()

    status, body = api("PUT", f"/repos/{REPO}/actions/secrets/TELEGRAM_BOT_TOKEN",
                       {"encrypted_value": encrypted, "key_id": key_id})
    print("секрет:", status, body.get("message", "ok") if status not in (201, 204) else "добавлен")
    if status not in (201, 204):
        return

    status, resp = api("POST", f"/repos/{REPO}/actions/workflows/signals.yml/dispatches",
                       {"ref": "main"})
    print("запуск workflow:", status, resp.get("message", "ok"))

    for attempt in range(20):
        time.sleep(6)
        st, runs = api("GET", f"/repos/{REPO}/actions/runs?per_page=1")
        if st != 200 or not runs.get("workflow_runs"):
            continue
        run = runs["workflow_runs"][0]
        print(f"  [{attempt + 1}] run {run['id']}: {run['status']} / {run.get('conclusion')}")
        if run["status"] == "completed":
            print("итог:", run.get("conclusion"))
            print("лог:", run["html_url"])
            break


if __name__ == "__main__":
    main()

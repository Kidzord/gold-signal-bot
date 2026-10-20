"""Проверка последнего запуска workflow и содержимого репозитория."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOKEN = os.environ["GH_TOKEN"]
REPO = "Kidzord/gold-signal-bot"


def api(path: str):
    req = urllib.request.Request("https://api.github.com" + path)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    runs = api(f"/repos/{REPO}/actions/runs?per_page=1")
    run = runs["workflow_runs"][0]
    print(f"run {run['id']}: {run['status']} / {run.get('conclusion')}")
    jobs = api(f"/repos/{REPO}/actions/runs/{run['id']}/jobs")
    for job in jobs["jobs"]:
        print(f"job: {job['name']} {job['status']} / {job['conclusion']}")
        for step in job["steps"]:
            print(f"   {step['number']}. {step['name']}: {step['conclusion']}")

    files = api(f"/repos/{REPO}/contents/")
    names = sorted(f["name"] for f in files)
    print(f"\nв репозитории {len(names)} объектов верхнего уровня")
    for name in names:
        print("  ", name)
    print("workflow:", any(n == ".github" for n in names))
    print("config.json в репо:", any(n == "config.json" for n in names))
    print("probe.txt в репо:", any(n == "probe.txt" for n in names))


if __name__ == "__main__":
    main()

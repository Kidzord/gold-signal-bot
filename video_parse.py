"""Превращает VTT-субтитры YouTube в чистый текст без таймкодов и дублей."""
from __future__ import annotations

import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video")
SRC = os.path.join(BASE, "E5Bvm4HGkTw.ru.vtt")
OUT = os.path.join(BASE, "transcript.txt")


def main() -> None:
    lines: list[str] = []
    last = ""
    for raw in open(SRC, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line or re.fullmatch(r"\d+", line.strip()):
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if not text or text == last:
            continue
        lines.append(text)
        last = text

    # склеиваем в абзацы по ~12 реплик
    chunks = [" ".join(lines[i:i + 12]) for i in range(0, len(lines), 12)]
    body = "\n".join(chunks)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"реплик: {len(lines)}, абзацев: {len(chunks)}, символов: {len(body)} -> {OUT}")


if __name__ == "__main__":
    main()

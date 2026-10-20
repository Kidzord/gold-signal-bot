"""Выделяет из OCR связный текст (без мусора с графиков)."""
from __future__ import annotations

import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_text")
FILES = ["rare_snr_ocr.txt", "snr_malaysia_ocr.txt", "secret411_a_ocr.txt", "secret411_b_ocr.txt"]


def clean(line: str) -> str:
    line = line.replace("|", "I").strip()
    line = re.sub(r"\s+", " ", line)
    return line


def is_prose(line: str) -> bool:
    words = line.split()
    if len(words) < 6:
        return False
    letters = sum(ch.isalpha() for ch in line)
    if letters / max(len(line), 1) < 0.72:
        return False
    long_words = sum(1 for w in words if len(w) >= 4)
    return long_words >= max(3, len(words) // 2)


def main() -> None:
    out_path = os.path.join(BASE, "manuals_prose.txt")
    chunks = []
    for name in FILES:
        path = os.path.join(BASE, name)
        if not os.path.exists(path):
            continue
        chunks.append(f"\n\n########## {name} ##########\n")
        page = ""
        for raw in open(path, encoding="utf-8"):
            if raw.startswith("--- стр."):
                page = raw.strip()
                continue
            line = clean(raw)
            if is_prose(line):
                chunks.append(f"[{page}] {line}")
    text = "\n".join(chunks)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"строк: {len(chunks)}, символов: {len(text)} -> {out_path}")


if __name__ == "__main__":
    main()

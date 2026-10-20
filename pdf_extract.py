"""Извлекает текст из PDF-методичек в папку pdf_text/."""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pypdf import PdfReader

SOURCES = [
    r"C:\Users\admin\Downloads\Telegram Desktop\My Rare SNR Course.pdf",
    r"C:\Users\admin\Downloads\Telegram Desktop\SNR Malaysia.pdf",
    r"C:\Users\admin\Downloads\Telegram Desktop\MSNR-Strategy-044.pdf",
    r"C:\Users\admin\Downloads\Telegram Desktop\Secret Of 411(1).pdf",
    r"C:\Users\admin\Downloads\Telegram Desktop\Secret of 411 (2)2.pdf",
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_text")


def safe_name(path: str) -> str:
    base = os.path.basename(path).rsplit(".", 1)[0]
    return "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in base).strip()


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for path in SOURCES:
        if not os.path.exists(path):
            print(f"НЕТ ФАЙЛА: {path}")
            continue
        size_mb = os.path.getsize(path) / 1024 / 1024
        reader = PdfReader(path)
        pages: list[str] = []
        empty = 0
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                text = ""
                print(f"  ошибка страницы: {exc}")
            if len(text.strip()) < 20:
                empty += 1
            pages.append(text)

        body = "\n\n".join(f"--- стр. {i + 1} ---\n{t}" for i, t in enumerate(pages))
        name = safe_name(path)
        out_path = os.path.join(OUT, f"{name}.txt")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(body)

        print(f"{name}: страниц {len(pages)}, символов {len(body)}, пустых страниц {empty}, "
              f"{size_mb:.1f} МБ -> {out_path}")


if __name__ == "__main__":
    main()

"""Рендерит страницы сканированных PDF в PNG для OCR."""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pymupdf

SOURCES = {
    "rare_snr": r"C:\Users\admin\Downloads\Telegram Desktop\My Rare SNR Course.pdf",
    "snr_malaysia": r"C:\Users\admin\Downloads\Telegram Desktop\SNR Malaysia.pdf",
    "secret411_a": r"C:\Users\admin\Downloads\Telegram Desktop\Secret Of 411(1).pdf",
    "secret411_b": r"C:\Users\admin\Downloads\Telegram Desktop\Secret of 411 (2)2.pdf",
}

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_pages")


def main() -> None:
    for name, path in SOURCES.items():
        if not os.path.exists(path):
            print(f"НЕТ ФАЙЛА: {path}")
            continue
        folder = os.path.join(OUT, name)
        os.makedirs(folder, exist_ok=True)
        doc = pymupdf.open(path)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            pix.save(os.path.join(folder, f"page_{i + 1:03d}.png"))
        print(f"{name}: отрендерено {len(doc)} страниц -> {folder}")


if __name__ == "__main__":
    main()

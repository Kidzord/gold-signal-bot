"""Веб-панель состояния бота (только чтение, stdlib).

Показывает инструменты, открытые сделки, риск-лимиты и последние результаты.
Данные берутся из снимка, который бот обновляет при каждом скане, — поэтому
страница открывается мгновенно и не грузит котировки заново.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>{title}</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
        background:#14161a; color:#e6e8eb; }}
 h1 {{ font-size: 20px; margin: 0 0 4px; }}
 .muted {{ color:#8b929c; font-size: 13px; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 14px; font-size: 14px; }}
 th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #242830; }}
 th {{ color:#8b929c; font-weight: 500; font-size: 12px; text-transform: uppercase; }}
 .pos {{ color:#4ade80; }} .neg {{ color:#f87171; }}
 .card {{ background:#1a1d23; border:1px solid #242830; border-radius:10px; padding:16px; margin-top:18px; }}
 .tag {{ display:inline-block; padding:2px 8px; border-radius:6px; background:#242830; font-size:12px; }}
 .pause {{ background:#3a2a12; color:#fbbf24; }}
</style></head>
<body>
<h1>{title}</h1>
<div class="muted">обновлено: {updated} · подписчиков: {subs} · @{username}</div>
{body}
</body></html>
"""


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def render_page(snapshot: dict, title: str = "Сигналы") -> str:
    rows = []
    for item in snapshot.get("instruments", []):
        digits = item.get("digits", 2)
        trades = item.get("trades") or []
        if trades:
            trade_cells = "<br>".join(
                f"{t['strategy']}: {t['side'].upper()} {_fmt(t['entry'], digits)} "
                f"<span class=\"{'pos' if t['r_now'] >= 0 else 'neg'}\">{t['r_now']:+.2f}R</span>"
                for t in trades
            )
        else:
            trade_cells = '<span class="muted">нет</span>'
        risk = item.get("risk", {})
        blocked = risk.get("blocked")
        risk_txt = (
            f"день {risk.get('day', 0):+.1f} · неделя {risk.get('week', 0):+.1f} · "
            f"месяц {risk.get('month', 0):+.1f}R"
        )
        if blocked:
            risk_txt += ' <span class="tag pause">пауза</span>'
        rows.append(
            "<tr>"
            f"<td><b>{item['name']}</b><br><span class='muted'>{item['timeframe']} · "
            f"{', '.join(item['strategies'])}</span></td>"
            f"<td>{_fmt(item.get('price', 0), digits)}</td>"
            f"<td>{item.get('trend', '—')}</td>"
            f"<td>{trade_cells}</td>"
            f"<td class='muted'>{risk_txt}</td>"
            f"<td class='muted'>{item.get('last_bar', '—')}</td>"
            "</tr>"
        )

    body = (
        "<div class='card'>"
        "<table><thead><tr>"
        "<th>инструмент</th><th>цена</th><th>тренд</th><th>сделки</th>"
        "<th>риск-лимиты</th><th>последний бар</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    return PAGE.format(
        title=title,
        updated=snapshot.get("updated") or "—",
        subs=snapshot.get("subscribers", 0),
        username=snapshot.get("username", "—"),
        body=body,
    )


def make_handler(get_snapshot):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            snapshot = get_snapshot() or {"instruments": []}
            if self.path.startswith("/api/status"):
                payload = json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            page = render_page(snapshot).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):  # тише в логах
            return

    return Handler


def start_server(get_snapshot, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(get_snapshot))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

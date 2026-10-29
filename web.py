"""Dashboard (strateji bazında performans) + Railway healthcheck."""
import math
from html import escape

from flask import Flask, jsonify

import config
import storage

app = Flask(__name__)
STATE = {"started_at": None, "last_scan": {}, "last_pnl": None, "provider": None, "universe": None}

STATUS_COLOR = {"PENDING": "#aaa", "OPEN": "#9ad", "TP": "lime", "SL": "#f55",
                "INVALID": "#f90", "EXPIRED": "#fb3", "SKIPPED": "#777"}


def _f(x, fmt="{:.2f}"):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "–"
    return fmt.format(x)


@app.get("/health")
def health():
    return jsonify(ok=True, strategies=config.ENABLED_STRATEGIES, **STATE)


@app.get("/api/signals")
def api_signals():
    return jsonify(storage.fetch("SELECT * FROM signals ORDER BY id DESC LIMIT 500"))


@app.get("/api/stats")
def api_stats():
    return jsonify(storage.strategy_stats())


@app.get("/")
def index():
    rows = storage.fetch("SELECT * FROM signals ORDER BY id DESC LIMIT 150")
    stats = storage.strategy_stats()
    cost = 2 * (config.COMMISSION_PCT + config.SLIPPAGE_PCT)

    h = ["<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<meta http-equiv='refresh' content='60'><title>BIST Quant</title>",
         "<style>body{background:#111;color:#eee;font-family:sans-serif;padding:12px}"
         "table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #333;padding:4px 6px}"
         "th{background:#1c1c1c}.w{overflow-x:auto;margin-bottom:18px}small{color:#888}</style></head><body>",
         "<h2>⚡ BIST Strateji Tarayıcı</h2>",
         f"<p><small>Veri: {escape(str(STATE['provider']))} (Yahoo ≈15 dk gecikmeli) · Etkin: "
         f"{escape(', '.join(config.ENABLED_STRATEGIES))} · Evren: {escape(str(STATE['universe']))} · "
         f"Son tarama: {escape(str(STATE['last_scan']))} · "
         f"PnL'ler gidiş-dönüş {cost:.2f}% maliyet sonrası NET</small></p>",
         "<h3>Strateji bazında sonuçlar (kapanan işlemler)</h3><div class='w'><table>",
         "<tr><th>Strateji</th><th>İşlem</th><th>Kazanma %</th><th>Ort. kazanç</th><th>Ort. kayıp</th>"
         "<th>Beklenen net / işlem</th><th>Ort. R</th><th>Kâr faktörü</th><th>Toplam</th><th>Maks. düşüş</th></tr>"]
    if not stats:
        h.append("<tr><td colspan='10'><small>Henüz kapanan işlem yok.</small></td></tr>")
    for name, s in stats.items():
        exp_color = "lime" if s["expectancy"] > 0 else "#f55"
        h.append(f"<tr><td>{escape(name)}</td><td>{s['n']}</td><td>{_f(s['win_rate'], '{:.1f}')}</td>"
                 f"<td>{_f(s['avg_win'])}%</td><td>{_f(s['avg_loss'])}%</td>"
                 f"<td style='color:{exp_color}'>{_f(s['expectancy'])}%</td><td>{_f(s['expectancy_r'])}</td>"
                 f"<td>{_f(s['profit_factor'])}</td><td>{_f(s['total'])}%</td><td>{_f(s['max_dd'])}%</td></tr>")
    h.append("</table></div><p><small>Az sayıda işlemle (ör. &lt;30) yapılan karşılaştırmalar güvenilir değildir.</small></p>")

    h.append("<h3>Sinyaller</h3><div class='w'><table><tr><th>Tarih</th><th>Sembol</th><th>TF</th><th>Strateji</th>"
             "<th>Rejim</th><th>Kalite</th><th>Sinyal</th><th>Giriş</th><th>Stop</th><th>Hedef</th>"
             "<th>Güncel/Çıkış</th><th>Durum</th><th>Net PnL</th><th>R</th><th>Nedenler</th></tr>")
    for r in rows:
        pnl = r["pnl_percent"] or 0.0
        color = "lime" if pnl > 0 else ("#f55" if pnl < 0 else "#ccc")
        st = r["status"] or ""
        if st == "SKIPPED" and r.get("skip_reason"):
            st = f"SKIPPED ({r['skip_reason']})"
        h.append(
            f"<tr><td>{escape(str(r['entry_date']))}</td><td>{escape(str(r['symbol']).replace('.IS', ''))}</td>"
            f"<td>{escape(str(r['timeframe']))}</td><td>{escape(str(r['strategy']))}</td>"
            f"<td>{escape(str(r.get('regime') or ''))}</td><td>{_f(r.get('quality'), '{:.0f}')}</td>"
            f"<td>{_f(r.get('signal_price'))}</td><td>{_f(r.get('entry_price'))}</td>"
            f"<td>{_f(r.get('stop_price'))}</td><td>{_f(r.get('target_price'))}</td>"
            f"<td>{_f(r.get('exit_price') or r.get('current_price'))}</td>"
            f"<td style='color:{STATUS_COLOR.get(r['status'], '#eee')}'>{escape(st)}</td>"
            f"<td style='color:{color}'>{_f(pnl)}%</td><td>{_f(r.get('r_multiple'))}</td>"
            f"<td><small>{escape(str(r.get('reasons') or ''))}</small></td></tr>"
        )
    h.append("</table></div><p><small>Yatırım tavsiyesi değildir.</small></p></body></html>")
    return "".join(h)

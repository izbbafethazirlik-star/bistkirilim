"""BIST Kırılım + RSI tarayıcı — Railway için giriş noktası.

Çalıştırma: python bot_bist.py
"""
import asyncio
import html
import logging
import random
import threading
from datetime import datetime, timedelta

from waitress import serve

import config
import storage
import strategy
from data_source import get_provider
from notifier import TelegramQueue
from regime import LABELS_TR
from storage import ACTIVE
from strategies import NAMES_TR
from tracker import evaluate_position
from web import STATE, app

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger("BIST_QUANT")


def now_ist() -> datetime:
    return datetime.now(config.TZ)


def in_session_window(now: datetime) -> bool:
    """Hafta içi 10:00 – 19:30 (kapanış seansı barının gecikmeli verisi dahil)."""
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=config.MARKET_OPEN[0], minute=config.MARKET_OPEN[1], second=0, microsecond=0)
    end = now.replace(hour=19, minute=30, second=0, microsecond=0)
    return start <= now < end


def daily_close_ready(now: datetime) -> bool:
    h, m = config.MARKET_CLOSE
    ready = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=config.DATA_DELAY_MIN + 5)
    return now.weekday() < 5 and now >= ready


def batched(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


class QuantBot:
    def __init__(self):
        storage.init_db()
        self.provider = get_provider()
        self.tg = TelegramQueue()
        STATE["provider"] = self.provider.name
        STATE["started_at"] = now_ist().isoformat(timespec="seconds")

    # ---------------- TARAMA ----------------
    async def scan(self, interval: str):
        symbols = config.get_symbols()
        random.shuffle(symbols)
        period = config.LOOKBACK.get(interval, "6mo")
        logger.info(f"🔍 {interval} taraması: {len(symbols)} sembol | stratejiler={config.ENABLED_STRATEGIES}")
        no_data, found = [], 0
        q = f"SELECT symbol, strategy FROM signals WHERE timeframe=? AND status IN ({','.join('?' * len(ACTIVE))})"
        active = {(r["symbol"], r["strategy"]) for r in storage.fetch(q, (interval, *ACTIVE))}

        for batch in batched(symbols, config.BATCH_SIZE):
            frames = await self.provider.fetch(batch, period, interval)
            no_data += [s for s in batch if s not in frames]
            now = now_ist()
            for symbol, df in frames.items():
                try:
                    # Aynı hissede aynı stratejiden açık/bekleyen pozisyon varken yeni sinyal yok
                    enabled = [s for s in config.ENABLED_STRATEGIES if (symbol, s) not in active]
                    if not enabled:
                        continue
                    for sig in strategy.analyze(df, symbol, interval, now, enabled):
                        found += await self._emit(sig)
                except Exception as e:
                    logger.exception(f"{symbol} analiz hatası: {e}")
            await asyncio.sleep(2)

        if no_data:
            logger.warning(f"Veri gelmeyen semboller ({len(no_data)}): {', '.join(sorted(no_data))}")
        STATE["last_scan"][interval] = now_ist().isoformat(timespec="seconds")
        logger.info(f"✅ {interval} taraması bitti, yeni sinyal: {found}")

    async def _emit(self, sig) -> int:
        c = sig["cand"]
        inserted = storage.execute(
            "INSERT OR IGNORE INTO signals (symbol, timeframe, strategy, regime, bar_time, entry_date, "
            "signal_price, current_price, stop_price, target_price, invalidation, quality, score, reasons, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING')",
            (sig["symbol"], sig["interval"], c.strategy, c.regime, sig["bar_time"],
             now_ist().strftime("%Y-%m-%d %H:%M"), c.entry_ref, c.entry_ref, c.stop, c.target,
             c.invalidation, c.quality, c.quality, " · ".join(c.reasons)),
        )
        if not inserted:  # aynı bar + strateji için zaten sinyal var (ör. restart sonrası)
            return 0
        logger.info(f"📈 Sinyal: {sig['symbol']} {sig['interval']} {c.strategy} Q={c.quality:.0f} rejim={c.regime}")
        loop = asyncio.get_running_loop()
        chart = await loop.run_in_executor(None, strategy.generate_chart, sig)
        name = html.escape(sig["symbol"].replace(".IS", ""))
        reasons = "\n".join(f"• {html.escape(r)}" for r in c.reasons)
        caption = (
            f"🤖 <b>{NAMES_TR.get(c.strategy, c.strategy)}</b> ({sig['interval']})\n\n"
            f"📈 <b>{name}</b> · Rejim: {LABELS_TR.get(c.regime, c.regime)}\n"
            f"💰 Sinyal: {c.entry_ref:.2f} TL (bar: {sig['bar_time'][:16].replace('T', ' ')})\n"
            f"⛔ Stop: {c.stop:.2f} (-{c.risk_pct:.1f}%)  🎯 Hedef: {c.target:.2f} ({config.TARGET_R:g}R)\n"
            + (f"❌ İptal: {c.invalidation:.2f} altında kapanış\n" if c.invalidation else "")
            + f"⭐ Kalite: {c.quality:.0f}/100 | RSI {sig['rsi']:.0f}\n{reasons}"
        )
        footer = (f"\n\n<i>Giriş bir sonraki bar açılışında varsayılır. Veri ~{config.DATA_DELAY_MIN} dk "
                  f"gecikmeli. Yatırım tavsiyesi değildir.</i>")
        if len(caption) + len(footer) <= 1024:  # Telegram foto açıklama sınırı
            caption += footer
        await self.tg.send_photo(chart, caption)
        return 1

    # ---------------- PnL TAKİBİ ----------------
    async def update_pnl(self):
        q = f"SELECT * FROM signals WHERE status IN ({','.join('?' * len(ACTIVE))})"
        rows = storage.fetch(q, ACTIVE)
        if not rows:
            return
        symbols = sorted({r["symbol"] for r in rows})
        frames = {}
        for batch in batched(symbols, config.BATCH_SIZE):
            frames.update(await self.provider.fetch(batch, "3mo", "1h"))

        for row in rows:
            df = frames.get(row["symbol"])
            if df is None:
                continue
            res = evaluate_position(row, df)
            st = res.get("status")
            name = html.escape(row["symbol"].replace(".IS", ""))
            label = f"<b>{name}</b> ({row['timeframe']}, {NAMES_TR.get(row['strategy'], row['strategy'])})"
            if st in (None, "PENDING"):
                continue
            if st == "SKIPPED":
                storage.execute("UPDATE signals SET status='SKIPPED', skip_reason=?, entry_price=? WHERE id=?",
                                (res["reason"], res["fill_price"], row["id"]))
                await self.tg.send_text(f"⏭ {label} işleme girilmedi: {res['reason']} "
                                        f"(açılış {res['fill_price']:.2f})")
            elif st == "OPEN":
                storage.execute(
                    "UPDATE signals SET status='OPEN', entry_price=?, current_price=?, target_price=?, "
                    "pnl_percent=?, r_multiple=? WHERE id=?",
                    (res["fill_price"], res["current_price"], res["target"], res["net_pct"],
                     res["r_multiple"], row["id"]))
            else:
                storage.execute(
                    "UPDATE signals SET status=?, entry_price=?, current_price=?, target_price=?, exit_price=?, "
                    "exit_date=?, pnl_percent=?, r_multiple=? WHERE id=? AND status IN ('PENDING','OPEN')",
                    (st, res["fill_price"], res["exit_price"], res["target"], res["exit_price"],
                     res.get("exit_date"), res["net_pct"], res["r_multiple"], row["id"]))
                icon = {"TP": "✅", "SL": "⛔", "EXPIRED": "⌛", "INVALID": "⚠️"}[st]
                why = {"TP": "hedef", "SL": "stop", "EXPIRED": "süre doldu", "INVALID": "sahte kırılım / seviye kaybı"}[st]
                await self.tg.send_text(
                    f"{icon} {label} kapandı: {why}\nGiriş {res['fill_price']:.2f} → Çıkış {res['exit_price']:.2f} "
                    f"| Net {res['net_pct']:+.2f}% ({res['r_multiple']:+.2f}R)")
        STATE["last_pnl"] = now_ist().isoformat(timespec="seconds")

    # ---------------- ZAMANLAYICI ----------------
    async def scheduler(self):
        await asyncio.sleep(2)
        logger.info(f"🚀 Motor başladı | provider={self.provider.name} | TF={config.TIMEFRAMES} "
                    f"| DB={config.DB_PATH} | DRY_RUN={config.DRY_RUN}")
        last_intraday = last_pnl = datetime.min.replace(tzinfo=config.TZ)
        last_daily_date = None
        first = True

        while True:
            now = now_ist()
            try:
                # Saatlik (intraday) TF'ler: seans penceresinde periyodik
                if first or (in_session_window(now) and
                             now - last_intraday >= timedelta(minutes=config.INTRADAY_SCAN_EVERY_MIN)):
                    for tf in config.TIMEFRAMES:
                        if tf != "1d":
                            await self.scan(tf)
                    last_intraday = now

                # Günlük TF: kapanış verisi oturduktan sonra günde bir kez
                if "1d" in config.TIMEFRAMES and (first or (daily_close_ready(now) and last_daily_date != now.date())):
                    await self.scan("1d")
                    if daily_close_ready(now):
                        last_daily_date = now.date()

                if first or (in_session_window(now) and
                             now - last_pnl >= timedelta(minutes=config.PNL_EVERY_MIN)):
                    await self.update_pnl()
                    last_pnl = now
            except Exception as e:
                logger.exception(f"Zamanlayıcı hatası: {e}")
            first = False
            await asyncio.sleep(30)

    async def main(self):
        await asyncio.gather(self.tg.worker(), self.scheduler())


def run_web():
    logger.info(f"🌐 Dashboard: 0.0.0.0:{config.PORT}")
    serve(app, host="0.0.0.0", port=config.PORT, threads=4)


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(QuantBot().main())

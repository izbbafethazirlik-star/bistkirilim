"""SQLite katmanı (4. katman — performans kaydı). Asyncio döngüsü + web thread → threading.Lock.

Her sinyal hangi stratejiden ve hangi piyasa rejiminde üretildiğiyle birlikte saklanır,
böylece strateji sonuçları birbirine karışmaz.
"""
import sqlite3
import threading

import config

_lock = threading.Lock()

COLUMNS = {
    "symbol": "TEXT", "timeframe": "TEXT", "strategy": "TEXT", "regime": "TEXT",
    "bar_time": "TEXT", "entry_date": "TEXT",
    "signal_price": "REAL", "entry_price": "REAL", "current_price": "REAL",
    "stop_price": "REAL", "target_price": "REAL", "invalidation": "REAL",
    "quality": "REAL", "score": "REAL", "reasons": "TEXT",
    "status": "TEXT DEFAULT 'PENDING'", "skip_reason": "TEXT",
    "pnl_percent": "REAL DEFAULT 0.0", "r_multiple": "REAL",
    "exit_price": "REAL", "exit_date": "TEXT",
}
# PENDING → (sonraki bar açılışında) OPEN → TP | SL | INVALID | EXPIRED ; ya da SKIPPED
ACTIVE = ("PENDING", "OPEN")
CLOSED = ("TP", "SL", "INVALID", "EXPIRED")


def _connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(signals)")}
        for col, typ in COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {typ}")
        # Eski sürümlerden gelen kayıtlar
        conn.execute("UPDATE signals SET strategy='legacy' WHERE strategy IS NULL")
        conn.execute("UPDATE signals SET signal_price=entry_price WHERE signal_price IS NULL")
        conn.execute("DROP INDEX IF EXISTS ux_signal_bar")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_strat "
                     "ON signals(symbol, timeframe, strategy, bar_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_status ON signals(status)")


def execute(query, params=()) -> int:
    with _lock, _connect() as conn:
        return conn.execute(query, params).rowcount


def fetch(query, params=()):
    with _lock, _connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def strategy_stats():
    """Strateji bazında: işlem sayısı, kazanma oranı, ort. kazanç/kayıp, beklenen net getiri, toplam."""
    rows = fetch(f"SELECT strategy, pnl_percent, r_multiple FROM signals "
                 f"WHERE status IN ({','.join('?' * len(CLOSED))}) ORDER BY exit_date", CLOSED)
    from metrics import summarize
    groups = {}
    for r in rows:
        groups.setdefault(r["strategy"] or "legacy", []).append(r)
    return {k: summarize([x["pnl_percent"] or 0.0 for x in v], [x["r_multiple"] for x in v])
            for k, v in sorted(groups.items())}

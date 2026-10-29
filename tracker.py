"""Canlı pozisyon takibi — backtest ile birebir aynı simülasyonu (execution.simulate_trade) kullanır.

Sinyal → PENDING. Sinyal barından sonraki ilk saatlik barın açılışı giriş fiyatıdır (OPEN).
Sonra stop / hedef / sahte kırılım (invalidation) / süre dolumu kontrol edilir.
"""
import pandas as pd

import config
from execution import simulate_trade
from features import clean, to_local_index
from strategy import BAR_LEN


def _start_time(row):
    if row.get("bar_time"):
        t = pd.Timestamp(row["bar_time"])
        t = t.tz_localize(config.TZ) if t.tzinfo is None else t.tz_convert(config.TZ)
        if row["timeframe"] == "1d":
            return t.normalize() + pd.Timedelta(days=1)
        return t + BAR_LEN.get(row["timeframe"], BAR_LEN["1h"])
    return pd.Timestamp(row["entry_date"]).tz_localize(config.TZ)  # çok eski kayıtlar


def evaluate_position(row: dict, hourly: pd.DataFrame) -> dict:
    df = to_local_index(clean(hourly))
    if df.empty:
        return {}
    after = df[df.index >= _start_time(row)]
    signal_px = float(row.get("signal_price") or row["entry_price"])
    stop = row.get("stop_price")
    if stop is None:  # eski sürüm kaydı: sabit %4 stop
        stop = signal_px * 0.96
    res = simulate_trade(
        after["Open"].to_numpy(), after["High"].to_numpy(), after["Low"].to_numpy(),
        after["Close"].to_numpy(), list(after.index.date), signal_px, float(stop),
        invalidation=row.get("invalidation"),
        # Eski kayıtlar zaten açılmıştı; boşluk kuralı uygulanmaz
        max_gap_pct=1e9 if row.get("strategy") == "legacy" else None,
    )
    if res["status"] not in ("PENDING", "SKIPPED") and "exit_idx" in res:
        res["exit_date"] = after.index[res["exit_idx"]].strftime("%Y-%m-%d %H:%M")
    return res

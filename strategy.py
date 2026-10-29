"""Canlı analiz: veri doğrulama → özellikler → rejim → stratejiler → risk kontrolü → grafik."""
import io
import logging
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")  # sunucuda ekran yok
import mplfinance as mpf
import pandas as pd

import config
from features import MIN_BARS, build_features, clean, to_local_index
from strategies import evaluate_bar

logger = logging.getLogger("BIST_QUANT")
BAR_LEN = {"1h": timedelta(hours=1), "1d": timedelta(days=1)}


def drop_incomplete_bar(df: pd.DataFrame, interval: str, now: datetime) -> pd.DataFrame:
    """Henüz kapanmamış (veya Yahoo gecikmesi yüzünden eksik) son barı atar."""
    if df.empty:
        return df
    delay = timedelta(minutes=config.DATA_DELAY_MIN)
    last = df.index[-1]
    if interval == "1d":
        h, m = config.MARKET_CLOSE
        complete = now >= last.replace(hour=h, minute=m, second=0, microsecond=0) + delay
    else:
        complete = now >= last + BAR_LEN[interval] + delay
    return df if complete else df.iloc[:-1]


def prepare(df: pd.DataFrame, interval: str, now: datetime | None = None):
    """1. katman: veri doğrulama. Yetersiz/eksik veri → None."""
    df = clean(df)
    if df.empty:
        return None
    df = to_local_index(df)
    if now is not None:
        df = drop_incomplete_bar(df, interval, now)
    if len(df) < MIN_BARS:
        return None
    return build_features(df, interval)


def analyze(df: pd.DataFrame, symbol: str, interval: str, now: datetime, enabled=None) -> list:
    F = prepare(df, interval, now)
    if F is None:
        return []
    i = len(F) - 1
    out = []
    for cand in evaluate_bar(F, i, enabled):
        out.append({
            "symbol": symbol, "interval": interval, "bar_time": F.df.index[i].isoformat(),
            "price": cand.entry_ref, "cand": cand, "rsi": float(F.a["RSI"][i]),
            "df": F.df.tail(80),
        })
    return out


def generate_chart(sig: dict) -> bytes:
    df, cand = sig["df"], sig["cand"]
    buf = io.BytesIO()
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", rc={"font.size": 7})
    title = f"{sig['symbol']} ({sig['interval']}) | {cand.strategy} | Q:{cand.quality:.0f}"
    apds = [mpf.make_addplot(df["EMA20"], color="cyan", width=0.8),
            mpf.make_addplot(df["EMA50"], color="orange", width=0.8)]
    plot_df = df.copy()
    plot_df.index = plot_df.index.tz_localize(None)
    lo, hi = plot_df["Low"].min(), plot_df["High"].max()
    levels = [(cand.level, "white"), (cand.stop, "red"), (cand.target, "lime")]
    levels = [(y, col) for y, col in levels if lo * 0.8 <= y <= hi * 1.2]
    extra = {}
    if levels:
        extra["hlines"] = dict(hlines=[y for y, _ in levels], colors=[col for _, col in levels],
                               linestyle="--", linewidths=0.7)
    mpf.plot(
        plot_df, type="candle", style=style, addplot=apds, title=title, volume=True,
        savefig=dict(fname=buf, dpi=100, bbox_inches="tight"), closefig=True, **extra,
    )
    return buf.getvalue()

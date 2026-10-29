"""1. Katman — Veri doğrulama + özellik hesaplama.

Bütün özellikler NEDENSELDİR: i. bardaki değer yalnızca 0..i barlarını kullanır.
Böylece aynı özellik seti hem canlıda (i = son bar) hem backtest'te (her i) kullanılır
ve geçmiş testte "geleceği görme" (lookahead) hatası oluşmaz. tests/ içinde doğrulanır.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config
from indicators import atr, bollinger, ema, rolling_pct_rank, rsi

OHLCV = ["Open", "High", "Low", "Close", "Volume"]
MIN_BARS = 150  # EMA50 + 120 barlık sıkışma yüzdeliği için


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Boş/bozuk satırları atar (toplu indirmede başka hisselerin saatlerinden gelen NaN'ler vb.)."""
    if df is None or df.empty or any(c not in df.columns for c in OHLCV):
        return pd.DataFrame(columns=OHLCV)
    df = df[OHLCV].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df["Volume"] = df["Volume"].fillna(0)
    df = df[(df["Close"] > 0) & (df["High"] >= df["Low"])]
    return df[~df.index.duplicated(keep="last")].sort_index()


def to_local_index(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize(config.TZ) if idx.tz is None else idx.tz_convert(config.TZ)
    df = df.copy()
    df.index = idx
    return df


@dataclass
class Features:
    df: pd.DataFrame          # gösterge kolonları eklenmiş DataFrame (grafik için)
    a: dict                   # kolon adı -> numpy dizisi (hızlı erişim)
    interval: str

    def __len__(self):
        return len(self.df)


def build_features(df: pd.DataFrame, interval: str) -> Features:
    df = df.copy()
    o, h, l, c, v = (df[k] for k in OHLCV)
    df["EMA20"] = ema(c, 20)
    df["EMA50"] = ema(c, 50)
    df["EMA50_SLOPE"] = df["EMA50"] - df["EMA50"].shift(5)
    df["RSI"] = rsi(c, 14)
    df["ATR"] = atr(h, l, c, 14)
    df["BB_LOW"], df["BB_MID"], df["BB_UP"], df["BBW"] = bollinger(c, 20, 2.0)
    df["BBW_RANK"] = rolling_pct_rank(df["BBW"], 120)
    df["VOL_MA"] = v.shift(1).rolling(20).mean()        # mevcut bar hariç
    df["RVOL"] = v / df["VOL_MA"].replace(0, np.nan)
    # Direnç = önceki N barın en yükseği (mevcut bar hariç); sahte kırılım = üstüne çıkıp altında kapanış
    n = config.BREAKOUT_LOOKBACK
    df["PRIOR_HIGH"] = h.shift(1).rolling(n).max()
    df["FAILED_BO"] = ((h > df["PRIOR_HIGH"]) & (c <= df["PRIOR_HIGH"])).astype(float)
    rng = (h - l).replace(0, np.nan)
    df["CLV"] = ((c - l) / rng).fillna(0.5)              # kapanışın mum içindeki konumu (0 dip, 1 tepe)

    # Ortalama günlük TL işlem hacmi (son 20 işlem günü)
    tl = c * v
    if interval == "1d":
        df["TURNOVER"] = tl.rolling(20, min_periods=5).mean()   # bar kapandığında bugün de kesin
    else:
        # Gün içinde bugünün toplamı henüz belli değil → yalnızca TAMAMLANMIŞ önceki günler
        dates = pd.Series(df.index.date, index=df.index)
        daily = tl.groupby(dates.values).sum()
        daily_avg = daily.rolling(20, min_periods=5).mean().shift(1)
        df["TURNOVER"] = dates.map(daily_avg).astype(float).values

    a = {col: df[col].to_numpy(dtype=float) for col in df.columns}
    return Features(df=df, a=a, interval=interval)

"""Bağımlılıksız indikatörler (TradingView ile aynı tanımlar).

pandas_ta artık PyPI'dan kurulamıyor / numpy 2 ile uyumsuz olduğu için
EMA ve RSI burada saf pandas/numpy ile hesaplanır.
"""
import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    """TradingView ta.ema: ilk değer SMA(length) ile tohumlanır, sonra alpha=2/(n+1)."""
    s = series.astype(float)
    out = pd.Series(np.nan, index=s.index)
    values = s.to_numpy()
    if len(values) < length:
        return out
    alpha = 2.0 / (length + 1)
    res = np.full(len(values), np.nan)
    res[length - 1] = values[:length].mean()
    for i in range(length, len(values)):
        res[i] = alpha * values[i] + (1 - alpha) * res[i - 1]
    out[:] = res
    return out


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder hareketli ortalaması (TradingView ta.rma): SMA tohum + alpha=1/n."""
    values = series.astype(float).to_numpy()
    res = np.full(len(values), np.nan)
    if len(values) < length:
        return pd.Series(res, index=series.index)
    res[length - 1] = values[:length].mean()
    alpha = 1.0 / length
    for i in range(length, len(values)):
        res[i] = alpha * values[i] + (1 - alpha) * res[i - 1]
    return pd.Series(res, index=series.index)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder ATR (TradingView ta.atr)."""
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return rma(tr, length)


def bollinger(close: pd.Series, length: int = 20, mult: float = 2.0):
    """(alt, orta, üst, genişlik=(üst-alt)/orta). TradingView gibi popülasyon std (ddof=0)."""
    mid = close.rolling(length).mean()
    sd = close.rolling(length).std(ddof=0)
    upper, lower = mid + mult * sd, mid - mult * sd
    return lower, mid, upper, (upper - lower) / mid


def rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    """Son değerin, son `window` değer içindeki yüzdelik sırası (0–1). Yalnızca geçmişi kullanır."""
    return series.rolling(window).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI (TradingView ta.rsi ile aynı)."""
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0).iloc[1:]
    loss = (-delta.clip(upper=0)).iloc[1:]
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    out[(avg_loss == 0) & avg_gain.notna()] = 100.0
    out[(avg_loss == 0) & (avg_gain == 0)] = 50.0
    return out.reindex(close.index)

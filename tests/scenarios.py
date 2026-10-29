"""Test senaryoları için deterministik sentetik günlük veri üreticileri."""
import numpy as np
import pandas as pd

import config


def bars(rows, start="2025-01-02"):
    """rows: (open, high, low, close, volume) listesi → iş günü indeksli DataFrame."""
    idx = pd.bdate_range(start, periods=len(rows), tz=config.TZ)
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def wave(n, start, end, amp=1.0, vol=1_000_000, period=6):
    out, prev = [], start
    for k in range(n):
        base = start + (end - start) * k / max(1, n - 1)
        c = base + amp * np.sin(2 * np.pi * k / period)
        o = prev
        out.append((o, max(o, c) + 0.6 * amp, min(o, c) - 0.6 * amp, c, vol))
        prev = c
    return out


def breakout_scenario():
    rows = wave(150, 60, 95, amp=1.2)
    # 30 barlık yatay bant: tepe ~100'e 3 kez dokunuyor
    prev = rows[-1][3]
    for k in range(30):
        c = 97 + 1.5 * np.sin(2 * np.pi * k / 10)
        hi = 100.0 if k % 10 == 2 else max(prev, c) + 0.8
        rows.append((prev, hi, min(prev, c) - 0.8, c, 900_000))
        prev = c
    # Kırılım barı: güçlü kapanış + 3x hacim
    rows.append((prev, 101.9, prev - 0.3, 101.7, 3_000_000))
    return rows


def pullback_scenario():
    rows = wave(170, 50, 100, amp=0.8, period=8)
    prev = rows[-1][3]
    for c in (98.0, 96.5, 95.6, 95.9):                      # EMA20'ye geri çekilme
        rows.append((prev, max(prev, c) + 0.4, min(prev, c) - 0.5, c, 700_000))
        prev = c
    rows.append((prev, 97.9, prev - 0.2, 97.8, 1_600_000))   # yeniden yükseliş + hacim
    return rows


def support_scenario():
    rows = wave(160, 100, 100, amp=4.0, period=20)           # 96–104 bandında yatay
    prev = rows[-1][3]
    for c in (98.0, 96.8, 96.2, 95.9):                      # desteğe iniş, RSI düşük
        rows.append((prev, max(prev, c) + 0.3, min(prev, c) - 0.6, c, 900_000))
        prev = c
    rows.append((prev, 97.6, prev - 0.2, 97.5, 1_400_000))   # dönüş mumu
    return rows


def squeeze_scenario():
    rows = wave(140, 60, 80, amp=2.5, period=10)
    prev = rows[-1][3]
    for k in range(25):                                      # dar bant: volatilite sıkışması
        c = 80 + 0.25 * np.sin(2 * np.pi * k / 5)
        rows.append((prev, max(prev, c) + 0.15, min(prev, c) - 0.15, c, 800_000))
        prev = c
    rows.append((prev, 81.6, prev - 0.05, 81.5, 2_500_000))
    return rows

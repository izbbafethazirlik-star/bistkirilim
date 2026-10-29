"""2. Katman — Piyasa rejimi tespiti.

UP      : EMA20 > EMA50, fiyat EMA50 üstünde, EMA50 eğimi pozitif
DOWN    : EMA20 < EMA50, fiyat EMA50 altında, EMA50 eğimi negatif
SQUEEZE : sinyal barından ÖNCEKİ barda Bollinger genişliği son 120 barın en dar diliminde
RANGE   : diğer durumlar (yatay / kararsız)
"""
import math

import config
from features import Features

UP, DOWN, RANGE, SQUEEZE = "UP", "DOWN", "RANGE", "SQUEEZE"
LABELS_TR = {UP: "Yükselen trend", DOWN: "Düşen trend", RANGE: "Yatay", SQUEEZE: "Sıkışma"}


def regime_at(F: Features, i: int) -> str:
    a = F.a
    if i >= 1 and not math.isnan(a["BBW_RANK"][i - 1]) and a["BBW_RANK"][i - 1] <= config.SQUEEZE_RANK:
        return SQUEEZE
    e20, e50, slope, c = a["EMA20"][i], a["EMA50"][i], a["EMA50_SLOPE"][i], a["Close"][i]
    if any(math.isnan(x) for x in (e20, e50, slope)):
        return RANGE
    if e20 > e50 and c > e50 and slope > 0:
        return UP
    if e20 < e50 and c < e50 and slope < 0:
        return DOWN
    return RANGE

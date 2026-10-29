"""Strateji modülleri + 3. katman risk/sinyal kontrolü.

Her strateji bağımsızdır ve `check(F, i) -> Candidate | None` imzasına sahiptir.
Yalnızca 0..i barlarını okur (lookahead yok). Bir sinyal, i. barın KAPANIŞINDA oluşur;
işlem bir sonraki barın açılışında yapılır (execution.simulate_trade).

Strateji listesi (doküman sırasıyla):
  breakout         — Gerçek direnç kırılımı (+ sahte kırılım kalite cezaları)
  breakout_retest  — Kırılım sonrası yeniden test (sahte kırılım filtresinin giriş tarafı)
  trend_pullback   — Trend devamı / EMA20'ye geri çekilme
  support_bounce   — Destek bölgesinden dönüş
  squeeze          — Volatilite sıkışması sonrası kırılım
"""
import math
from dataclasses import dataclass, field

import numpy as np

import config
from features import Features
from regime import DOWN, RANGE, SQUEEZE, UP, regime_at

NAMES_TR = {
    "breakout": "Direnç Kırılımı",
    "breakout_retest": "Kırılım Retesti",
    "trend_pullback": "Trend Devamı (Geri Çekilme)",
    "support_bounce": "Destekten Dönüş",
    "squeeze": "Volatilite Sıkışması",
}


@dataclass
class Candidate:
    strategy: str
    stop: float
    level: float                      # kırılan direnç / destek vb. referans seviye
    invalidation: float | None        # bu seviyenin ALTINDA kapanış → sinyal iptal (sahte kırılım)
    quality: float
    reasons: list = field(default_factory=list)
    regime: str = ""
    entry_ref: float = 0.0            # sinyal barının kapanışı
    target: float = 0.0               # entry_ref + TARGET_R × risk (bilgi amaçlı)

    @property
    def risk_pct(self):
        return (self.entry_ref - self.stop) / self.entry_ref * 100


def _ok(*xs):
    return all(x is not None and not math.isnan(x) for x in xs)


def _bull_confirm(a, i):
    """Yeniden yükseliş teyidi: yeşil mum ve önceki barın tepesi üzerinde kapanış."""
    return a["Close"][i] > a["Open"][i] and a["Close"][i] > a["High"][i - 1]


# ---------------------------------------------------------------- 1) Direnç kırılımı
def breakout(F: Features, i: int):
    a, n = F.a, config.BREAKOUT_LOOKBACK
    if i < n + 1:
        return None
    c, h, lo, atr, res = a["Close"][i], a["High"][i], a["Low"][i], a["ATR"][i], a["PRIOR_HIGH"][i]
    rvol, rsi_, clv = a["RVOL"][i], a["RSI"][i], a["CLV"][i]
    if not _ok(atr, res, rvol, rsi_):
        return None
    # Kapanış teyidi: direncin belirgin şekilde üstünde ve TAZE kırılım (önceki kapanış altında)
    if not (c > res + 0.1 * atr and a["Close"][i - 1] <= res):
        return None
    # Gerçek seviye: direnç bölgesi en az N kez test edilmiş olmalı
    window_h = a["High"][i - n:i]
    touches = int(np.sum(window_h >= res - 0.5 * atr))
    if touches < config.BREAKOUT_MIN_TOUCHES:
        return None
    # Hacim ve momentum teyidi
    if rvol < config.BREAKOUT_RVOL or not (config.BREAKOUT_RSI_MIN <= rsi_ <= config.BREAKOUT_RSI_MAX):
        return None
    # Volatilite filtresi: aşırı uzamış mum / seviyeden çok uzak giriş reddedilir
    if (h - lo) > 3 * atr or (c - res) > 1.5 * atr:
        return None

    q, reasons = 50.0, [f"Direnç {res:.2f} ({touches} test) kapanışla kırıldı",
                        f"Göreli hacim x{rvol:.1f}", f"RSI {rsi_:.0f}"]
    q += min(20, (rvol - config.BREAKOUT_RVOL) * 20)
    q += min(10, (touches - config.BREAKOUT_MIN_TOUCHES) * 5)
    if clv >= 0.7:
        q += 15; reasons.append("Güçlü kapanış (mumun üst bölgesi)")
    elif clv < 0.5:
        q -= 15; reasons.append("Uzun üst fitil (satış baskısı)")
    q += _false_breakout_penalty(F, i, reasons)
    return Candidate("breakout", stop=res - 1.0 * atr, level=res,
                     invalidation=res - 0.25 * atr, quality=q, reasons=reasons)


def _false_breakout_penalty(F, i, reasons):
    """5) Sahte kırılım filtresi: yakın geçmişte zirve üstüne çıkıp altında kapanan mumlar."""
    n = config.BREAKOUT_LOOKBACK
    fails = int(np.nansum(F.a["FAILED_BO"][max(0, i - n):i]))
    if fails:
        reasons.append(f"Son {n} barda {fails} başarısız kırılım denemesi")
    return -10.0 * fails


# ---------------------------------------------------------------- 5b) Kırılım retesti
def breakout_retest(F: Features, i: int):
    a, n, w = F.a, config.BREAKOUT_LOOKBACK, config.RETEST_WINDOW
    if i < n + w + 1:
        return None
    for k in range(i - 1, i - w - 1, -1):                 # en yakın geçerli kırılım barı
        res_k, atr_k = a["PRIOR_HIGH"][k], a["ATR"][k]
        if not _ok(res_k, atr_k, a["RVOL"][k]):
            continue
        if a["Close"][k] > res_k + 0.1 * atr_k and a["Close"][k - 1] <= res_k and a["RVOL"][k] >= config.BREAKOUT_RVOL:
            break
    else:
        return None
    level = res_k
    after = slice(k + 1, i + 1)
    # Kırılımdan sonra seviyenin altında KAPANIŞ olduysa bu sahte kırılımdır → sinyal yok
    if np.any(a["Close"][after] < level - 0.25 * atr_k):
        return None
    # Retest: fiyat seviyeye geri gelmiş olmalı
    lows = a["Low"][after]
    if not np.any(lows <= level + 0.3 * atr_k):
        return None
    if not (_bull_confirm(a, i) and a["Close"][i] > level):
        return None

    atr = a["ATR"][i]
    q, reasons = 60.0, [f"{level:.2f} kırılımı {i - k} bar önce", "Seviye yeniden test edildi ve tuttu",
                        "Yeniden yükseliş teyidi"]
    j = k + 1 + int(np.argmin(lows))
    if a["Volume"][j] < a["Volume"][k]:
        q += 10; reasons.append("Geri çekilme düşük hacimli")
    if a["CLV"][i] >= 0.7:
        q += 10
    q += _false_breakout_penalty(F, k, reasons)
    return Candidate("breakout_retest", stop=float(lows.min()) - 0.25 * atr, level=level,
                     invalidation=level - 0.25 * atr, quality=q, reasons=reasons)


# ---------------------------------------------------------------- 2) Trend devamı
def trend_pullback(F: Features, i: int):
    a, w = F.a, 5
    if i < 60:
        return None
    # Trend şartı (rejim SQUEEZE etiketli olsa bile)
    if not (a["EMA20"][i] > a["EMA50"][i] and a["Close"][i] > a["EMA50"][i] and a["EMA50_SLOPE"][i] > 0):
        return None
    win = slice(i - w, i)
    e20, e50, atr = a["EMA20"][win], a["EMA50"][win], a["ATR"][win]
    if np.isnan(e50).any():
        return None
    touched = np.any(a["Low"][win] <= e20 + 0.25 * atr)          # EMA20'ye geri çekildi
    held = np.all(a["Close"][win] > e50)                          # ama EMA50 üstünde kaldı
    if not (touched and held):
        return None
    rvol, rsi_ = a["RVOL"][i], a["RSI"][i]
    if not _ok(rvol, rsi_):
        return None
    if not (_bull_confirm(a, i) and a["Close"][i] > a["EMA20"][i]):
        return None
    if rvol < config.PULLBACK_RVOL or not (40 <= rsi_ <= 65):
        return None

    q, reasons = 60.0, ["EMA20'ye geri çekilme, EMA50 korundu", "Yeniden yükseliş teyidi",
                        f"Göreli hacim x{rvol:.1f}", f"RSI {rsi_:.0f}"]
    q += min(15, (rvol - config.PULLBACK_RVOL) * 15)
    if a["CLV"][i] >= 0.7:
        q += 10
    stop = float(a["Low"][i - w:i + 1].min()) - 0.25 * a["ATR"][i]
    return Candidate("trend_pullback", stop=stop, level=float(a["EMA20"][i]),
                     invalidation=float(a["EMA50"][i]), quality=q, reasons=reasons)


# ---------------------------------------------------------------- 3) Destekten dönüş
def support_bounce(F: Features, i: int):
    a, n = F.a, config.SUPPORT_LOOKBACK
    if i < n + 6:
        return None
    atr = a["ATR"][i]
    zone_lows = a["Low"][i - n:i - 3]
    sup = float(zone_lows.min())
    touches = int(np.sum(zone_lows <= sup + 0.5 * atr))
    if touches < 2 or not _ok(atr):
        return None
    recent = slice(i - 3, i + 1)
    if not np.any(a["Low"][recent] <= sup + 0.5 * atr):            # destek yeniden test edildi
        return None
    if np.any(a["Close"][recent] < sup - 0.25 * atr):              # destek altında kapanış → iptal
        return None
    rs = a["RSI"]
    if not _ok(rs[i], rs[i - 1]) or not (np.nanmin(rs[i - 5:i]) < 40 and rs[i] > rs[i - 1] and rs[i] >= 35):
        return None
    if not _bull_confirm(a, i):
        return None

    q, reasons = 55.0, [f"Destek {sup:.2f} ({touches} test)", f"RSI toparlanıyor ({rs[i]:.0f})",
                        "Dönüş mumu teyidi"]
    q += min(15, (touches - 2) * 5)
    if a["CLV"][i] >= 0.7:
        q += 10
    if _ok(a["RVOL"][i]) and a["RVOL"][i] >= 1.2:
        q += 10; reasons.append(f"Göreli hacim x{a['RVOL'][i]:.1f}")
    return Candidate("support_bounce", stop=sup - 0.5 * atr, level=sup,
                     invalidation=sup - 0.1 * atr, quality=q, reasons=reasons)


# ---------------------------------------------------------------- 4) Volatilite sıkışması
def squeeze(F: Features, i: int):
    a, box = F.a, 10
    if i < 130:
        return None
    if not _ok(a["BBW_RANK"][i - 1], a["BB_UP"][i], a["RVOL"][i], a["ATR"][i]):
        return None
    if a["BBW_RANK"][i - 1] > config.SQUEEZE_RANK:
        return None
    box_hi, box_lo = float(a["High"][i - box:i].max()), float(a["Low"][i - box:i].min())
    c, atr = a["Close"][i], a["ATR"][i]
    if not (c > a["BB_UP"][i] and c > box_hi and c > a["Open"][i]):
        return None
    if a["RVOL"][i] < config.SQUEEZE_RVOL or a["CLV"][i] < 0.6:    # hacim + kapanış teyidi şart
        return None
    reasons = [f"BB genişliği son 120 barın en dar %{config.SQUEEZE_RANK * 100:.0f}'inde",
               f"{box} barlık kutu ({box_hi:.2f}) yukarı kırıldı", f"Göreli hacim x{a['RVOL'][i]:.1f}"]
    q = 60.0 + min(20, (a["RVOL"][i] - config.SQUEEZE_RVOL) * 20)
    q += _false_breakout_penalty(F, i, reasons)
    return Candidate("squeeze", stop=max(box_lo - 0.1 * atr, c - 2.5 * atr), level=box_hi,
                     invalidation=box_hi - 0.25 * atr, quality=q, reasons=reasons)


# ---------------------------------------------------------------- Yönlendirme + risk kontrolü
STRATEGIES = {
    #  ad               fonksiyon         izin verilen rejimler
    "breakout":        (breakout,        {UP, RANGE, SQUEEZE}),
    "breakout_retest": (breakout_retest, {UP, RANGE, SQUEEZE}),
    # Sakin trendlerde geri çekilme dar bantta olur → SQUEEZE etiketi alabilir; trend koşulu
    # fonksiyon içinde ayrıca doğrulanır.
    "trend_pullback":  (trend_pullback,  {UP, SQUEEZE}),
    # Dönüş tanımı gereği düşüşten sonra gelir; rejim kaydedilir ve backtest'te rejime göre ölçülür.
    "support_bounce":  (support_bounce,  {UP, RANGE, DOWN, SQUEEZE}),
    "squeeze":         (squeeze,         {SQUEEZE}),
}


def risk_check(F: Features, i: int, cand: Candidate):
    """Likidite · volatilite · stop mesafesi · risk/getiri · kalite. (ok, sebep)"""
    a = F.a
    c, atr, turnover = a["Close"][i], a["ATR"][i], a["TURNOVER"][i]
    if not _ok(turnover) or turnover < config.MIN_AVG_TURNOVER_TL:
        return False, "likidite"
    atr_pct = atr / c * 100
    if not (config.ATR_PCT_MIN <= atr_pct <= config.ATR_PCT_MAX):
        return False, "volatilite"
    if cand.stop >= c:
        return False, "stop"
    risk_pct = (c - cand.stop) / c * 100
    if not (config.RISK_MIN_PCT <= risk_pct <= config.RISK_MAX_PCT):
        return False, "stop mesafesi"
    if cand.quality < config.MIN_QUALITY:
        return False, "kalite"
    return True, ""


def evaluate_bar(F: Features, i: int, enabled=None):
    """i. bar kapanışında tüm etkin stratejileri çalıştırır, risk kontrolünden geçenleri döndürür."""
    enabled = enabled or config.ENABLED_STRATEGIES
    reg = regime_at(F, i)
    out = []
    for name in enabled:
        func, allowed = STRATEGIES[name]
        if reg not in allowed:
            continue
        cand = func(F, i)
        if cand is None:
            continue
        cand.regime = reg
        cand.quality = max(0.0, min(100.0, cand.quality))
        cand.entry_ref = float(F.a["Close"][i])
        ok, _ = risk_check(F, i, cand)
        if ok:
            cand.target = cand.entry_ref + config.TARGET_R * (cand.entry_ref - cand.stop)
            out.append(cand)
    return out

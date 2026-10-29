"""Ortak işlem simülasyonu — canlı takip (tracker) ve backtest AYNI fonksiyonu kullanır.

Gerçekçilik varsayımları:
  * Sinyal bar kapanışında oluşur; alım bir SONRAKİ barın açılışından yapılır.
  * Açılış sinyal fiyatının MAX_ENTRY_GAP_PCT üzerinde ise (ör. tavan/boşluklu açılış) işlem
    yapılmaz → SKIPPED. Açılış stop'un altındaysa da işlem yapılmaz.
  * Hedef, gerçekleşen giriş fiyatından yeniden hesaplanır (giriş + R × risk).
  * Aynı barda hem stop hem hedef görülürse önce STOP varsayılır (muhafazakâr).
  * Boşluklu açılışlarda çıkış, stop/hedef fiyatından değil AÇILIŞ fiyatından olur.
  * Seviye altında kapanış (invalidation) → sahte kırılım, kapanıştan çıkılır.
  * Komisyon + kayma her iki yönde düşülür.
"""
import config


def round_trip_cost_pct():
    return 2 * (config.COMMISSION_PCT + config.SLIPPAGE_PCT)


def simulate_trade(o, h, l, c, dates, signal_close, stop, invalidation=None,
                   target_r=None, max_days=None, max_gap_pct=None):
    """o/h/l/c: sinyal barından SONRAKİ barların dizileri; dates: her barın takvim günü."""
    target_r = config.TARGET_R if target_r is None else target_r
    max_days = config.MAX_HOLD_DAYS if max_days is None else max_days
    max_gap_pct = config.MAX_ENTRY_GAP_PCT if max_gap_pct is None else max_gap_pct
    cost = round_trip_cost_pct()

    if len(o) == 0:
        return {"status": "PENDING"}
    fill = float(o[0])
    if fill > signal_close * (1 + max_gap_pct / 100):
        return {"status": "SKIPPED", "reason": "boşluklu açılış", "fill_price": fill, "exit_idx": 0}
    if fill <= stop:
        return {"status": "SKIPPED", "reason": "açılış stop altında", "fill_price": fill, "exit_idx": 0}

    risk = fill - stop
    target = fill + target_r * risk

    def result(status, px, idx):
        gross = (px / fill - 1) * 100
        return {"status": status, "fill_price": fill, "exit_price": float(px), "current_price": float(px),
                "target": target, "exit_idx": idx, "gross_pct": gross, "net_pct": gross - cost,
                "r_multiple": (px - fill) / risk}

    day_count = 0
    for j in range(len(o)):
        if j == 0 or dates[j] != dates[j - 1]:
            if day_count >= max_days:              # süre doldu → yeni günün açılışında çık
                return result("EXPIRED", o[j], j)
            day_count += 1
        if j > 0 and o[j] <= stop:
            return result("SL", o[j], j)
        if l[j] <= stop:
            return result("SL", stop, j)
        if j > 0 and o[j] >= target:
            return result("TP", o[j], j)
        if h[j] >= target:
            return result("TP", target, j)
        if invalidation is not None and c[j] < invalidation:
            return result("INVALID", c[j], j)

    res = result("OPEN", c[-1], len(o) - 1)
    res.pop("exit_price")
    return res

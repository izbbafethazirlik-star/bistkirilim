"""Performans ölçütleri (canlı panel ve backtest ortak)."""
import math


def max_drawdown(returns_pct):
    """İşlemler sırayla, her biri sabit sermaye payıyla açılıyormuş gibi kümülatif getiri eğrisinin
    zirveden en büyük düşüşü (yüzde puan). Basit ve karşılaştırma için tutarlı bir yaklaşım."""
    peak = cum = dd = 0.0
    for r in returns_pct:
        cum += r
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return dd


def summarize(net_returns_pct, r_multiples=None):
    rets = [float(x) for x in net_returns_pct if x is not None and not math.isnan(x)]
    n = len(rets)
    if n == 0:
        return {"n": 0}
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_win, gross_loss = sum(wins), -sum(losses)
    rs = [float(r) for r in (r_multiples or []) if r is not None and not math.isnan(r)]
    return {
        "n": n,
        "win_rate": 100 * len(wins) / n,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": (avg_win / -avg_loss) if avg_loss < 0 else float("inf"),
        "expectancy": sum(rets) / n,                       # işlem başına beklenen NET getiri (%)
        "expectancy_r": (sum(rs) / len(rs)) if rs else float("nan"),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "total": sum(rets),
        "max_dd": max_drawdown(rets),
    }

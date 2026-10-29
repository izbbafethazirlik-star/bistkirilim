"""Geçmiş test — canlı botla AYNI strateji (strategies.evaluate_bar) ve AYNI işlem
simülasyonu (execution.simulate_trade) kullanılır.

Örnekler:
  python backtest.py --interval 1d --period 5y
  python backtest.py --interval 1h --period 2y --strategies breakout,trend_pullback
  python backtest.py --csv-dir veriler/ --interval 1d     # SEMBOL.csv dosyalarından (Date,Open,High,Low,Close,Volume)

Yöntem:
  * Sinyal i. barın kapanışında, giriş (i+1). barın açılışında. Boşluklu/tavan açılışta işlem yok.
  * Bir hisse + strateji için aynı anda tek pozisyon.
  * Dönem, tarihe göre ikiye bölünür: IN-SAMPLE (ilk %70) ve OUT-OF-SAMPLE (son %30).
    Parametreleri yalnızca IN-SAMPLE sonuçlarına bakarak ayarlayın; OUT-OF-SAMPLE'ı en sonda,
    bir kez doğrulama için kullanın. Aksi halde geçmişe aşırı uyum (overfitting) olur.
  * Maliyet: gidiş-dönüş 2 × (COMMISSION_PCT + SLIPPAGE_PCT).

Bilinen sınırlamalar:
  * Sembol listesi BUGÜNÜN listesi → işlemden kaldırılmış hisseler yok (hayatta kalma yanlılığı).
  * Günlük barlarda gün içi sıralama bilinmez; aynı barda stop ve hedef → stop varsayılır.
  * Getiriler işlem başına; portföy sermaye kısıtı / eşzamanlı pozisyon sınırı modellenmez.
"""
import warnings
# yfinance, pandas 3.1+ altında zararsız "inplace deprecated" uyarıları üretiyor; logları boğmasın
warnings.filterwarnings("ignore", message=r".*inplace keyword.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

import config
from execution import simulate_trade
from features import MIN_BARS, build_features, clean, to_local_index
from metrics import summarize
from strategies import STRATEGIES, evaluate_bar

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
log = logging.getLogger("backtest")


def backtest_symbol(symbol, df, interval, strategies):
    df = clean(df)
    if df.empty:
        return []
    df = to_local_index(df)
    if len(df) < MIN_BARS + 2:
        return []
    F = build_features(df, interval)
    a, idx = F.a, F.df.index
    dates = list(idx.date)
    busy_until = {s: -1 for s in strategies}
    trades = []

    for i in range(MIN_BARS, len(F) - 1):
        free = [s for s in strategies if i > busy_until[s]]
        if not free:
            continue
        for cand in evaluate_bar(F, i, free):
            j0 = i + 1
            res = simulate_trade(a["Open"][j0:], a["High"][j0:], a["Low"][j0:], a["Close"][j0:],
                                 dates[j0:], cand.entry_ref, cand.stop, cand.invalidation)
            st = res["status"]
            exit_i = j0 + res.get("exit_idx", 0)
            trades.append({
                "symbol": symbol, "strategy": cand.strategy, "regime": cand.regime,
                "quality": round(cand.quality, 1), "signal_time": idx[i].isoformat(),
                "entry_time": idx[j0].isoformat(), "exit_time": idx[exit_i].isoformat(),
                "status": st, "skip_reason": res.get("reason", ""),
                "signal_price": cand.entry_ref, "fill": res.get("fill_price"),
                "stop": cand.stop, "exit": res.get("exit_price", res.get("current_price")),
                "net_pct": res.get("net_pct"), "r": res.get("r_multiple"),
                "bars_held": exit_i - j0 + 1,
            })
            busy_until[cand.strategy] = exit_i if st != "SKIPPED" else i
    return trades


def load_csv_dir(path):
    frames = {}
    for f in sorted(Path(path).glob("*.csv")):
        df = pd.read_csv(f)
        date_col = next(c for c in df.columns if c.lower() in ("date", "datetime", "time", "tarih"))
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
        df.columns = [c.capitalize() for c in df.columns]
        sym = f.stem.upper()
        frames[sym if sym.endswith(".IS") else f"{sym}.IS"] = df
    return frames


async def load_yahoo(symbols, period, interval):
    from data_source import get_provider
    provider = get_provider()
    frames = {}
    for k in range(0, len(symbols), config.BATCH_SIZE):
        batch = symbols[k:k + config.BATCH_SIZE]
        frames.update(await provider.fetch(batch, period, interval))
        log.info(f"İndirildi: {len(frames)}/{len(symbols)}")
        await asyncio.sleep(1)
    return frames


def fmt_row(name, s):
    if not s.get("n"):
        return f"{name:<34}{'0':>6}"
    return (f"{name:<34}{s['n']:>6}{s['win_rate']:>8.1f}{s['avg_win']:>9.2f}{s['avg_loss']:>9.2f}"
            f"{s['payoff']:>8.2f}{s['expectancy']:>10.3f}{s['expectancy_r']:>8.2f}"
            f"{s['profit_factor']:>7.2f}{s['total']:>9.1f}{s['max_dd']:>9.1f}")


HEADER = (f"{'':<34}{'İşlem':>6}{'Kaz%':>8}{'OrtKaz':>9}{'OrtKay':>9}{'Oran':>8}"
          f"{'Bekl.%':>10}{'Ort.R':>8}{'PF':>7}{'Toplam':>9}{'MaxDD':>9}")


def report(trades, split):
    closed = [t for t in trades if t["status"] in ("TP", "SL", "INVALID", "EXPIRED")]
    if not closed:
        print("Kapanan işlem yok.")
        return {}
    closed.sort(key=lambda t: t["exit_time"])
    times = sorted(t["signal_time"] for t in closed)
    cutoff = times[int(len(times) * split)] if len(times) > 1 else times[-1]
    out = {"cutoff": cutoff, "cost_round_trip_pct": 2 * (config.COMMISSION_PCT + config.SLIPPAGE_PCT)}

    def block(title, subset_fn):
        print(f"\n=== {title} ===\n{HEADER}")
        res = {}
        for name in sorted({t["strategy"] for t in closed}):
            sub = [t for t in closed if t["strategy"] == name and subset_fn(t)]
            s = summarize([t["net_pct"] for t in sub], [t["r"] for t in sub])
            res[name] = s
            print(fmt_row(name, s))
        return res

    out["in_sample"] = block(f"IN-SAMPLE (sinyal < {cutoff[:10]})", lambda t: t["signal_time"] < cutoff)
    out["out_of_sample"] = block(f"OUT-OF-SAMPLE (sinyal ≥ {cutoff[:10]})", lambda t: t["signal_time"] >= cutoff)

    print(f"\n=== Piyasa rejimine göre (tüm dönem) ===\n{HEADER}")
    out["by_regime"] = {}
    for name in sorted({t["strategy"] for t in closed}):
        for reg in sorted({t["regime"] for t in closed if t["strategy"] == name}):
            sub = [t for t in closed if t["strategy"] == name and t["regime"] == reg]
            s = summarize([t["net_pct"] for t in sub], [t["r"] for t in sub])
            out["by_regime"][f"{name}/{reg}"] = s
            print(fmt_row(f"{name} / {reg}", s))

    print("\n=== Çıkış türleri ===")
    for name in sorted({t["strategy"] for t in trades}):
        counts = {}
        for t in trades:
            if t["strategy"] == name:
                key = t["status"] + (f"({t['skip_reason']})" if t["skip_reason"] else "")
                counts[key] = counts.get(key, 0) + 1
        print(f"{name:<18} " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="BIST strateji backtest")
    p.add_argument("--interval", default="1d", choices=["1d", "1h"])
    p.add_argument("--period", default=None, help="Yahoo dönemi: 1y,2y,5y,max (1h için en fazla 2y)")
    p.add_argument("--strategies", default="all", help="virgülle ayrılmış veya 'all'")
    p.add_argument("--symbols", default=None, help="THYAO,ASELS,... (varsayılan: config listesi)")
    p.add_argument("--csv-dir", default=None, help="Yahoo yerine bu klasördeki CSV'leri kullan")
    p.add_argument("--split", type=float, default=0.7, help="in-sample oranı (varsayılan 0.7)")
    p.add_argument("--out", default="backtest_trades.csv")
    args = p.parse_args(argv)

    strategies = list(STRATEGIES) if args.strategies == "all" else [s.strip() for s in args.strategies.split(",")]
    unknown = [s for s in strategies if s not in STRATEGIES]
    if unknown:
        sys.exit(f"Bilinmeyen strateji: {unknown}. Mevcut: {list(STRATEGIES)}")
    if args.symbols:
        os.environ["SYMBOLS"] = args.symbols
    period = args.period or ("2y" if args.interval == "1h" else "5y")

    if args.csv_dir:
        frames = load_csv_dir(args.csv_dir)
    else:
        frames = asyncio.run(load_yahoo(config.get_symbols(), period, args.interval))
    log.info(f"{len(frames)} sembol, interval={args.interval}, stratejiler={strategies}")

    trades = []
    for sym, df in frames.items():
        trades += backtest_symbol(sym, df, args.interval, strategies)
    if not trades:
        print("Hiç sinyal oluşmadı.")
        return [], {}

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0]))
        w.writeheader()
        w.writerows(trades)
    summary = report(trades, args.split)
    Path(args.out).with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nİşlemler: {args.out} | Özet: {Path(args.out).with_suffix('.summary.json')}")
    print("Not: Bekl.% = işlem başına maliyet sonrası ortalama net getiri. İşlem sayısı ~30'un altındaysa "
          "sonuçlar istatistiksel olarak güvenilir değildir.")
    return trades, summary


if __name__ == "__main__":
    main()

"""Çalıştırma: python -m pytest -q tests"""
import os
import sqlite3
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import config  # noqa: E402
import scenarios as S  # noqa: E402
import strategy  # noqa: E402
from execution import simulate_trade  # noqa: E402
from features import build_features  # noqa: E402
from indicators import atr, ema, rsi  # noqa: E402
from metrics import max_drawdown, summarize  # noqa: E402
from strategies import STRATEGIES, breakout_retest, evaluate_bar  # noqa: E402

TZ = config.TZ
ALL = list(STRATEGIES)

# ------------------------------------------------------------------ indikatörler
WILDER_CLOSES = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
                 45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028,
                 46.0328, 46.4116, 46.2222, 45.6439, 46.2122]
WILDER_RSI = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93]


def test_rsi_matches_wilder_reference():
    r = rsi(pd.Series(WILDER_CLOSES), 14).dropna().round(2).tolist()
    assert r == pytest.approx(WILDER_RSI, abs=0.02)


def test_rsi_edge_cases():
    assert rsi(pd.Series(np.arange(1, 40, dtype=float)), 14).dropna().eq(100).all()
    assert rsi(pd.Series([10.0] * 40), 14).dropna().eq(50).all()


def test_ema_sma_seed():
    e = ema(pd.Series(np.arange(1, 31, dtype=float)), 10)
    assert e.iloc[:9].isna().all() and e.iloc[9] == pytest.approx(5.5)


def test_atr_constant_range():
    n = 50
    h, l = pd.Series([11.0] * n), pd.Series([9.0] * n)
    c = pd.Series([10.0] * n)
    assert atr(h, l, c, 14).dropna().round(6).eq(2.0).all()


# ------------------------------------------------------------------ geleceği görme (lookahead) testi
def test_features_and_signals_have_no_lookahead():
    """i. barda hesaplanan her değer, veri i. barda kesilse de AYNI olmalı."""
    rng = np.random.default_rng(7)
    n = 260
    c = 100 + np.cumsum(rng.normal(0.1, 1.5, n))
    o = np.r_[c[0], c[:-1]] + rng.normal(0, 0.3, n)
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, c) + rng.uniform(0.1, 1.5, n),
                       "Low": np.minimum(o, c) - rng.uniform(0.1, 1.5, n), "Close": c,
                       "Volume": rng.uniform(5e5, 3e6, n)},
                      index=pd.bdate_range("2024-01-01", periods=n, tz=TZ))
    full = build_features(df, "1d")
    for k in (160, 200, 240, 259):
        part = build_features(df.iloc[:k + 1], "1d")
        for col, arr in part.a.items():
            x, y = arr[k], full.a[col][k]
            assert (np.isnan(x) and np.isnan(y)) or x == pytest.approx(y, rel=1e-9, abs=1e-9), (col, k)
        sig_full = [(s.strategy, round(s.stop, 6)) for s in evaluate_bar(full, k, ALL)]
        sig_part = [(s.strategy, round(s.stop, 6)) for s in evaluate_bar(part, k, ALL)]
        assert sig_full == sig_part


def test_intraday_turnover_uses_only_completed_days():
    idx = [pd.Timestamp(d).tz_localize(TZ) + pd.Timedelta(hours=h)
           for d in pd.bdate_range("2026-01-05", periods=30) for h in range(10, 18)]
    df = pd.DataFrame({"Open": 10.0, "High": 10.0, "Low": 10.0, "Close": 10.0, "Volume": 1000.0},
                      index=pd.DatetimeIndex(idx))
    df.iloc[-1, df.columns.get_loc("Volume")] = 1e12      # son saatte dev hacim
    F = build_features(df, "1h")
    assert F.a["TURNOVER"][-1] == pytest.approx(10 * 1000 * 8)   # bugünün hacmi dahil edilmedi


# ------------------------------------------------------------------ bar tamamlanma
def test_drop_incomplete_bars():
    idx = pd.bdate_range("2026-10-01", periods=20, tz=TZ)
    d = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)
    day = idx[-1]
    assert len(strategy.drop_incomplete_bar(d, "1d", day.replace(hour=15).to_pydatetime())) == 19
    assert len(strategy.drop_incomplete_bar(d, "1d", day.replace(hour=19).to_pydatetime())) == 20
    h = d.copy()
    h.index = [day + pd.Timedelta(hours=k) for k in range(20)]
    last = h.index[-1]
    assert len(strategy.drop_incomplete_bar(h, "1h", (last + pd.Timedelta(minutes=30)).to_pydatetime())) == 19
    assert len(strategy.drop_incomplete_bar(h, "1h", (last + pd.Timedelta(minutes=80)).to_pydatetime())) == 20


# ------------------------------------------------------------------ stratejiler
def _signals(rows, enabled=ALL):
    F = build_features(S.bars(rows), "1d")
    return F, {c.strategy: c for c in evaluate_bar(F, len(F) - 1, enabled)}


def test_breakout_detects_real_resistance_break():
    F, sig = _signals(S.breakout_scenario())
    c = sig["breakout"]
    assert c.level == pytest.approx(100.0)
    assert c.stop < c.level < c.entry_ref < c.target
    assert c.target == pytest.approx(c.entry_ref + config.TARGET_R * (c.entry_ref - c.stop))


def test_breakout_rejected_without_volume():
    rows = S.breakout_scenario()
    o, h, l, c, _ = rows[-1]
    rows[-1] = (o, h, l, c, 900_000)
    _, sig = _signals(rows, ["breakout"])
    assert "breakout" not in sig


def test_breakout_rejected_when_level_untested():
    rows = S.breakout_scenario()
    rows[-31:-1] = [(r[0], min(r[1], 98.5), r[2], r[3], r[4]) for r in rows[-31:-1]]
    rows[-15] = (rows[-15][0], 100.0, rows[-15][2], rows[-15][3], rows[-15][4])   # tek dokunuş
    _, sig = _signals(rows, ["breakout"])
    assert "breakout" not in sig


def test_retest_after_breakout():
    rows = S.breakout_scenario()
    prev = rows[-1][3]
    for c in (101.0, 100.6):                                   # seviyeye geri çekilme
        rows.append((prev, max(prev, c) + 0.2, 100.2, c, 800_000))
        prev = c
    rows.append((prev, 102.4, prev - 0.1, 102.3, 1_200_000))   # yeniden yükseliş
    F, _ = _signals(rows)
    cand = breakout_retest(F, len(F) - 1)
    assert cand is not None and cand.level == pytest.approx(100.0)


def test_fake_breakout_blocks_retest_and_exits_trade():
    rows = S.breakout_scenario()
    prev = rows[-1][3]
    for c in (99.0, 98.4):                                     # direnç altında kapanış = sahte kırılım
        rows.append((prev, prev + 0.2, c - 0.3, c, 900_000))
        prev = c
    rows.append((prev, 100.5, prev - 0.1, 100.4, 1_200_000))
    F, _ = _signals(rows)
    assert breakout_retest(F, len(F) - 1) is None

    F0, sig = _signals(S.breakout_scenario())
    cand = sig["breakout"]
    after = S.bars(rows).iloc[len(F0):]
    res = simulate_trade(after["Open"].values, after["High"].values, after["Low"].values,
                         after["Close"].values, list(after.index.date), cand.entry_ref, cand.stop,
                         cand.invalidation)
    assert res["status"] == "INVALID" and res["net_pct"] < 0


def test_trend_pullback():
    _, sig = _signals(S.pullback_scenario())
    assert "trend_pullback" in sig


def test_support_bounce_and_invalidation():
    F, sig = _signals(S.support_scenario())
    c = sig["support_bounce"]
    assert c.stop < c.level < c.entry_ref and c.invalidation > c.stop


def test_squeeze():
    _, sig = _signals(S.squeeze_scenario())
    assert "squeeze" in sig


def test_liquidity_filter_blocks_everything():
    rows = [(o, h, l, c, 10) for o, h, l, c, _ in S.breakout_scenario()]
    _, sig = _signals(rows)
    assert sig == {}


# ------------------------------------------------------------------ işlem simülasyonu
def _sim(o, h, l, c, signal=100.0, stop=95.0, inv=None, days=None, **kw):
    n = len(o)
    days = days or list(pd.bdate_range("2026-01-05", periods=n).date)
    return simulate_trade(np.array(o, float), np.array(h, float), np.array(l, float), np.array(c, float),
                          days, signal, stop, inv, **kw)


def test_sim_next_open_fill_target_recomputed_and_costs():
    r = _sim([101, 102, 110], [102, 104, 113], [100, 101, 109], [101.5, 103, 112], target_r=2)
    assert r["fill_price"] == 101 and r["target"] == pytest.approx(101 + 2 * 6)
    assert r["status"] == "TP" and r["exit_price"] == pytest.approx(113)
    cost = 2 * (config.COMMISSION_PCT + config.SLIPPAGE_PCT)
    assert r["net_pct"] == pytest.approx((113 / 101 - 1) * 100 - cost)
    assert r["r_multiple"] == pytest.approx(2.0)


def test_sim_gap_up_skip_and_gap_down_exit():
    assert _sim([104], [105], [103], [104])["status"] == "SKIPPED"          # %4 boşluk > %3
    r = _sim([100, 92], [101, 93], [99, 90], [100.5, 91])                    # stop 95, açılış 92
    assert r["status"] == "SL" and r["exit_price"] == 92


def test_sim_same_bar_stop_and_target_assumes_stop():
    r = _sim([100], [120], [90], [110])
    assert r["status"] == "SL" and r["exit_price"] == 95


def test_sim_expiry_exits_next_day_open():
    n = config.MAX_HOLD_DAYS + 1
    r = _sim([100] * n, [101] * n, [99] * n, [100.5] * n)
    assert r["status"] == "EXPIRED" and r["exit_idx"] == config.MAX_HOLD_DAYS


def test_sim_open_position_has_no_exit():
    r = _sim([100, 100], [101, 101], [99, 99], [100.5, 100.7])
    assert r["status"] == "OPEN" and "exit_price" not in r


# ------------------------------------------------------------------ metrikler
def test_metrics():
    s = summarize([2.0, -1.0, 3.0, -1.0], [1, -0.5, 1.5, -0.5])
    assert s["n"] == 4 and s["win_rate"] == 50
    assert s["avg_win"] == 2.5 and s["avg_loss"] == -1.0 and s["expectancy"] == 0.75
    assert s["profit_factor"] == pytest.approx(2.5)
    assert max_drawdown([5, -3, -4, 2]) == -7


# ------------------------------------------------------------------ backtest + DB + web
def test_backtest_runs_end_to_end(tmp_path):
    import backtest
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    for name, fn in [("AAA", S.breakout_scenario), ("BBB", S.pullback_scenario), ("CCC", S.support_scenario)]:
        rows = fn()
        prev = rows[-1][3]
        for k in range(15):                                         # sinyal sonrası yükseliş
            c = prev * 1.01
            rows.append((prev, c * 1.005, prev * 0.998, c, 1_000_000))
            prev = c
        d = S.bars(rows)
        d.index = d.index.tz_localize(None)
        d.rename_axis("Date").to_csv(csv_dir / f"{name}.csv")
    trades, summary = backtest.main(["--csv-dir", str(csv_dir), "--out", str(tmp_path / "t.csv")])
    strategies_hit = {t["strategy"] for t in trades}
    assert {"breakout", "trend_pullback", "support_bounce"} <= strategies_hit
    assert (tmp_path / "t.summary.json").exists()


def test_storage_migrates_old_schema_and_web():
    import storage
    path = os.path.join(tempfile.mkdtemp(), "old.sqlite")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, timeframe TEXT,
        entry_price REAL, current_price REAL, entry_date TEXT, status TEXT DEFAULT 'OPEN',
        score REAL, pnl_percent REAL DEFAULT 0.0)""")
    conn.execute("INSERT INTO signals (symbol,timeframe,entry_price,status) VALUES ('X.IS','1h',10,'OPEN')")
    conn.execute("INSERT INTO signals (symbol,timeframe,entry_price,status,pnl_percent) VALUES ('Z.IS','1d',10,'TP',5)")
    conn.commit(); conn.close()
    config.DB_PATH = path
    storage.init_db()
    rows = storage.fetch("SELECT * FROM signals")
    assert all(r["strategy"] == "legacy" for r in rows)
    ins = "INSERT OR IGNORE INTO signals (symbol,timeframe,strategy,bar_time) VALUES ('Y','1h',?, 't')"
    assert storage.execute(ins, ("breakout",)) == 1
    assert storage.execute(ins, ("breakout",)) == 0
    assert storage.execute(ins, ("trend_pullback",)) == 1    # aynı bar, farklı strateji → ayrı kayıt
    assert storage.strategy_stats()["legacy"]["n"] == 1

    from web import app
    c = app.test_client()
    assert c.get("/health").status_code == 200
    page = c.get("/").data.decode()
    assert "X" in page and "legacy" in page
    assert c.get("/api/stats").status_code == 200

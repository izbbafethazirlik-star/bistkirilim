"""Taranacak hisse evreni — Borsa İstanbul'un resmi endeks bileşen dosyasından günlük güncellenir.

Kaynak: https://www.borsaistanbul.com/datum/hisse_endeks_ds.csv  (';' ayraçlı)
  ENDEKS KODU  : XU030 (BIST 30), XU050 (BIST 50), XU100 (BIST 100), XYLDZ (BIST Yıldız = Yıldız Pazar) ...
  BILESEN KODU : hisse kodu, ".E" son ekli (ör. THYAO.E)

Öncelik sırası:
  1) SYMBOLS ortam değişkeni (elle liste)  → evren dosyası kullanılmaz
  2) Borsa İstanbul dosyası (UNIVERSE endeksleri), günde bir kez yenilenir
  3) DATA_DIR'deki son başarılı indirme (önbellek)
  4) config.DEFAULT_SYMBOLS (yerleşik 130 hisse)
"""
import io
import json
import logging
import time
import urllib.request
from pathlib import Path

import pandas as pd

import config

logger = logging.getLogger("BIST_QUANT")

URL = "https://www.borsaistanbul.com/datum/hisse_endeks_ds.csv"
INDEX_NAMES = {"XU030": "BIST 30", "XU050": "BIST 50", "XU100": "BIST 100", "XYLDZ": "Yıldız Pazar"}
REFRESH_SEC = 24 * 3600
CACHE = Path(config.DATA_DIR) / "universe_cache.json"

_state = {"loaded_at": 0.0, "symbols": None, "membership": {}, "source": None}


def parse_components(raw: bytes, wanted) -> dict:
    """CSV içeriğinden {SEMBOL.IS: [endeks kodları]} döndürür."""
    text = None
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(io.StringIO(text), sep=";", dtype=str)
    norm = {c: c.strip().upper().replace("İ", "I").replace("_", " ") for c in df.columns}
    code_col = next(c for c, n in norm.items() if "BILESEN" in n and "KOD" in n)
    idx_col = next(c for c, n in norm.items() if "ENDEKS" in n and "KOD" in n)
    wanted = {w.upper() for w in wanted}
    out = {}
    for code, idx in zip(df[code_col], df[idx_col]):
        if not isinstance(code, str) or not isinstance(idx, str):
            continue
        idx = idx.strip().upper()
        if idx not in wanted:          # İngilizce başlık satırı vb. burada elenir
            continue
        sym = code.strip().upper()
        sym = sym[:-2] if sym.endswith(".E") else sym
        if not sym.isalnum():
            continue
        out.setdefault(f"{sym}.IS", []).append(idx)
    return out


def _download() -> bytes:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (bist-scanner)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _save_cache(membership):
    try:
        CACHE.write_text(json.dumps({"ts": time.time(), "membership": membership}), encoding="utf-8")
    except OSError as e:
        logger.warning(f"Evren önbelleği yazılamadı: {e}")


def _load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))["membership"]
    except Exception:
        return None


def refresh(force=False):
    if _state["symbols"] is not None and not force and time.time() - _state["loaded_at"] < REFRESH_SEC:
        return
    wanted = config.UNIVERSE
    membership, source = None, None
    try:
        membership = parse_components(_download(), wanted)
        if len(membership) < 30:   # bozuk/eksik dosyaya karşı koruma
            raise ValueError(f"beklenenden az hisse ({len(membership)})")
        _save_cache(membership)
        source = "borsaistanbul"
    except Exception as e:
        logger.warning(f"Borsa İstanbul endeks dosyası alınamadı: {e}")
        membership = _load_cache()
        source = "önbellek" if membership else None
    if not membership:
        membership = {s: [] for s in config.DEFAULT_SYMBOLS_IS}
        source = "yerleşik liste"
    _state.update(symbols=sorted(membership), membership=membership, source=source, loaded_at=time.time())
    counts = {INDEX_NAMES.get(k, k): sum(k in v for v in membership.values()) for k in wanted}
    logger.info(f"🌐 Hisse evreni: {len(membership)} hisse ({source}) | {counts}")


def get_symbols():
    manual = config.manual_symbols()
    if manual:
        return manual
    refresh()
    return list(_state["symbols"])


def label(symbol: str) -> str:
    """Mesajlarda gösterilecek en dar endeks etiketi (ör. 'BIST 30 · Yıldız Pazar')."""
    m = set(_state["membership"].get(symbol, []))
    parts = []
    for code in ("XU030", "XU050", "XU100"):
        if code in m:
            parts.append(INDEX_NAMES[code])
            break
    if "XYLDZ" in m:
        parts.append(INDEX_NAMES["XYLDZ"])
    return " · ".join(parts)


def source() -> str:
    return "SYMBOLS (elle)" if config.manual_symbols() else (_state["source"] or "-")

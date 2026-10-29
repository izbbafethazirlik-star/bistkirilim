"""Tüm ayarlar ortam değişkenlerinden okunur (Railway > Variables)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(name, default=None, cast=str):
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    try:
        return cast(val)
    except (TypeError, ValueError):
        return default


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on", "evet")


# --- Telegram ---
TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")
CHAT_ID = _env("TELEGRAM_CHAT_ID")
# Token yoksa bot çökmez; mesajları sadece loglar (Railway restart döngüsüne girmez)
DRY_RUN = _env("DRY_RUN", False, _bool) or not (TELEGRAM_TOKEN and CHAT_ID)

# --- Sunucu / Depolama ---
PORT = _env("PORT", 8080, int)  # Railway PORT'u kendisi verir
# Railway'de bir Volume'u /data'ya bağlayın; yoksa veritabanı her deploy'da silinir.
DATA_DIR = Path(_env("DATA_DIR", "/data" if Path("/data").is_dir() else "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DATA_DIR / "bist_quant.sqlite")

# --- Zaman ---
TZ = ZoneInfo("Europe/Istanbul")  # Railway sunucuları UTC çalışır
DATA_DELAY_MIN = _env("DATA_DELAY_MIN", 15, int)   # Yahoo BIST verisi 15 dk gecikmeli
MARKET_OPEN = (10, 0)
MARKET_CLOSE = (18, 10)                             # kapanış seansı dahil
INTRADAY_SCAN_EVERY_MIN = _env("INTRADAY_SCAN_EVERY_MIN", 15, int)
PNL_EVERY_MIN = _env("PNL_EVERY_MIN", 10, int)

# --- Tarama ---
TIMEFRAMES = [t.strip() for t in _env("TIMEFRAMES", "1h,1d").split(",") if t.strip()]
BATCH_SIZE = _env("BATCH_SIZE", 20, int)
LOOKBACK = {"1h": "3mo", "1d": "1y"}  # EMA50'nin oturması için yeterli bar

# --- Strateji seçimi ---
# Mevcut: breakout, breakout_retest, trend_pullback, support_bounce, squeeze
# Varsayılan canlı set = dokümandaki ilk öncelikler (kırılım + sahte kırılım filtresi/retest + trend devamı).
# support_bounce ve squeeze backtest'te her zaman karşılaştırılabilir; canlıya almak için buraya ekleyin.
ENABLED_STRATEGIES = [s.strip() for s in _env(
    "ENABLED_STRATEGIES", "breakout,breakout_retest,trend_pullback").split(",") if s.strip()]

# --- Ortak filtreler / risk ---
MIN_AVG_TURNOVER_TL = _env("MIN_AVG_TURNOVER_TL", 20_000_000, float)  # 20 günlük ort. günlük işlem hacmi (TL)
MIN_QUALITY = _env("MIN_QUALITY", 60, int)          # 0–100 sinyal kalite puanı alt sınırı
ATR_PCT_MIN = _env("ATR_PCT_MIN", 0.5, float)       # çok ölü hisseleri ele (ATR/fiyat %)
ATR_PCT_MAX = _env("ATR_PCT_MAX", 8.0, float)       # aşırı oynak hisseleri ele
RISK_MIN_PCT = _env("RISK_MIN_PCT", 0.8, float)     # stop mesafesi alt sınır (%)
RISK_MAX_PCT = _env("RISK_MAX_PCT", 8.0, float)     # stop mesafesi üst sınır (%)
TARGET_R = _env("TARGET_R", 2.0, float)             # hedef = giriş + TARGET_R × risk
MAX_ENTRY_GAP_PCT = _env("MAX_ENTRY_GAP_PCT", 3.0, float)  # sonraki açılış bu kadar yukarı boşluklu ise alma (tavan vb.)
MAX_HOLD_DAYS = _env("MAX_HOLD_DAYS", 10, int)      # işlem günü

# --- Maliyet (tek yön, %) — backtest ve canlı net PnL için ---
COMMISSION_PCT = _env("COMMISSION_PCT", 0.08, float)  # komisyon + BSMV; kendi aracı kurumunuza göre girin
SLIPPAGE_PCT = _env("SLIPPAGE_PCT", 0.05, float)

# --- Strateji parametreleri ---
BREAKOUT_LOOKBACK = _env("BREAKOUT_LOOKBACK", 20, int)       # 20–55 arası önerilir
BREAKOUT_MIN_TOUCHES = _env("BREAKOUT_MIN_TOUCHES", 2, int)  # direnç en az kaç kez test edilmiş olmalı
BREAKOUT_RVOL = _env("BREAKOUT_RVOL", 1.5, float)
BREAKOUT_RSI_MIN = _env("BREAKOUT_RSI_MIN", 55, float)
BREAKOUT_RSI_MAX = _env("BREAKOUT_RSI_MAX", 80, float)
RETEST_WINDOW = _env("RETEST_WINDOW", 5, int)                # kırılımdan sonra kaç bar içinde retest
PULLBACK_RVOL = _env("PULLBACK_RVOL", 1.2, float)
SUPPORT_LOOKBACK = _env("SUPPORT_LOOKBACK", 40, int)
SQUEEZE_RANK = _env("SQUEEZE_RANK", 0.20, float)             # BB genişliği son 120 barın en dar %20'sinde
SQUEEZE_RVOL = _env("SQUEEZE_RVOL", 1.5, float)

# --- Semboller ---
DEFAULT_SYMBOLS = [
    "THYAO", "ASELS", "KCHOL", "AKBNK", "EREGL", "SISE", "BIMAS", "TUPRS",
    "GARAN", "YKBNK", "SAHOL", "PETKM", "HEKTS", "SASA", "KONTR", "ODAS",
    "EKGYO", "FROTO", "TOASO", "PGSUS", "ASTOR", "EUPWR", "ALARK", "KOZAL",
    "ISCTR", "TCELL", "MGROS", "ENKAI", "VESTL", "GUBRF", "OYAKC", "TTKOM",
    "HALKB", "VAKBN", "TSKB", "SKBNK", "ALBRK", "AEFES", "AGHOL", "AKSA",
    "AKSEN", "ALGYO", "ALKIM", "ANHYT", "ARCLK", "ARDYZ", "AYDEM", "AYGAZ",
    "BERA", "BIOEN", "BRSAN", "BRYAT", "BUCIM", "CANTE", "CCOLA", "CEMTS",
    "CIMSA", "DOAS", "DOHOL", "ECILC", "EGEEN", "ENJSA", "ENERY", "ERBOS",
    "GENIL", "GESAN", "GLYHO", "GOZDE", "GSDHO", "GWIND", "HEDEF", "HLGYO",
    "HUNER", "IHLAS", "INDES", "INVEO", "ISDMR", "ISFIN", "ISGYO", "ISMEN",
    "IZMDC", "KARSN", "KARTN", "KCAER", "KERVT", "KLRHO", "KMPUR", "KORDS",
    "KOZAA", "KRDMD", "KZBGY", "LOGO", "MAVI", "MNDRS", "MPARK", "NTHOL",
    "OTKAR", "OZKGY", "PENTA", "PSGYO", "QUAGR", "RTALB", "RYGYO", "RYSAS",
    "SANKO", "SELEC", "SKTAS", "SMRTG", "SNGYO", "SOKM", "TATGD", "TAVHL",
    "TKFEN", "TKNSA", "TMSN", "TRGYO", "TSPOR", "TTRAK", "TUKAS", "TURSG",
    "ULKER", "UNLU", "VERUS", "VESBE", "YATAS", "YEOAF", "YEOTK", "YYLGD",
    "ZRGYO", "ZOREN",
]


def get_symbols():
    """SYMBOLS="THYAO,ASELS,..." ile listeyi kod değiştirmeden güncelleyebilirsiniz."""
    raw = _env("SYMBOLS")
    base = [s.strip().upper() for s in raw.split(",")] if raw else DEFAULT_SYMBOLS
    out = []
    for s in base:
        if not s:
            continue
        s = s if s.endswith(".IS") else f"{s}.IS"
        if s not in out:
            out.append(s)
    return out

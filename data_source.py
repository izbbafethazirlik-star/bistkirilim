"""Veri kaynağı katmanı.

Varsayılan: Yahoo Finance (yfinance) — ÜCRETSİZ ama BIST verisi 15 dk GECİKMELİ.
Gerçek zamanlı veri için (ör. aracı kurum API'si) aynı imzaya sahip yeni bir
sınıf yazıp DATA_PROVIDER ile seçebilirsiniz; stratejinin geri kalanı değişmez.
"""
import asyncio
import logging
import os

import pandas as pd

logger = logging.getLogger("BIST_QUANT")


class YahooProvider:
    name = "yahoo"

    def __init__(self, retries: int = 3):
        import yfinance as yf  # yalnızca bu sağlayıcı kullanılınca yüklensin
        self.yf = yf
        self.retries = retries

    def _download(self, symbols, period, interval):
        return self.yf.download(
            symbols, period=period, interval=interval, group_by="ticker",
            auto_adjust=True,  # bedelsiz/bölünme düzeltmeli — BIST için önemli
            progress=False, threads=True, multi_level_index=True, timeout=20,
        )

    async def fetch(self, symbols, period, interval) -> dict:
        """{sembol: DataFrame(Open, High, Low, Close, Volume)} döndürür."""
        loop = asyncio.get_running_loop()
        for attempt in range(1, self.retries + 1):
            try:
                data = await loop.run_in_executor(None, self._download, list(symbols), period, interval)
                return split_frames(data, symbols)
            except Exception as e:  # YFRateLimitError dahil
                wait = 10 * attempt
                logger.warning(f"Yahoo indirme hatası ({attempt}/{self.retries}): {e} — {wait}s sonra tekrar")
                await asyncio.sleep(wait)
        return {}


def split_frames(data: pd.DataFrame, symbols) -> dict:
    """yfinance çıktısını sembol bazında ayırır (tek/çok hisse, iki MultiIndex düzeni)."""
    out = {}
    if data is None or data.empty:
        return out
    cols = data.columns
    for s in symbols:
        try:
            if isinstance(cols, pd.MultiIndex):
                if s in cols.get_level_values(0):
                    df = data[s]
                elif s in cols.get_level_values(1):
                    df = data.xs(s, axis=1, level=1)
                else:
                    continue
            else:
                if len(symbols) != 1:
                    continue
                df = data
            df = df.dropna(how="all")
            if not df.empty:
                out[s] = df.copy()
        except Exception as e:
            logger.debug(f"{s} ayrıştırılamadı: {e}")
    return out


def get_provider():
    name = os.environ.get("DATA_PROVIDER", "yahoo").lower()
    if name == "yahoo":
        return YahooProvider()
    raise ValueError(f"Bilinmeyen DATA_PROVIDER: {name}")

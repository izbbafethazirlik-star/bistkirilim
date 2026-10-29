# BIST Strateji Tarayıcı (Kırılım ailesi)

BIST hisselerini tarar. Her stratejiyi ayrı bir modül olarak çalıştırır, sinyalleri
**hangi stratejiden ve hangi piyasa rejiminde** üretildiğiyle birlikte kaydeder,
pozisyonları canlı takip eder ve strateji bazında performans raporlar. Canlı bot ve
geçmiş test (backtest) **aynı strateji ve aynı işlem simülasyonu kodunu** kullanır.

## Mimari

```
1. Veri doğrulama   features.py   tamamlanmış mum · eksik veri · likidite (yalnızca geçmiş günler)
2. Piyasa rejimi    regime.py     UP · DOWN · RANGE · SQUEEZE
   Stratejiler      strategies.py
       breakout         Gerçek direnç kırılımı (20–55 bar direnç, ≥2 test, kapanış + hacim + RSI teyidi)
       breakout_retest  Kırılım sonrası yeniden test (sahte kırılım filtresinin giriş tarafı)
       trend_pullback   Trend devamı: EMA20'ye geri çekilme + yeniden yükseliş teyidi
       support_bounce   Destekten dönüş: test edilmiş destek + RSI toparlanması
       squeeze          Bollinger sıkışması sonrası hacimli kutu kırılımı
   Sahte kırılım filtresi: yakın geçmişte başarısız kırılım → kalite cezası;
       seviye altında kapanış → sinyal/pozisyon iptal (INVALID)
3. Risk kontrolü    strategies.risk_check   likidite · ATR% · stop mesafesi · hedef = giriş + 2R · kalite
   İşlem            execution.py            sonraki bar açılışında giriş, boşluk/tavan kontrolü, maliyet
4. Performans       storage.py + metrics.py strateji ve rejim bazında: işlem, kazanma %, ort. kazanç/kayıp,
                                            beklenen net getiri, kâr faktörü, maks. düşüş
```

Rejim yönlendirmesi (`strategies.STRATEGIES`):

| Strateji | Çalıştığı rejimler |
|---|---|
| breakout, breakout_retest | UP, RANGE, SQUEEZE |
| trend_pullback | UP (ve trend koşulu sağlanıyorsa SQUEEZE) |
| support_bounce | hepsi (rejim kaydedilir, backtest'te ayrı ölçülür) |
| squeeze | SQUEEZE |

Canlıda varsayılan olarak açık olan stratejiler: `breakout`, `breakout_retest`, `trend_pullback`.
Diğer ikisini önce backtest'te karşılaştırın, sonra `ENABLED_STRATEGIES` değişkenine ekleyin.

## Taranan hisseler

Varsayılan evren: **BIST 30 + BIST 50 + BIST 100 + Yıldız Pazar** (`UNIVERSE=XU030,XU050,XU100,XYLDZ`).
Liste, Borsa İstanbul'un resmi endeks bileşen dosyasından (`hisse_endeks_ds.csv`) günde bir kez
otomatik güncellenir; dönemsel endeks değişiklikleri ve yeni Yıldız Pazar hisseleri kendiliğinden girer.
Dosyaya ulaşılamazsa son başarılı liste (`/data/universe_cache.json`), o da yoksa yerleşik 130 hisselik
liste kullanılır. `SYMBOLS=THYAO,ASELS,...` verilirse endeks listesi yerine o kullanılır.
Telegram mesajlarında hissenin endeksi de yazar (ör. "BIST 30 · Yıldız Pazar").

## Sinyal yaşam döngüsü

`PENDING` (sinyal bar kapanışında) → sonraki barın açılışı = giriş → `OPEN` →
`TP` | `SL` | `INVALID` (sahte kırılım) | `EXPIRED` (MAX_HOLD_DAYS doldu, ertesi gün açılışında çıkış).
Açılış, sinyal fiyatının %3 üzerindeyse (tavan / boşluklu açılış) veya stop'un altındaysa
işleme girilmez: `SKIPPED`. Aynı barda hem stop hem hedef görülürse önce stop varsayılır.
Bütün PnL değerleri komisyon ve kayma düşüldükten sonraki **net** değerlerdir.

## Geçmiş test

```bash
pip install -r requirements.txt
python backtest.py --interval 1d --period 5y                      # tüm stratejiler
python backtest.py --interval 1h --period 2y --strategies breakout,trend_pullback
python backtest.py --csv-dir veriler/                             # SEMBOL.csv: Date,Open,High,Low,Close,Volume
```

Çıktılar:
- **IN-SAMPLE** (ilk %70) ve **OUT-OF-SAMPLE** (son %30) tabloları
- Rejim bazında sonuçlar ve çıkış türü dağılımı
- `backtest_trades.csv` (bütün işlemler) ve `backtest_trades.summary.json`

Parametreleri **yalnızca in-sample sonuçlarına bakarak** ayarlayın. Out-of-sample dönemi en sonda,
bir kez doğrulama için kullanın. Yaklaşık 30'dan az işlemle yapılan karşılaştırmalara güvenmeyin.
Yahoo'ya bulut sunucusundan erişim engellenirse, testi kendi bilgisayarınızda çalıştırın.

Bilinen sınırlamalar:
- Sembol listesi bugünün listesi olduğu için hayatta kalma yanlılığı (survivorship bias) vardır.
- Günlük barlarda gün içi fiyat sırası bilinmez.
- Portföy sermaye kısıtı modellenmez.

## Railway'de yayınlama

1. Klasörü GitHub'a gönderin → Railway → **Deploy from GitHub repo**. `Dockerfile` ve
   `railway.json` hazır.
2. **Variables** sekmesine şunları girin: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `DATA_DIR=/data`.
   Komisyonunuzu `COMMISSION_PCT` (tek yön, %) ile girin.
3. Servise **Volume** ekleyin, mount path: `/data`. Volume yoksa geçmiş her deploy'da silinir.
4. **Settings → Networking → Generate Domain**: panel `/` adresinde açılır. JSON uçları:
   `/api/stats`, `/api/signals`. Sağlık kontrolü `/health`.
5. Replica sayısını **1** bırakın.

Token girilmemişse bot `DRY_RUN` modunda çalışır ve mesajları yalnızca loglara yazar.
Bütün ayarların listesi `.env.example` dosyasında.

## Zamanlama (İstanbul saati)

- **1h:** Hafta içi 10:00–19:30 arasında 15 dakikada bir. Yalnızca kapanmış barlar değerlendirilir.
- **1d:** Hafta içi 18:30'dan sonra günde bir kez.
- **Pozisyon takibi:** Seans boyunca 10 dakikada bir. Giriş, kapanış ve işleme girilmeyen
  sinyaller Telegram'a bildirilir.

## Test

```bash
pip install pytest && python -m pytest -q tests
```

Testler şunları kapsar:
- RSI'nin Wilder referans verisiyle eşleşmesi
- **Geleceği görme (lookahead) olmaması**: veri her noktada kesildiğinde bütün özellikler ve sinyaller aynı kalıyor
- Her stratejinin senaryosu ve reddetme koşulları
- Sahte kırılım çıkışı
- Boşluk ve tavan kuralları
- Maliyet hesabı, metrikler
- Uçtan uca backtest ve veritabanı geçişi

## Veri kaynağı

Varsayılan kaynak Yahoo Finance: ücretsiz, BIST için **15 dakika gecikmeli**, resmi bir API değil.
Gerçek zamanlı veri için `data_source.py` dosyasına aynı `fetch(symbols, period, interval)`
imzasıyla bir sağlayıcı ekleyip `DATA_PROVIDER` ile seçin. Örneğin bir aracı kurum API'si
veya lisanslı bir veri dağıtıcısı kullanılabilir.

> Bu yazılım yatırım tavsiyesi değildir.

#!/bin/bash
# Günlük çekim — cron bunu çalıştırır.
#   1) Token'ı kontrol eder, ölüyse çekim yapmadan uyarı bırakır
#   2) config.json'daki sayfaların reklamlarını tazeler
#   3) Yeni reklamların görsellerini indirir
#   4) Panelin JSON'unu yeniden üretir
# Log: collector.log  (2 MB'ı geçince başı kırpılır)

set -u
KLASOR="$(cd "$(dirname "$0")" && pwd)"
PY=/usr/bin/python3
LOG="$KLASOR/collector.log"

cd "$KLASOR" || exit 1

yaz() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Log 2 MB'ı geçtiyse son 2000 satırı tut
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2097152 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

yaz "=== günlük çekim başladı ==="

# 1) Token kontrolü — ölü token'la çekim yapmak veriyi bozmaz ama boşa gider
if ! "$PY" collector.py --test >> "$LOG" 2>&1; then
  yaz "DURDURULDU: token geçersiz veya süresi dolmuş."
  yaz "Yenile:  https://developers.facebook.com/tools/accesstoken -> Extend Access Token"
  yaz "Sonra .env icindeki FB_TOKEN satirini guncelle."
  exit 1
fi

# 2) Sayfa bazlı çekim (config.json > pages)
if "$PY" collector.py >> "$LOG" 2>&1; then
  yaz "çekim tamam"
else
  yaz "HATA: çekim başarısız (çıkış kodu $?)"
  exit 1
fi

# 3) Yeni reklamların görselini indir (var olanları atlar, sadece yenileri çeker)
if "$PY" gorsel.py --kisiler --adet 8 --genislik 380 --kalite 70 --bekle 2 >> "$LOG" 2>&1; then
  yaz "görseller güncel"
else
  yaz "UYARI: görsel indirme başarısız (veri yine de güncel)"
fi

# 4) Panel verisini tazele
if "$PY" export.py --kisiler --sayfa 14 --gorsel >> "$LOG" 2>&1; then
  yaz "veri.json güncellendi"
else
  yaz "UYARI: export başarısız"
fi

yaz "=== bitti ==="

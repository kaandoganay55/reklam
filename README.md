# Reklam Kütüphanesi Paneli

**Canlı panel:** <https://kaandoganay55.github.io/reklam/>


Meta Ad Library API'sinden (`ads_archive`) Türkiye'deki **siyasi ve sosyal konulu
reklamları** çekip kimin ne yayınladığını, ne kadar harcadığını takip eden panel.

## Kapsam — önce bunu oku

| Reklam türü | Kapsam | Geriye dönük |
|---|---|---|
| Siyasi / seçim / sosyal konu | Tüm dünya, Türkiye dahil | 7 yıl |
| Her tür reklam (`ad_type=ALL`) | Sadece AB + İngiltere | 1 yıl |

Türkiye AB dışında olduğu için bu panel yalnızca siyasi reklamları görebilir.
Bir reklamın arşive düşmesi için reklamverenin onu **siyasi olarak beyan etmiş
olması** gerekir; beyansız yayınlanan reklam yakalanana kadar görünmez.

Harcama ve gösterim **kesin sayı değil aralıktır** (`lower_bound`–`upper_bound`).
Açık uçlu kovalarda üst sınır hiç gelmez; panel o durumda alt sınıra düşer.
Grafiklerdeki tek rakamlar aralıkların orta noktasıdır — tahmindir.

## Kurulum

```bash
pip3 install -r requirements.txt
cp .env.example .env          # FB_TOKEN'ı içine yaz
```

Token için sırayla:

1. **Kimlik doğrulama** — <https://www.facebook.com/ID> (API'nin ön şartı, birkaç gün sürebilir)
2. **Uygulama** — <https://developers.facebook.com> üzerinde "Business" tipi bir app
3. **Token** — Graph API Explorer'dan kısa ömürlü token al, uzun ömürlüye çevir:

```bash
curl -G "https://graph.facebook.com/v23.0/oauth/access_token" \
  -d grant_type=fb_exchange_token \
  -d client_id=$APP_ID -d client_secret=$APP_SECRET \
  -d fb_exchange_token=$SHORT_TOKEN
```

Uzun ömürlü token ~60 gün geçerli. Süresi dolunca `collector.py --test` hata kodu
190 döner; o zaman yenile.

## Kullanım

```bash
python3 collector.py --test          # token ve erişim doğru mu (tek ucuz istek)
python3 collector.py --discover      # kelimelerle sayfa keşfi
python3 collector.py                 # config.json'daki sayfaların reklamlarını çek
python3 collector.py --days 90       # sadece son 90 gün
python3 -m streamlit run app.py      # paneli aç
```

Takip edilecek sayfaları `config.json` içindeki `pages` listesine ekle:

```json
"pages": [ { "page_id": "1234567890", "label": "Örnek Belediye" } ]
```

`page_id`'yi ya <https://www.facebook.com/ads/library> adresinde sayfayı aratıp
URL'deki `view_all_page_id=` değerinden, ya da panelin **Sayfa Keşfi** sekmesinden
alırsın — keşif sekmesi doğrudan yapıştırılabilir JSON bloğu üretir.

## Dosyalar

| Dosya | İş |
|---|---|
| `api.py` | Ad Library istemcisi — sayfalama, rate-limit geri çekilmesi, token hatası ayrımı |
| `db.py` | SQLite şeması ve upsert |
| `collector.py` | Çekim CLI'ı (`--test`, `--discover`, `--days`) |
| `app.py` | Streamlit panel |
| `viz.py` | Grafikler |
| `export.py` | Gerçek veriyi HTML panelinin JSON şekline çevirir |
| `gorsel.py` | Reklam kreatiflerini ekran görüntüsü olarak indirir (Playwright) |
| `rapor.py` | Kişi bazlı rakip raporu — kendi kampanyası vs. adı geçen |
| `fbtoken.py` | Token ömrünü uzatır ve kalan süreyi gösterir |
| `gunluk.sh` | Tüm zinciri tek komutta çalıştırır |
| `config.json` | Takip listesi ve anahtar kelimeler |

## Neden SQLite

API sadece **anlık** durumu verir. Her çekimde `ad_history` tablosuna o günün
harcama/gösterim aralığı yazılır, `ads.first_seen` korunur. Birkaç hafta veri
biriktikten sonra "X sayfası dün 5 yeni reklam başlattı", "şu reklam yayından
kalktı", "bu ay harcama aralığı yükseldi" gibi sorular cevaplanabilir hale gelir.
Panelin asıl değeri burada.

## Toplu güncelleme

`gunluk.sh` bütün zinciri tek komutta çalıştırır:

```bash
./gunluk.sh
```

Sırayla: token'ı doğrular (ölüyse hiç başlamaz) → `config.json` içindeki sayfaların
reklamlarını tazeler → yeni reklamların görsellerini indirir → `veri.json`'u üretir.
Çıktı `collector.log` dosyasına yazılır (2 MB'ı geçince başı kırpılır).

```bash
tail -30 collector.log
```

**Cron'a bağlı değil** — elle çalıştırılır. Otomatik istersen:

```bash
( crontab -l 2>/dev/null; echo "0 9 * * * $HOME/Desktop/reklam-paneli/gunluk.sh" ) | crontab -
```

Bunu yaparsan macOS'ta `~/Desktop` korumalı klasör olduğu için **Sistem Ayarları →
Gizlilik ve Güvenlik → Tam Disk Erişimi**'ne `/usr/sbin/cron` eklemen gerekebilir.

## Token ömrü

Graph API Explorer token'ı 1-2 saatte ölür — panel için mutlaka uzun ömürlüye çevir.

```bash
python3 fbtoken.py --uzat KISA_TOKEN   # 60 güne çevirir, .env'i günceller
python3 fbtoken.py --kontrol           # kalan süreyi gösterir
```

`--uzat` için `.env` içinde `FB_APP_ID` ve `FB_APP_SECRET` olmalı
(developers.facebook.com > uygulaman > Ayarlar > Temel). Alternatif olarak
[Access Token Tool](https://developers.facebook.com/tools/accesstoken)'daki
"Extend Access Token" düğmesi aynı işi tek tıkla yapar.

Kalıcı çözüm: Business Manager'dan **sistem kullanıcısı** token'ı — süresi hiç dolmaz.

## HTML önizleme

Yayınlanmış HTML sayfası Meta API'sini **doğrudan çağıramaz**: tarayıcı CSP'si dış
isteklere izin vermiyor, ayrıca token'ı yayınlanmış bir sayfaya koymak onu sızdırır.
Akış şöyle:

```
collector.py  ->  ads.db  ->  export.py  ->  veri.json  ->  HTML
```

```bash
python3 export.py --gun 180      # veri.json üretir (en çok harcayan 5 sayfa)
```

Çıkan `veri.json`, HTML panelindeki `const D = {...}` bloğunun yerine geçer.

## Canlı panel

`index.html` tek dosyalık, kendi kendine yeten bir sayfadır — veriler ve reklam
görselleri içine gömülüdür, sunucu gerektirmez. GitHub Pages'te yayınlanır.

Güncellemek için:

```bash
./gunluk.sh                                        # veriyi tazele
python3 export.py --kisiler --sayfa 14 --gorsel    # veri.json üret
# veri.json'u index.html içindeki `const D = {...};` bloğunun yerine koy
git commit -am "veri güncellendi" && git push
```

## Veri kaynağı ve sorumluluk

Tüm veriler **Meta Reklam Kütüphanesi API'sinden** (`ads_archive`) alınmıştır.
Reklam Kütüphanesi, Meta'nın kamuya açık şeffaflık aracıdır; buradaki reklamlar
reklamverenlerin kendi beyanlarıyla siyasi/sosyal içerikli olarak işaretlenmiştir.

Bilinmesi gerekenler:

- **Harcama ve gösterim kesin rakam değildir.** API bunları aralık olarak verir
  (`0–99 ₺`, `1.000–1.499 ₺` gibi). Paneldeki tek sayılar bu aralıkların orta
  noktasıdır ve **tahmindir**. Toplamlar alt/üst sınırların toplamıdır.
- **"Erişim" verisi yoktur.** Türkiye AB dışında olduğu için API kaç kişiye
  ulaşıldığını vermez; yalnızca gösterim (kaç kez gösterildi) vardır. Paneldeki
  frekans, gösterimin tahmini hedef kitleye bölümüdür — gerçek frekansın alt sınırıdır.
- **Kapsam eksik olabilir.** Siyasi olarak beyan edilmeden yayınlanan reklamlar
  arşive düşmez. Bir kişinin panelde reklamı görünmüyorsa "reklam vermedi" değil,
  "beyanlı reklamı arşivde yok" demektir.
- **Kreatifler ekran görüntüsüdür.** API reklam görselini vermediği için her
  reklamın Reklam Kütüphanesi sayfası açılıp kartı görüntülenmiştir. Meta'nın
  gizlediği reklamların (sorumluluk reddi olmadan yayınlananlar) görseli yoktur.

Bu depo bağımsız bir analiz çalışmasıdır; Meta ile ilişkisi yoktur ve adı geçen
kişi veya kurumları temsil etmez.

## Kurulum notu

`.env` dosyası depoda **yoktur** (token içerdiği için). `.env.example`'ı kopyalayıp
kendi Meta erişim token'ını yazman gerekir.

#!/usr/bin/env python3
"""Reklam kreatiflerini (görsel/video kartı) ekran görüntüsü olarak indirir.

API kreatifi vermiyor: `ads_archive` sadece `ad_snapshot_url` döndürüyor ve o
sayfa JavaScript ile render ediliyor. Bu yüzden Playwright ile sayfayı açıp
reklam kartının ekran görüntüsünü alıyoruz. Resim, video ve karusel reklamların
hepsinde çalışır (videoda ilk kare görünür).

    python3 gorsel.py --adet 6            # sayfa başına en yeni 6 reklam
    python3 gorsel.py --sayfa "Cevat Öncü" --adet 20
    python3 gorsel.py --genislik 420      # küçük resim genişliği

Çıktı: gorseller/<ad_id>.jpg  +  gorseller/index.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import sys

from PIL import Image, ImageChops

import db as store
from collector import load_env, load_config
from rapor import sadelestir, haric_liste

HERE = os.path.dirname(os.path.abspath(__file__))
KLASOR = os.path.join(HERE, "gorseller")


def token_tazele(url: str, token: str) -> str:
    """snapshot_url içindeki access_token'ı günceliyle değiştirir.

    API kaydı yapılırken o anki token URL'e gömülüyor. Token yenilendiğinde
    eski URL'ler giriş duvarına düşer; bu yüzden her açılışta tazeliyoruz.
    """
    if "access_token=" in url:
        return re.sub(r"access_token=[^&]*", "access_token=" + token, url)
    ayirac = "&" if "?" in url else "?"
    return url + ayirac + "access_token=" + token


def kirp(ham: bytes, genislik: int, kalite: int) -> bytes:
    """Beyaz kenarları kırpar, verilen genişliğe küçültür, JPEG'e çevirir."""
    im = Image.open(io.BytesIO(ham)).convert("RGB")
    zemin = Image.new("RGB", im.size, (255, 255, 255))
    kutu = ImageChops.difference(im, zemin).convert("L").point(lambda v: 255 if v > 8 else 0).getbbox()
    if kutu:
        pad = 6
        im = im.crop((max(kutu[0] - pad, 0), max(kutu[1] - pad, 0),
                      min(kutu[2] + pad, im.width), min(kutu[3] + pad, im.height)))
    if im.width > genislik:
        im = im.resize((genislik, round(im.height * genislik / im.width)), Image.LANCZOS)
    # Çok uzun kartları kırp: küçük resimde alt kısım zaten okunmuyor.
    if im.height > genislik * 2:
        im = im.crop((0, 0, im.width, genislik * 2))
    tampon = io.BytesIO()
    im.save(tampon, "JPEG", quality=kalite, optimize=True, progressive=True)
    return tampon.getvalue()


def aday_sayfalari(conn) -> list:
    """config.json'daki kişi/kurum isimleriyle eşleşen sayfa adları."""
    cfg = load_config()
    anahtarlar = [sadelestir(k) for k in cfg.get("kisiler", [])]
    adlar = [r[0] for r in conn.execute(
        "SELECT DISTINCT page_name FROM ads WHERE page_name IS NOT NULL").fetchall()]
    haric = haric_liste()
    return [a for a in adlar
            if a not in haric and any(x and x in sadelestir(a) for x in anahtarlar)]


def secilenler(conn, sayfa: str, adet: int, sadece_kisiler: bool = False) -> list:
    if sadece_kisiler and not sayfa:
        adlar = aday_sayfalari(conn)
        if not adlar:
            return []
        yer = ",".join("?" * len(adlar))
        return conn.execute(
            "SELECT ad_id, page_name, snapshot_url, delivery_start FROM ("
            "  SELECT ad_id, page_name, snapshot_url, delivery_start,"
            "         ROW_NUMBER() OVER (PARTITION BY page_id ORDER BY delivery_start DESC) sira"
            "  FROM ads WHERE snapshot_url IS NOT NULL AND page_name IN (" + yer + ")"
            ") WHERE sira <= ? ORDER BY page_name, delivery_start DESC",
            adlar + [adet]).fetchall()
    if sayfa:
        return conn.execute(
            "SELECT ad_id, page_name, snapshot_url, delivery_start FROM ads "
            "WHERE snapshot_url IS NOT NULL AND page_name = ? "
            "ORDER BY delivery_start DESC LIMIT ?", (sayfa, adet)).fetchall()
    # Sayfa başına en yeni N reklam
    return conn.execute(
        "SELECT ad_id, page_name, snapshot_url, delivery_start FROM ("
        "  SELECT ad_id, page_name, snapshot_url, delivery_start,"
        "         ROW_NUMBER() OVER (PARTITION BY page_id ORDER BY delivery_start DESC) sira"
        "  FROM ads WHERE snapshot_url IS NOT NULL"
        ") WHERE sira <= ? ORDER BY page_name, delivery_start DESC", (adet,)).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="Reklam kreatiflerini indir")
    ap.add_argument("--db", default=store.DEFAULT_DB)
    ap.add_argument("--sayfa", default=None, help="Tek bir sayfanın reklamları")
    ap.add_argument("--adet", type=int, default=6, help="Sayfa başına kaç reklam (varsayılan 6)")
    ap.add_argument("--genislik", type=int, default=420, help="Küçük resim genişliği")
    ap.add_argument("--kalite", type=int, default=72, help="JPEG kalitesi")
    ap.add_argument("--kisiler", action="store_true",
                    help="Sadece config.json'daki kişilerin kendi sayfaları")
    ap.add_argument("--bekle", type=float, default=2.5,
                    help="Reklamlar arası bekleme saniyesi (varsayılan 2.5)")
    ap.add_argument("--yenile", action="store_true", help="Var olanları tekrar çek")
    a = ap.parse_args()

    load_env()
    if not os.environ.get("FB_TOKEN"):
        print("FB_TOKEN yok — snapshot sayfaları token olmadan açılmaz.", file=sys.stderr)
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright kurulu değil:  pip3 install playwright && playwright install chromium",
              file=sys.stderr)
        return 1

    # Ön kontrol: token ölüyse snapshot sayfaları giriş duvarına düşer ve
    # tüm ekran görüntüleri çöp olur. Toplu çekimden önce tek istekle doğrula.
    import api
    try:
        next(api.fetch_ads(search_terms="a", limit=1, max_pages=1, pause=0), None)
    except api.AdLibraryError as exc:
        print("Token doğrulanamadı: {}".format(exc), file=sys.stderr)
        if getattr(exc, "code", None) == 190:
            print("\nGraph API Explorer'dan yeni token al ve UZUN ÖMÜRLÜYE çevir "
                  "(kısa token 1-2 saatte ölür):\n"
                  "  curl -G 'https://graph.facebook.com/v23.0/oauth/access_token' \\\n"
                  "    -d grant_type=fb_exchange_token -d client_id=APP_ID \\\n"
                  "    -d client_secret=APP_SECRET -d fb_exchange_token=KISA_TOKEN",
                  file=sys.stderr)
        return 1

    os.makedirs(KLASOR, exist_ok=True)
    conn = sqlite3.connect(a.db)
    hedef = secilenler(conn, a.sayfa, a.adet, a.kisiler)
    conn.close()
    if not hedef:
        print("Uygun reklam yok.")
        return 1

    indeks_yolu = os.path.join(KLASOR, "index.json")
    indeks = {}
    if os.path.exists(indeks_yolu):
        with open(indeks_yolu, encoding="utf-8") as fh:
            indeks = json.load(fh)

    print("{} reklam işlenecek.".format(len(hedef)))
    basarili = atlanan = hatali = 0

    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    # Reklam kartının kesin işareti; yoksa sayfa giriş duvarına düşmüş demektir.
    ISARET = ("Kütüphane Kodu", "Library ID", "Sponsorlu", "Sponsored")
    # Kreatif yerine uyarı gösterilen reklamlar: kart görünür ama içerik yok.
    ENGELLI = ("sorumluluk reddi olmadan yayınlandı", "without a required disclaimer",
               "Hâlâ görmek istiyorsan", "you must log in")
    engel = 0

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ])
        ctx = b.new_context(viewport={"width": 640, "height": 1400}, user_agent=UA,
                            locale="tr-TR", timezone_id="Europe/Istanbul")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        pg = ctx.new_page()

        for i, (ad_id, sayfa, url, bas) in enumerate(hedef, 1):
            yol = os.path.join(KLASOR, ad_id + ".jpg")
            if os.path.exists(yol) and not a.yenile:
                atlanan += 1
                continue
            try:
                ham = None
                taze_url = token_tazele(url, os.environ["FB_TOKEN"])
                for deneme in range(3):
                    pg.goto(taze_url, wait_until="networkidle", timeout=45000)
                    pg.wait_for_timeout(1500)
                    metin = pg.inner_text("body") or ""
                    if any(x in metin for x in ENGELLI):
                        print("  {} atlandı: kreatif gizli (sorumluluk reddi uyarısı)".format(ad_id))
                        ham = "ENGELLI"
                        break
                    if any(x in metin for x in ISARET):
                        ham = pg.screenshot()
                        break
                    # Giriş duvarı: hız sınırına takıldık, bekleyip tekrar dene.
                    engel += 1
                    pg.wait_for_timeout(4000 * (deneme + 1))

                if ham == "ENGELLI":
                    hatali += 1
                elif ham is None:
                    hatali += 1
                    print("  {} atlandı: giriş duvarı (3 deneme)".format(ad_id))
                else:
                    with open(yol, "wb") as fh:
                        fh.write(kirp(ham, a.genislik, a.kalite))
                    indeks[ad_id] = {"sayfa": sayfa, "bas": (bas or "")[:10],
                                     "kb": round(os.path.getsize(yol) / 1024, 1)}
                    basarili += 1
            except Exception as exc:
                hatali += 1
                print("  {} hata: {}".format(ad_id, str(exc)[:90]))

            pg.wait_for_timeout(int(a.bekle * 1000))
            if i % 10 == 0:
                print("  {}/{} ({} indi, {} atlandı, {} hata, {} engel)".format(
                    i, len(hedef), basarili, atlanan, hatali, engel))
        ctx.close(); b.close()

    if engel:
        print("\n{} kez giriş duvarına takıldı (yeniden denendi). "
              "Çok tekrarlıyorsa --bekle değerini artır.".format(engel))

    with open(indeks_yolu, "w", encoding="utf-8") as fh:
        json.dump(indeks, fh, ensure_ascii=False, indent=1)

    toplam = sum(os.path.getsize(os.path.join(KLASOR, f))
                 for f in os.listdir(KLASOR) if f.endswith(".jpg")) / 1024 / 1024
    print("\nBitti: {} indi, {} atlandı, {} hata.".format(basarili, atlanan, hatali))
    print("Klasör: {} ({} görsel, {:.1f} MB)".format(
        KLASOR, len([f for f in os.listdir(KLASOR) if f.endswith('.jpg')]), toplam))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

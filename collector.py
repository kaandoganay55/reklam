#!/usr/bin/env python3
"""Ad Library'den veri çekip SQLite'a yazan toplayıcı.

Kullanım:
    python3 collector.py                      # config.json'daki sayfaları çek
    python3 collector.py --discover           # config.json'daki anahtar kelimelerle sayfa keşfet
    python3 collector.py --discover "Samsun"  # tek seferlik kelime araması
    python3 collector.py --days 90            # sadece son 90 günde yayınlananlar

Panelin "Veri Çekme" sekmesindeki buton da bu dosyayı çalıştırır.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List

import api
import db

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
ENV_PATH = os.path.join(HERE, ".env")


def load_env(path: str = ENV_PATH) -> None:
    """.env dosyasındaki KEY=VALUE satırlarını ortama alır (bağımlılıksız)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"countries": ["TR"], "pages": [], "keywords": []}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def collect_pages(conn, cfg: Dict[str, Any], date_min: str = None) -> Dict[str, int]:
    entries: List[Dict[str, str]] = [
        p for p in cfg.get("pages", []) if str(p.get("page_id", "")).strip()
    ]
    if not entries:
        print("config.json'da takip edilecek sayfa yok. "
              "Önce --discover ile sayfa bul, page_id'leri config.json'a ekle.")
        return {"fetched": 0, "new": 0}

    db.mark_tracked(conn, entries)
    page_ids = [str(p["page_id"]).strip() for p in entries]
    run_id = db.start_run(conn, "pages", ",".join(page_ids))
    fetched = new = 0

    try:
        batch: List[Dict[str, Any]] = []
        for ad in api.fetch_ads_for_pages(
            page_ids,
            countries=cfg.get("countries", ["TR"]),
            date_min=date_min or cfg.get("date_min"),
            active_status="ALL",
        ):
            batch.append(ad)
            if len(batch) >= 200:
                t, n = db.upsert_ads(conn, batch)
                fetched += t
                new += n
                print("  ... {} reklam yazıldı ({} yeni)".format(fetched, new))
                batch = []
        if batch:
            t, n = db.upsert_ads(conn, batch)
            fetched += t
            new += n
    except Exception as exc:  # çekim yarıda kalsa da yazılanlar korunur
        db.finish_run(conn, run_id, fetched, new, str(exc))
        raise

    db.finish_run(conn, run_id, fetched, new)
    return {"fetched": fetched, "new": new}


def discover(conn, cfg: Dict[str, Any], keywords: List[str], date_min: str = None) -> Dict[str, int]:
    """Kelime araması: hangi sayfaların siyasi reklam yayınladığını bulur."""
    run_id = db.start_run(conn, "discover", ",".join(keywords))
    fetched = new = 0

    try:
        for term in keywords:
            print("Aranıyor: {}".format(term))
            batch: List[Dict[str, Any]] = []
            for ad in api.fetch_ads(
                search_terms=term,
                countries=cfg.get("countries", ["TR"]),
                date_min=date_min or cfg.get("date_min"),
                active_status="ALL",
            ):
                batch.append(ad)
                if len(batch) >= 200:
                    t, n = db.upsert_ads(conn, batch)
                    fetched += t
                    new += n
                    batch = []
            if batch:
                t, n = db.upsert_ads(conn, batch)
                fetched += t
                new += n
            print("  toplam {} reklam ({} yeni)".format(fetched, new))
    except Exception as exc:
        db.finish_run(conn, run_id, fetched, new, str(exc))
        raise

    db.finish_run(conn, run_id, fetched, new)
    return {"fetched": fetched, "new": new}


def test_token(cfg: Dict[str, Any]) -> int:
    """Tek ve ucuz bir istekle token'ı ve erişimi doğrular.

    limit=1 ile çağırır; hem token'ın geçerli olduğunu hem de siyasi reklam
    arşivine erişimin açık olduğunu gösterir. Büyük çekimden önce bunu çalıştır.
    """
    print("Token ve erişim sınanıyor (tek istek)...")
    try:
        ad = next(api.fetch_ads(search_terms="a", countries=cfg.get("countries", ["TR"]),
                                limit=1, max_pages=1, pause=0), None)
    except api.AdLibraryError as exc:
        print("BAŞARISIZ: {}".format(exc), file=sys.stderr)
        if getattr(exc, "code", None) == 190:
            print("\n-> Token süresi dolmuş olabilir. Graph API Explorer'dan yeni token alıp "
                  "uzun ömürlüye çevir, .env içindeki FB_TOKEN'ı güncelle.", file=sys.stderr)
        return 1

    if ad is None:
        print("Token çalışıyor ama sonuç dönmedi.")
        print("Bu normal olabilir: arama kelimesi tutmadıysa ya da kimlik doğrulaman "
              "(facebook.com/ID) henüz onaylanmadıysa arşiv boş görünür.")
        return 0

    print("Başarılı. Örnek kayıt:")
    print("  sayfa      : {}".format(ad.get("page_name")))
    print("  başlangıç  : {}".format(ad.get("ad_delivery_start_time")))
    print("  finansman  : {}".format(ad.get("bylines")))
    print("  harcama    : {}".format(ad.get("spend")))
    return 0


def kisi_tara(conn, cfg: Dict[str, Any], kisiler: List[str],
              date_min: str = None) -> Dict[str, int]:
    """Kişi ismiyle tam ifade araması yapar ve kimin kimden bahsettiğini kaydeder.

    Her isim için ayrı bir arama: dönen reklamlar hem o kişinin kendi
    reklamları hem de rakiplerinin ondan bahseden reklamları olabilir.
    Ayrımı rapor.py yapar (sayfa adı == kişi adı ise "kendi", değilse "bahseden").
    """
    run_id = db.start_run(conn, "kisi", ",".join(kisiler))
    fetched = new = 0

    try:
        for kisi in kisiler:
            print("Aranıyor (tam ifade): {}".format(kisi))
            bulunan: List[Dict[str, Any]] = []
            for ad in api.fetch_ads(
                search_terms=kisi,
                search_type="KEYWORD_EXACT_PHRASE",
                countries=cfg.get("countries", ["TR"]),
                date_min=date_min or cfg.get("date_min"),
                active_status="ALL",
            ):
                bulunan.append(ad)

            if bulunan:
                t, n = db.upsert_ads(conn, bulunan)
                db.record_mentions(conn, [a["id"] for a in bulunan], kisi)
                fetched += t
                new += n
                sayfalar = len({a.get("page_id") for a in bulunan})
                print("  {} reklam, {} farklı sayfa ({} yeni)".format(len(bulunan), sayfalar, n))
            else:
                print("  sonuç yok")
    except Exception as exc:
        db.finish_run(conn, run_id, fetched, new, str(exc))
        raise

    db.finish_run(conn, run_id, fetched, new)
    return {"fetched": fetched, "new": new}


def main() -> int:
    parser = argparse.ArgumentParser(description="Meta Ad Library toplayıcı")
    parser.add_argument("--discover", nargs="?", const="__config__", default=None,
                        help="Kelime ile sayfa keşfi. Değer verilmezse config.json'daki keywords kullanılır.")
    parser.add_argument("--days", type=int, default=None,
                        help="Sadece son N gün içinde yayınlanan reklamlar")
    parser.add_argument("--db", default=db.DEFAULT_DB, help="SQLite dosya yolu")
    parser.add_argument("--kisi", nargs="?", const="__config__", default=None,
                        help="Kişi ismiyle tam ifade araması (virgülle ayır). "
                             "Değer verilmezse config.json'daki kisiler listesi kullanılır.")
    parser.add_argument("--test", action="store_true",
                        help="Tek istekle token'ı ve arşiv erişimini doğrula, hiçbir şey yazma")
    args = parser.parse_args()

    load_env()
    cfg = load_config()

    if args.test:
        return test_token(cfg)

    conn = db.connect(args.db)

    date_min = None
    if args.days:
        date_min = (date.today() - timedelta(days=args.days)).isoformat()

    try:
        if args.kisi is not None:
            kisiler = (cfg.get("kisiler", []) + cfg.get("kurumlar", [])
                       if args.kisi == "__config__"
                       else [k.strip() for k in args.kisi.split(",") if k.strip()])
            if not kisiler:
                print("Kişi listesi boş: config.json içindeki kisiler listesini doldur.")
                return 1
            result = kisi_tara(conn, cfg, kisiler, date_min)
        elif args.discover is not None:
            keywords = (cfg.get("keywords", []) if args.discover == "__config__"
                        else [k.strip() for k in args.discover.split(",") if k.strip()])
            if not keywords:
                print("Anahtar kelime yok: config.json içindeki keywords listesini doldur.")
                return 1
            result = discover(conn, cfg, keywords, date_min)
        else:
            result = collect_pages(conn, cfg, date_min)
    except api.AdLibraryError as exc:
        print("HATA: {}".format(exc), file=sys.stderr)
        return 1

    print("\nBitti: {} reklam işlendi, {} tanesi yeni.".format(result["fetched"], result["new"]))
    print("Veritabanı: {}".format(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

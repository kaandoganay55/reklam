#!/usr/bin/env python3
"""Kişi bazlı rakip raporu.

    python3 rapor.py                     # config.json'daki kisiler
    python3 rapor.py "Halit Doğan" "X Y"

Her isim için iki şeyi ayırır:
  KENDİ    — sayfa adı kişiyle eşleşen reklamlar (kişinin kendi kampanyası)
  BAHSEDEN — ismi geçen ama başka bir sayfanın verdiği reklamlar (rakip/haber)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import unicodedata

import pandas as pd

import db as store

HERE = os.path.dirname(os.path.abspath(__file__))


def sadelestir(s: str) -> str:
    """Türkçe karakterleri ve büyük/küçük farkını yok sayarak karşılaştırma anahtarı."""
    if not s:
        return ""
    s = s.replace("ı", "i").replace("İ", "i").replace("ğ", "g").replace("Ğ", "g")
    s = s.replace("ş", "s").replace("Ş", "s").replace("ç", "c").replace("Ç", "c")
    s = s.replace("ö", "o").replace("Ö", "o").replace("ü", "u").replace("Ü", "u")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def haric_liste() -> set:
    """config.json'daki elenecek sayfa adları (tam eşleşme)."""
    yol = os.path.join(HERE, "config.json")
    if not os.path.exists(yol):
        return set()
    with open(yol, encoding="utf-8") as fh:
        return set(json.load(fh).get("haric_sayfalar", []))


def tl(alt, ust) -> str:
    f = lambda v: "{:,.0f}".format(v or 0).replace(",", ".")
    return "{} – {} ₺".format(f(alt), f(ust))


def rapor(db_path: str, kisiler: list) -> None:
    conn = sqlite3.connect(db_path)
    try:
        m = pd.read_sql_query("SELECT * FROM mentions", conn)
        ads = pd.read_sql_query("SELECT * FROM ads", conn)
    finally:
        conn.close()

    if m.empty:
        print("Henüz kişi araması yapılmamış. Önce:  python3 collector.py --kisi")
        return

    ads["alt"] = pd.to_numeric(ads.spend_lower, errors="coerce").fillna(0)
    ads["ust"] = pd.to_numeric(ads.spend_upper, errors="coerce").fillna(ads["alt"])
    df = m.merge(ads, on="ad_id", how="inner")

    ozet = []
    for kisi in kisiler:
        g = df[df.kisi == kisi]
        if g.empty:
            print("\n" + "=" * 78)
            print("{}  —  hiç reklam bulunamadı".format(kisi.upper()))
            print("Bu kişi beyanlı siyasi reklam vermemiş ve adı reklam metinlerinde geçmiyor.")
            continue

        anahtar = sadelestir(kisi)
        g = g[~g.page_name.isin(haric_liste())].copy()
        if g.empty:
            print("\n" + "=" * 78)
            print("{}  —  eşleşen tüm sayfalar hariç listesinde".format(kisi.upper()))
            continue
        g["kendi"] = g.page_name.fillna("").map(
            lambda p: anahtar in sadelestir(p) or sadelestir(p) in anahtar)

        kendi, baska = g[g.kendi], g[~g.kendi]
        print("\n" + "=" * 78)
        print("{}  —  {} reklam, {} farklı sayfa".format(
            kisi.upper(), len(g), g.page_id.nunique()))
        print("-" * 78)

        print("KENDİ KAMPANYASI : {} reklam · {} yayında · {}".format(
            len(kendi), int(kendi.is_active.sum()) if len(kendi) else 0,
            tl(kendi.alt.sum(), kendi.ust.sum()) if len(kendi) else "—"))
        print("ADI GEÇEN DİĞER  : {} reklam · {} sayfa · {}".format(
            len(baska), baska.page_id.nunique(),
            tl(baska.alt.sum(), baska.ust.sum()) if len(baska) else "—"))

        if not baska.empty:
            print("\n  Adından bahseden sayfalar:")
            t = (baska.groupby("page_name")
                 .agg(reklam=("ad_id", "count"), yayinda=("is_active", "sum"),
                      alt=("alt", "sum"), ust=("ust", "sum"))
                 .sort_values("reklam", ascending=False).head(10))
            for ad, r in t.iterrows():
                print("    {:<38} {:>3} reklam  {:>2} yayında  {}".format(
                    (ad or "—")[:38], int(r.reklam), int(r.yayinda), tl(r.alt, r.ust)))

        ozet.append({
            "Kişi": kisi,
            "Kendi reklamı": len(kendi),
            "Yayında": int(kendi.is_active.sum()) if len(kendi) else 0,
            "Kendi harcaması": tl(kendi.alt.sum(), kendi.ust.sum()) if len(kendi) else "—",
            "Adı geçen": len(baska),
            "Bahseden sayfa": baska.page_id.nunique(),
        })

    if ozet:
        print("\n" + "=" * 78)
        print("KARŞILAŞTIRMA")
        print("=" * 78)
        print(pd.DataFrame(ozet).to_string(index=False))
        print("\nHarcamalar API'nin verdiği alt/üst sınırların toplamıdır, kesin rakam değildir.")


def main() -> int:
    kisiler = sys.argv[1:]
    if not kisiler:
        cfg_path = os.path.join(HERE, "config.json")
        with open(cfg_path, encoding="utf-8") as fh:
            kisiler = json.load(fh).get("kisiler", [])
    if not kisiler:
        print("Kişi listesi boş. config.json içindeki kisiler listesini doldur "
              "ya da isimleri argüman olarak ver.")
        return 1
    rapor(store.DEFAULT_DB, kisiler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

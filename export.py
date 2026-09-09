#!/usr/bin/env python3
"""SQLite'taki veriyi HTML panelinin beklediği JSON'a çevirir.

Veri **reklam bazında** gider: panel tüm toplamları (ölçümler, çubuklar, günlük
seri, tablo) tarayıcıda bu satırlardan hesaplar. Sayfa toplamı göndermek yerine
böyle yapılıyor ki tarih filtresi her şeyi doğru yeniden hesaplayabilsin.

    python3 export.py --kisiler              # adayların kendi sayfaları
    python3 export.py --gun 90               # son 90 gün
    python3 export.py --sayfa 8              # kaç sayfa gösterilsin
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
from datetime import date

import pandas as pd

import db as store
from rapor import sadelestir, haric_liste

HERE = os.path.dirname(os.path.abspath(__file__))


GORSEL_KLASOR = os.path.join(HERE, "gorseller")


def gorsel_uri(ad_id: str) -> str:
    """İndirilmiş küçük resmi data: URI olarak döndürür.

    Artifact sayfasının CSP'si dış görsel yüklemeye izin vermediği için
    resimler sayfaya gömülmek zorunda.
    """
    yol = os.path.join(GORSEL_KLASOR, str(ad_id) + ".jpg")
    if not os.path.exists(yol):
        return None
    with open(yol, "rb") as fh:
        return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()


def build(db_path: str, gun: int = 0, sadece_kisiler: bool = False,
          sayfa_sayisi: int = 5, gorseller: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM ads", conn)
    finally:
        conn.close()
    if df.empty:
        raise SystemExit("Veritabanı boş. Önce collector.py ile veri çek.")

    df["bas"] = pd.to_datetime(df["delivery_start"], errors="coerce", utc=True).dt.tz_localize(None)
    df["bit"] = pd.to_datetime(df["delivery_stop"], errors="coerce", utc=True).dt.tz_localize(None)
    df["sayfa"] = df["page_name"].fillna(df["page_id"]).fillna("Bilinmiyor")
    df = df[df["bas"].notna()]

    if sadece_kisiler:
        # config.json > pages listesindeki sayfa ID'leri (isim eşleştirme değil:
        # aynı adı taşıyan başka sayfalar karışıyordu, kurumlar da dışarıda kalıyordu)
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as fh:
            kimlikler = {str(x["page_id"]) for x in json.load(fh).get("pages", [])}
        df = df[df["page_id"].astype(str).isin(kimlikler)]
        df = df[~df["sayfa"].isin(haric_liste())]
        if df.empty:
            raise SystemExit("Aday sayfası yok. Önce: python3 collector.py --kisi")

    if gun > 0:
        esik = pd.Timestamp(date.today()) - pd.Timedelta(days=gun - 1)
        df = df[df["bas"] >= esik]

    for c in ("spend_lower", "spend_upper", "impr_lower", "impr_upper",
              "audience_lower", "audience_upper"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Panelin kategorik paleti sınırlı: en çok harcayan N sayfa gösterilir.
    sira = (df.groupby("sayfa")["spend_lower"].sum()
              .sort_values(ascending=False).head(sayfa_sayisi).index.tolist())
    df = df[df["sayfa"].isin(sira)]

    sayfa_idx = {ad: i for i, ad in enumerate(sira)}
    reklamlar = []
    gorselli = 0
    for _, r in df.sort_values("bas", ascending=False).iterrows():
        kayit = {
            "id": r["ad_id"],
            "s": sayfa_idx[r["sayfa"]],
            "b": r["bas"].strftime("%Y-%m-%d"),
            "e": None if pd.isna(r["bit"]) else r["bit"].strftime("%Y-%m-%d"),
            "hl": None if pd.isna(r["spend_lower"]) else int(r["spend_lower"]),
            "hu": None if pd.isna(r["spend_upper"]) else int(r["spend_upper"]),
            "gl": None if pd.isna(r["impr_lower"]) else int(r["impr_lower"]),
            "gu": None if pd.isna(r["impr_upper"]) else int(r["impr_upper"]),
            "al": None if pd.isna(r["audience_lower"]) else int(r["audience_lower"]),
            "au": None if pd.isna(r["audience_upper"]) else int(r["audience_upper"]),
            "p": [x.lower() for x in (r["platforms"] or "").split(",") if x],
            "t": (r["body"] or "").replace("\n", " ").strip()[:160],
            "f": (r["bylines"] or "")[:60],
        }
        if gorseller:
            uri = gorsel_uri(r["ad_id"])
            if uri:
                kayit["g"] = uri
                gorselli += 1
        reklamlar.append(kayit)

    return {
        "gorselli": gorselli,
        "sayfalar": sira,
        "reklamlar": reklamlar,
        "ilk": df["bas"].min().strftime("%Y-%m-%d"),
        "son": df["bas"].max().strftime("%Y-%m-%d"),
        "cekim": date.today().strftime("%Y-%m-%d"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Paneli HTML'e aktarmak için JSON üret")
    ap.add_argument("--db", default=store.DEFAULT_DB)
    ap.add_argument("--gun", type=int, default=0, help="Son N gün (0 = tüm veri)")
    ap.add_argument("--kisiler", action="store_true",
                    help="Sadece config.json'daki adayların kendi sayfaları")
    ap.add_argument("--sayfa", type=int, default=5, help="Kaç sayfa gösterilsin (varsayılan 5)")
    ap.add_argument("--gorsel", action="store_true",
                    help="İndirilmiş reklam görsellerini data: URI olarak göm")
    ap.add_argument("--cikti", default=os.path.join(HERE, "veri.json"))
    a = ap.parse_args()

    veri = build(a.db, a.gun, a.kisiler, a.sayfa, a.gorsel)
    with open(a.cikti, "w", encoding="utf-8") as fh:
        json.dump(veri, fh, ensure_ascii=False, separators=(",", ":"))
    boyut = os.path.getsize(a.cikti) / 1024
    print("Yazıldı: {} ({:.0f} KB)".format(a.cikti, boyut))
    print("{} reklam · {} sayfa · {} -> {}".format(
        len(veri["reklamlar"]), len(veri["sayfalar"]), veri["ilk"], veri["son"]))
    if a.gorsel:
        print("Görselli reklam: {} / {}".format(veri["gorselli"], len(veri["reklamlar"])))
    print("Sayfalar: " + ", ".join(veri["sayfalar"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Access token ömrünü uzatır ve kalan süreyi gösterir.

    python3 fbtoken.py --kontrol          # mevcut token ne zaman ölüyor?
    python3 fbtoken.py --uzat KISA_TOKEN  # uzun ömürlüye çevir ve .env'e yaz

Token ömürleri:
  Graph API Explorer token'ı  ~1-2 saat   (varsayılan, bu bizi yaktı)
  Uzun ömürlü kullanıcı token'ı  ~60 gün  (--uzat bunu üretir)
  Sistem kullanıcısı token'ı     süresiz  (Business Manager'dan, cron için ideal)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import requests

from collector import ENV_PATH, load_env

SURUM = os.environ.get("FB_GRAPH_VERSION", "v23.0")
GRAPH = "https://graph.facebook.com/" + SURUM


def env_yaz(anahtar: str, deger: str) -> None:
    """.env içindeki bir satırı günceller, yoksa ekler."""
    satirlar = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as fh:
            satirlar = fh.read().splitlines()
    bulundu = False
    for i, s in enumerate(satirlar):
        if s.strip().startswith(anahtar + "="):
            satirlar[i] = "{}={}".format(anahtar, deger)
            bulundu = True
            break
    if not bulundu:
        satirlar.append("{}={}".format(anahtar, deger))
    with open(ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(satirlar) + "\n")
    os.chmod(ENV_PATH, 0o600)


def kalan_sure(bitis: int) -> str:
    if not bitis:
        return "süresiz"
    kalan = datetime.fromtimestamp(bitis, timezone.utc) - datetime.now(timezone.utc)
    if kalan.total_seconds() <= 0:
        return "SÜRESİ DOLMUŞ"
    gun, saat = kalan.days, kalan.seconds // 3600
    return "{} gün {} saat".format(gun, saat) if gun else "{} saat {} dakika".format(
        saat, (kalan.seconds % 3600) // 60)


def kontrol(token: str, app_id: str, app_secret: str) -> int:
    if not (app_id and app_secret):
        print("FB_APP_ID ve FB_APP_SECRET .env'de yok — kalan süre sorgulanamıyor.\n"
              "developers.facebook.com > uygulaman > Ayarlar > Temel'den alıp .env'e ekle.",
              file=sys.stderr)
        return 1
    r = requests.get(GRAPH + "/debug_token", timeout=30, params={
        "input_token": token, "access_token": "{}|{}".format(app_id, app_secret)})
    veri = r.json().get("data", {})
    if "error" in r.json() or not veri:
        print("Sorgulanamadı: {}".format(r.json().get("error", {}).get("message", r.text[:200])),
              file=sys.stderr)
        return 1

    bitis = veri.get("expires_at", 0)
    print("Geçerli mi   : {}".format("evet" if veri.get("is_valid") else "HAYIR"))
    print("Tür          : {}".format(veri.get("type", "?")))
    print("Uygulama     : {}".format(veri.get("app_id", "?")))
    print("Bitiş        : {}".format(
        datetime.fromtimestamp(bitis, timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")
        if bitis else "süresiz"))
    print("Kalan süre   : {}".format(kalan_sure(bitis)))
    if bitis and (datetime.fromtimestamp(bitis, timezone.utc) -
                  datetime.now(timezone.utc)).days < 7:
        print("\nUYARI: bir haftadan az kalmış. Yenile:  python3 fbtoken.py --uzat YENI_KISA_TOKEN")
    return 0


def uzat(kisa: str, app_id: str, app_secret: str) -> int:
    if not (app_id and app_secret):
        print("FB_APP_ID ve FB_APP_SECRET .env'de olmalı.\n"
              "developers.facebook.com > uygulaman > Ayarlar > Temel", file=sys.stderr)
        return 1
    r = requests.get(GRAPH + "/oauth/access_token", timeout=30, params={
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": kisa})
    veri = r.json()
    if "error" in veri:
        print("Değişim başarısız: {}".format(veri["error"].get("message", "")), file=sys.stderr)
        return 1

    yeni = veri["access_token"]
    env_yaz("FB_TOKEN", yeni)
    print("Uzun ömürlü token .env'e yazıldı.")
    if veri.get("expires_in"):
        print("Ömür: yaklaşık {} gün".format(round(veri["expires_in"] / 86400)))
    print()
    return kontrol(yeni, app_id, app_secret)


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Access token ömrünü yönet")
    ap.add_argument("--kontrol", action="store_true", help="Mevcut token ne zaman ölüyor")
    ap.add_argument("--uzat", metavar="KISA_TOKEN", help="Uzun ömürlüye çevir ve .env'e yaz")
    a = ap.parse_args()

    app_id = os.environ.get("FB_APP_ID", "").strip()
    app_secret = os.environ.get("FB_APP_SECRET", "").strip()

    if a.uzat:
        return uzat(a.uzat.strip(), app_id, app_secret)
    if a.kontrol:
        token = os.environ.get("FB_TOKEN", "").strip()
        if not token:
            print("FB_TOKEN .env'de yok.", file=sys.stderr)
            return 1
        return kontrol(token, app_id, app_secret)

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

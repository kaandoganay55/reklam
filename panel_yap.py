#!/usr/bin/env python3
"""panel.html şablonundan yayına hazır dosyaları üretir.

    python3 panel_yap.py

Üretilenler:
  index.html         GitHub Pages için TAM HTML belgesi (doctype + head + viewport)
  panel-artifact.html Claude artifact için gövde (artifact sarmalayıcıyı kendi ekler)

Neden iki dosya: artifact sistemi <!doctype>, <head> ve viewport'u kendisi ekliyor.
Aynı dosyayı Pages'e koyunca viewport eksik kalıyor ve mobil tarayıcı sayfayı
980px genişlikte varsayıp masaüstü düzenini küçültüyor. Bu script farkı kapatır.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SABLON = os.path.join(HERE, "panel.html")
VERI = os.path.join(HERE, "veri.json")

BASLIK = "Reklam Kütüphanesi Paneli"
ACIKLAMA = ("Samsun yerel siyaset aktörlerinin Meta Reklam Kütüphanesi'ndeki "
            "siyasi reklamları: harcama, gösterim ve kreatif dökümü.")

# Artifact sarmalayıcısının verdiği sıfırlama + mobil için şart olan viewport
KAFA = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="description" content="{aciklama}">
<meta name="theme-color" content="#f6f6f3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#121312" media="(prefers-color-scheme: dark)">
<meta property="og:title" content="{baslik}">
<meta property="og:description" content="{aciklama}">
<meta property="og:type" content="website">
<style>
  html{{-webkit-text-size-adjust:100%}}
  /* Zemin body'ye de yazılıyor: mobilde sayfayı aşağı çekince (rubber-band)
     ve içerik ekrandan kısa kaldığında tema rengi görünsün. */
  body{{margin:0;background:#f6f6f3}}
  @media (prefers-color-scheme:dark){{
    html:not([data-theme="light"]) body{{background:#121312}}
  }}
  html[data-theme="dark"] body{{background:#121312}}
  img{{max-width:100%}}
  [hidden]{{display:none!important}}
</style>
"""


def parcala(sablon: str):
    """Şablonu head'e ve gövdeye ayırır (ilk sayfa kabından itibaren gövde)."""
    i = sablon.index('<div class="min-h-screen')
    return sablon[:i].rstrip(), sablon[i:]


def main() -> int:
    for yol in (SABLON, VERI):
        if not os.path.exists(yol):
            print("eksik dosya: {}".format(yol), file=sys.stderr)
            return 1

    sablon = open(SABLON, encoding="utf-8").read()
    veri_ham = open(VERI, encoding="utf-8").read()
    veri = json.loads(veri_ham)                     # bozuksa burada patlasın

    if "__DATA__" not in sablon:
        print("panel.html içinde __DATA__ yer tutucusu yok.", file=sys.stderr)
        return 1
    # re.sub kullanma: veri içindeki \n gibi kaçışları yorumlar ve JSON'u bozar
    dolu = sablon.replace("__DATA__", veri_ham, 1)
    # Sürüm damgası: tarayıcı önbelleği yüzünden eski sürüme bakıldığını
    # anlamak zor oluyordu; sayfanın dibinde derleme anı yazıyor.
    damga = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    dolu = dolu.replace("__BUILD__", damga)

    kafa_ic, govde = parcala(dolu)

    with open(os.path.join(HERE, "panel-artifact.html"), "w", encoding="utf-8") as fh:
        fh.write(dolu)

    tam = (KAFA.format(baslik=BASLIK, aciklama=ACIKLAMA) +
           kafa_ic + "\n</head>\n<body>\n" + govde.rstrip() + "\n</body>\n</html>\n")
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(tam)

    mb = len(tam.encode()) / 1024 / 1024
    print("index.html         : {:.2f} MB  (viewport ✓, doctype ✓)".format(mb))
    print("panel-artifact.html: {:.2f} MB".format(len(dolu.encode()) / 1024 / 1024))
    print("içerik             : {} sayfa · {} reklam · {} görsel".format(
        len(veri["sayfalar"]), len(veri["reklamlar"]), veri.get("gorselli", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

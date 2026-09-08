#!/usr/bin/env python3
"""Reklam Kütüphanesi Paneli — kim, hangi siyasi reklamı yayınlıyor.

Çalıştırma:  streamlit run app.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st

import db as store
import viz

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ADLIB_DB", store.DEFAULT_DB)

st.set_page_config(page_title="Reklam Kütüphanesi Paneli",
                   page_icon="📢", layout="wide")


def current_theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


THEME = current_theme()


# ---------------------------------------------------------------- veri yükleme

@st.cache_data(show_spinner=False)
def load_ads(path: str, stamp: float) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    conn = sqlite3.connect(path)
    try:
        df = pd.read_sql_query("SELECT * FROM ads", conn)
    finally:
        conn.close()
    if df.empty:
        return df

    df["baslangic"] = pd.to_datetime(df["delivery_start"], errors="coerce", utc=True).dt.tz_localize(None)
    df["bitis"] = pd.to_datetime(df["delivery_stop"], errors="coerce", utc=True).dt.tz_localize(None)
    df["sayfa"] = df["page_name"].fillna(df["page_id"]).fillna("Bilinmiyor")
    df["durum"] = np.where(df["is_active"] == 1, "Yayında", "Bitmiş")
    # Aralıkların orta noktası: kesin değil, "tahmini" olarak sunulur.
    # Üst sınır açık uçlu kovalarda ("100000+") hiç gelmez -> alt sınıra düşeriz.
    for hedef, alt_c, ust_c in (("harcama_orta", "spend_lower", "spend_upper"),
                                ("gosterim_orta", "impr_lower", "impr_upper")):
        alt_v = pd.to_numeric(df[alt_c], errors="coerce")
        ust_v = pd.to_numeric(df[ust_c], errors="coerce")
        df[hedef] = pd.concat([alt_v, ust_v], axis=1).mean(axis=1).fillna(alt_v)
    df["sure_gun"] = ((df["bitis"].fillna(pd.Timestamp.utcnow().tz_localize(None)) -
                       df["baslangic"]).dt.days).clip(lower=0)
    return df


@st.cache_data(show_spinner=False)
def load_runs(path: str, stamp: float) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    conn = sqlite3.connect(path)
    try:
        return pd.read_sql_query(
            "SELECT started_at, finished_at, mode, query, fetched, new_ads, error "
            "FROM runs ORDER BY id DESC LIMIT 25", conn)
    finally:
        conn.close()


def db_stamp(path: str) -> float:
    return os.path.getmtime(path) if os.path.exists(path) else 0.0


stamp = db_stamp(DB_PATH)
ads = load_ads(DB_PATH, stamp)


# ---------------------------------------------------------------------- filtre

st.sidebar.title("Filtreler")

if ads.empty:
    st.sidebar.info("Veritabanı boş.")
    filtered = ads
else:
    min_d = ads["baslangic"].min()
    min_d = (min_d.date() if pd.notna(min_d) else date.today() - timedelta(days=365))
    default_start = max(min_d, date.today() - timedelta(days=180))
    tarih = st.sidebar.date_input(
        "Yayın tarihi aralığı", value=(default_start, date.today()),
        min_value=min_d, max_value=date.today(),
    )
    if isinstance(tarih, tuple) and len(tarih) == 2:
        d_start, d_end = tarih
    else:
        d_start, d_end = default_start, date.today()

    sayfalar = sorted(ads["sayfa"].dropna().unique().tolist())
    secili = st.sidebar.multiselect("Sayfalar", sayfalar, default=[])
    durum = st.sidebar.radio("Durum", ["Hepsi", "Yayında", "Bitmiş"], horizontal=True)

    tum_platformlar = sorted({p for row in ads["platforms"].dropna()
                              for p in row.split(",") if p})
    platform = st.sidebar.multiselect("Platform", tum_platformlar, default=[])
    arama = st.sidebar.text_input("Reklam metninde ara")

    m = (ads["baslangic"].dt.date >= d_start) & (ads["baslangic"].dt.date <= d_end)
    if secili:
        m &= ads["sayfa"].isin(secili)
    if durum != "Hepsi":
        m &= ads["durum"] == durum
    if platform:
        m &= ads["platforms"].fillna("").apply(
            lambda s: any(p in s.split(",") for p in platform))
    if arama:
        haystack = (ads["body"].fillna("") + " " + ads["link_title"].fillna("") + " " +
                    ads["link_description"].fillna(""))
        m &= haystack.str.contains(arama, case=False, na=False)
    filtered = ads[m]

st.sidebar.divider()
st.sidebar.caption("Veritabanı: `{}`".format(os.path.basename(DB_PATH)))
if stamp:
    st.sidebar.caption("Son güncelleme: {}".format(
        pd.Timestamp.fromtimestamp(stamp).strftime("%d.%m.%Y %H:%M")))


# ------------------------------------------------------------------- başlık

st.title("📢 Reklam Kütüphanesi Paneli")
st.caption("Meta Ad Library · Türkiye · siyasi ve sosyal konulu reklamlar")

if ads.empty:
    st.warning(
        "Henüz veri yok. Aşağıdaki **Veri Çekme** sekmesinden ilk çekimi başlat "
        "ya da terminalde `python3 collector.py --discover` çalıştır."
    )


def fmt_int(x) -> str:
    return "—" if pd.isna(x) else "{:,.0f}".format(x).replace(",", ".")


def fmt_kisa(x) -> str:
    """st.metric dar olduğu için büyük tutarları kısaltır: 118.400 -> 118 B."""
    if pd.isna(x):
        return "—"
    for esik, birim in ((1e9, "Mr"), (1e6, "Mn"), (1e3, "B")):
        if abs(x) >= esik:
            return "{:.1f} {}".format(x / esik, birim).replace(".0 ", " ").replace(".", ",")
    return "{:,.0f}".format(x).replace(",", ".")


c1, c2, c3, c4 = st.columns(4)
c1.metric("Reklam", fmt_int(len(filtered)) if not filtered.empty else "0")
c2.metric("Yayında", fmt_int((filtered["durum"] == "Yayında").sum()) if not filtered.empty else "0")
c3.metric("Sayfa", fmt_int(filtered["sayfa"].nunique()) if not filtered.empty else "0")
if not filtered.empty:
    lo = filtered["spend_lower"].sum(skipna=True)
    hi = filtered["spend_upper"].fillna(filtered["spend_lower"]).sum(skipna=True)
    c4.metric("Tahmini harcama", "{} – {} ₺".format(fmt_kisa(lo), fmt_kisa(hi)),
              help="API harcamayı kesin rakam değil aralık olarak verir. "
                   "Tam değer: {} – {} ₺".format(fmt_int(lo), fmt_int(hi)))
else:
    c4.metric("Tahmini harcama", "—")


# --------------------------------------------------------------------- sekmeler

tabs = st.tabs(["Genel Bakış", "Sayfa Karşılaştırma", "Reklamlar",
                "Sayfa Keşfi", "Veri Çekme"])


with tabs[0]:
    if filtered.empty:
        st.info("Seçilen filtrelerde reklam yok.")
    else:
        end = pd.Timestamp(date.today())
        start = max(pd.Timestamp(d_start), filtered["baslangic"].min())
        days = pd.date_range(start.normalize(), end.normalize(), freq="D")

        rows = []
        weight = filtered.groupby("sayfa").size().sort_values(ascending=False)
        for sayfa in weight.head(viz.MAX_SERIES + 4).index:
            g = filtered[filtered["sayfa"] == sayfa]
            s = g["baslangic"].values.astype("datetime64[D]")
            e = g["bitis"].fillna(end).values.astype("datetime64[D]")
            d = days.values.astype("datetime64[D]")
            counts = ((s[None, :] <= d[:, None]) & (e[None, :] >= d[:, None])).sum(axis=1)
            rows.append(pd.DataFrame({"tarih": days, "sayfa": sayfa, "aktif": counts}))

        daily = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
        if not daily.empty:
            st.altair_chart(
                viz.active_over_time(daily, THEME, "Günlük yayında olan reklam sayısı"),
                use_container_width=True)

        haftalik = (filtered.set_index("baslangic").resample("W")
                    .size().reset_index(name="adet")
                    .rename(columns={"baslangic": "hafta"}))
        st.altair_chart(
            viz.volume_over_time(haftalik, THEME, "Haftalık yeni başlayan reklam"),
            use_container_width=True)

        yeni = filtered[filtered["baslangic"] >= pd.Timestamp(date.today() - timedelta(days=7))]
        if not yeni.empty:
            st.subheader("Son 7 günde başlayan reklamlar")
            st.dataframe(
                yeni[["sayfa", "baslangic", "durum", "body", "snapshot_url"]]
                .sort_values("baslangic", ascending=False)
                .rename(columns={"sayfa": "Sayfa", "baslangic": "Başlangıç",
                                 "durum": "Durum", "body": "Metin",
                                 "snapshot_url": "Reklam"}),
                use_container_width=True, hide_index=True,
                column_config={"Reklam": st.column_config.LinkColumn("Reklam", display_text="aç")},
            )


with tabs[1]:
    if filtered.empty:
        st.info("Seçilen filtrelerde reklam yok.")
    else:
        ozet = (filtered.groupby("sayfa")
                .agg(reklam=("ad_id", "count"),
                     harcama=("harcama_orta", "sum"),
                     gosterim=("gosterim_orta", "sum"))
                .reset_index().sort_values("harcama", ascending=False))
        top = ozet.head(15)

        left, right = st.columns(2)
        with left:
            st.altair_chart(
                viz.ranked_bar(top, "sayfa", "harcama", THEME,
                               "Tahmini harcama (₺)", "Tahmini harcama"),
                use_container_width=True)
            st.caption("Aralıkların orta noktasından hesaplanan tahmindir, kesin harcama değildir.")
        with right:
            st.altair_chart(
                viz.ranked_bar(top, "sayfa", "gosterim", THEME,
                               "Tahmini gösterim", "Tahmini gösterim"),
                use_container_width=True)
            st.caption("Aralıkların orta noktasından hesaplanan tahmindir.")

        durum_df = (filtered.groupby(["sayfa", "durum"]).size()
                    .reset_index(name="adet"))
        durum_df = durum_df[durum_df["sayfa"].isin(top["sayfa"])]
        st.altair_chart(
            viz.status_bar(durum_df, THEME, "Sayfa başına yayında / bitmiş reklam"),
            use_container_width=True)

        st.subheader("Sayfa özeti")
        st.dataframe(
            ozet.rename(columns={"sayfa": "Sayfa", "reklam": "Reklam",
                                 "harcama": "Tahmini harcama (₺)",
                                 "gosterim": "Tahmini gösterim"}),
            use_container_width=True, hide_index=True)


with tabs[2]:
    if filtered.empty:
        st.info("Seçilen filtrelerde reklam yok.")
    else:
        tablo = filtered[[
            "sayfa", "bylines", "baslangic", "bitis", "durum", "sure_gun",
            "spend_lower", "spend_upper", "impr_lower", "impr_upper",
            "platforms", "body", "snapshot_url", "ad_id",
        ]].sort_values("baslangic", ascending=False)
        st.dataframe(
            tablo.rename(columns={
                "sayfa": "Sayfa", "bylines": "Finansman", "baslangic": "Başlangıç",
                "bitis": "Bitiş", "durum": "Durum", "sure_gun": "Gün",
                "spend_lower": "Harcama alt", "spend_upper": "Harcama üst",
                "impr_lower": "Gösterim alt", "impr_upper": "Gösterim üst",
                "platforms": "Platformlar", "body": "Metin",
                "snapshot_url": "Reklam", "ad_id": "Reklam ID"}),
            use_container_width=True, hide_index=True, height=460,
            column_config={"Reklam": st.column_config.LinkColumn("Reklam", display_text="aç")},
        )
        st.download_button(
            "CSV indir", tablo.to_csv(index=False).encode("utf-8-sig"),
            file_name="reklamlar.csv", mime="text/csv")

        st.subheader("Reklam detayı")
        secim = st.selectbox("Reklam seç", tablo["ad_id"].tolist(),
                             format_func=lambda i: "{} · {}".format(
                                 tablo.loc[tablo["ad_id"] == i, "sayfa"].iloc[0],
                                 (tablo.loc[tablo["ad_id"] == i, "body"].iloc[0] or "")[:70]))
        if secim:
            row = filtered[filtered["ad_id"] == secim].iloc[0]
            d1, d2 = st.columns([2, 1])
            with d1:
                st.markdown("**Metin**")
                st.write(row["body"] or "—")
                if row["snapshot_url"]:
                    st.markdown("[Reklamı Ad Library'de aç]({})".format(row["snapshot_url"]))
                    st.caption("Bu bağlantı görseli/videoyu gösterir ama Facebook oturumu gerektirir.")
            with d2:
                st.markdown("**Hedefleme**")
                st.write("Yaş: {}".format(row["target_ages"] or "—"))
                st.write("Cinsiyet: {}".format(row["target_gender"] or "—"))
                if row["regions"]:
                    reg = pd.DataFrame(json.loads(row["regions"]))
                    if not reg.empty:
                        reg["percentage"] = reg["percentage"].astype(float)
                        st.dataframe(reg.sort_values("percentage", ascending=False).head(8),
                                     use_container_width=True, hide_index=True)


with tabs[3]:
    st.markdown(
        "Kelime aramasıyla bulunan tüm sayfalar. Takip etmek istediklerinin "
        "`page_id`'sini `config.json` içindeki `pages` listesine ekle."
    )
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            pages = pd.DataFrame([dict(r) for r in store.discovered_pages(conn)])
        finally:
            conn.close()
    else:
        pages = pd.DataFrame()

    if pages.empty:
        st.info("Henüz sayfa yok. **Veri Çekme** sekmesinden kelime keşfi çalıştır.")
    else:
        pages["tracked"] = pages["tracked"].map({1: "✓", 0: ""})
        st.dataframe(
            pages.rename(columns={"page_id": "Sayfa ID", "ad_page_name": "Sayfa",
                                  "tracked": "Takipte", "ad_count": "Reklam",
                                  "active_count": "Yayında", "last_ad": "Son reklam"}),
            use_container_width=True, hide_index=True)

        st.markdown("**config.json için hazır blok** (istediklerini seç, kopyala):")
        secilenler = st.multiselect("Sayfa seç", pages["ad_page_name"].tolist())
        if secilenler:
            blok = [{"page_id": str(r["page_id"]), "label": r["ad_page_name"]}
                    for _, r in pages[pages["ad_page_name"].isin(secilenler)].iterrows()]
            st.code(json.dumps(blok, ensure_ascii=False, indent=2), language="json")


with tabs[4]:
    def token_var() -> bool:
        if os.environ.get("FB_TOKEN", "").strip():
            return True
        env_path = os.path.join(HERE, ".env")
        if not os.path.exists(env_path):
            return False
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip().startswith("FB_TOKEN=") and line.split("=", 1)[1].strip():
                    return True
        return False

    if token_var():
        st.success("Token bulundu (.env veya ortam değişkeni).")
    else:
        st.error("FB_TOKEN yok. `.env.example` dosyasını `.env` olarak kopyalayıp token'ı yaz.")

    cfg_path = os.path.join(HERE, "config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    st.caption("Takip edilen sayfa: {} · anahtar kelime: {}".format(
        len(cfg.get("pages", [])), len(cfg.get("keywords", []))))

    gun = st.number_input("Sadece son kaç günü çek? (0 = hepsi)", 0, 2555, 0, step=30)
    b1, b2 = st.columns(2)
    args_base = [sys.executable, os.path.join(HERE, "collector.py")]
    if gun:
        args_base += ["--days", str(int(gun))]

    def run(cmd):
        with st.spinner("Çekiliyor… büyük sayfalarda birkaç dakika sürebilir."):
            proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
        st.code((proc.stdout or "") + (proc.stderr or ""), language="text")
        if proc.returncode == 0:
            load_ads.clear()
            load_runs.clear()
            st.success("Bitti. Sayfayı yenile.")
        else:
            st.error("Çekim hata verdi (çıkış kodu {}).".format(proc.returncode))

    if b1.button("Takip edilen sayfaları çek", type="primary",
                 disabled=not cfg.get("pages")):
        run(args_base)
    if b2.button("Kelimelerle sayfa keşfet", disabled=not cfg.get("keywords")):
        run(args_base + ["--discover"])

    st.subheader("Son çekimler")
    runs = load_runs(DB_PATH, stamp)
    if runs.empty:
        st.caption("Kayıt yok.")
    else:
        st.dataframe(runs.rename(columns={
            "started_at": "Başladı", "finished_at": "Bitti", "mode": "Tür",
            "query": "Sorgu", "fetched": "Reklam", "new_ads": "Yeni",
            "error": "Hata"}), use_container_width=True, hide_index=True)

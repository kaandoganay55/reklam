"""Panel grafikleri.

Renkler doğrulanmış kategorik paletten geliyor (light + dark ayrı seçilmiş
adımlar, otomatik ters çevirme değil). Kural özeti:
  - Kimlik (sayfa) -> kategorik slotlar, sabit sırayla, asla döngüsel değil.
  - Büyüklük (harcama, gösterim) -> tek hue mavi.
  - 8'den fazla sayfa -> kalanlar "Diğer" olarak nötr griye katlanır.
  - Tek seri -> lejant yok, başlık seriyi adlandırır; çubuklarda doğrudan etiket.
  - İki eksenli grafik yok: harcama ve gösterim ayrı grafiklerde.
"""
from __future__ import annotations

from typing import Dict, List

import altair as alt
import pandas as pd

CATEGORICAL: Dict[str, List[str]] = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500",
             "#d55181", "#008300", "#9085e9", "#e66767"],
}

TOKENS: Dict[str, Dict[str, str]] = {
    "light": {
        "surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e",
        "grid": "#e6e5e1", "other": "#8a8983", "sequential": "#2a78d6",
    },
    "dark": {
        "surface": "#1a1a19", "text": "#ffffff", "muted": "#c3c2b7",
        "grid": "#33332f", "other": "#7a7a74", "sequential": "#3987e5",
    },
}

MAX_SERIES = 8
OTHER_LABEL = "Diğer"


def fold_series(df: pd.DataFrame, key: str, weight: str,
                limit: int = MAX_SERIES) -> pd.DataFrame:
    """En büyük `limit` seriyi bırakır, kalanını 'Diğer'e katlar."""
    if df.empty or df[key].nunique() <= limit:
        return df
    top = (df.groupby(key)[weight].sum()
             .sort_values(ascending=False).head(limit).index)
    out = df.copy()
    out[key] = out[key].where(out[key].isin(top), OTHER_LABEL)
    return out


def color_scale(labels: List[str], theme: str) -> alt.Scale:
    """Sabit sıralı slot ataması; 'Diğer' her zaman nötr gri."""
    hues = CATEGORICAL[theme]
    named = [l for l in labels if l != OTHER_LABEL]
    domain = named + ([OTHER_LABEL] if OTHER_LABEL in labels else [])
    rng = [hues[i % len(hues)] for i in range(len(named))]
    if OTHER_LABEL in labels:
        rng.append(TOKENS[theme]["other"])
    return alt.Scale(domain=domain, range=rng)


def _style(chart: alt.Chart, theme: str, height) -> alt.Chart:
    """height: piksel (int) ya da bant başına adım (alt.Step) olabilir."""
    t = TOKENS[theme]
    return (
        chart.properties(height=height)
        .configure_view(strokeWidth=0, fill=t["surface"])
        .configure_axis(
            grid=True, gridColor=t["grid"], gridOpacity=0.7,
            domain=False, tickColor=t["grid"],
            labelColor=t["muted"], titleColor=t["muted"],
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
        )
        .configure_legend(
            labelColor=t["text"], titleColor=t["muted"],
            labelFontSize=11, titleFontSize=11, symbolType="stroke",
            symbolStrokeWidth=3, orient="top", direction="horizontal",
            columns=4, title=None,
        )
        .configure_title(color=t["text"], fontSize=13, anchor="start", dy=-6)
    )


def active_over_time(df: pd.DataFrame, theme: str, title: str) -> alt.Chart:
    """Günlük yayında olan reklam sayısı, sayfa bazında. Çok seri -> lejant + tooltip."""
    df = fold_series(df, "sayfa", "aktif")
    labels = (df.groupby("sayfa")["aktif"].sum()
                .sort_values(ascending=False).index.tolist())
    labels = [l for l in labels if l != OTHER_LABEL] + \
             ([OTHER_LABEL] if OTHER_LABEL in labels else [])

    hover = alt.selection_point(fields=["tarih"], nearest=True,
                                on="pointerover", empty=False)

    line = alt.Chart(df).mark_line(strokeWidth=2, interpolate="monotone").encode(
        x=alt.X("tarih:T", title=None),
        y=alt.Y("aktif:Q", title="Yayındaki reklam"),
        color=alt.Color("sayfa:N", scale=color_scale(labels, theme),
                        sort=labels, legend=alt.Legend(title=None)),
    )
    points = line.mark_point(size=90, filled=True, opacity=0).encode(
        tooltip=[alt.Tooltip("tarih:T", title="Tarih"),
                 alt.Tooltip("sayfa:N", title="Sayfa"),
                 alt.Tooltip("aktif:Q", title="Yayındaki reklam")],
    ).add_params(hover)
    marks = line.mark_point(size=70, filled=True,
                            stroke=TOKENS[theme]["surface"], strokeWidth=2).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
    )
    rule = alt.Chart(df).mark_rule(color=TOKENS[theme]["muted"],
                                   strokeWidth=1, opacity=0.4).encode(
        x="tarih:T",
    ).transform_filter(hover)

    return _style(alt.layer(rule, line, marks, points).properties(title=title), theme, 300)


def ranked_bar(df: pd.DataFrame, label_col: str, value_col: str, theme: str,
               title: str, value_title: str, fmt: str = ",.0f") -> alt.Chart:
    """Tek serili büyüklük sıralaması: tek hue, lejant yok, doğrudan etiket."""
    t = TOKENS[theme]
    order = df.sort_values(value_col, ascending=False)[label_col].tolist()

    bars = alt.Chart(df).mark_bar(
        cornerRadiusEnd=4, color=t["sequential"],
    ).encode(
        y=alt.Y(label_col + ":N", sort=order, title=None,
                scale=alt.Scale(paddingInner=0.28, paddingOuter=0.2),
                axis=alt.Axis(labelLimit=220)),
        x=alt.X(value_col + ":Q", title=value_title,
                axis=alt.Axis(format=fmt)),
        tooltip=[alt.Tooltip(label_col + ":N", title="Sayfa"),
                 alt.Tooltip(value_col + ":Q", title=value_title, format=fmt)],
    )
    labels = bars.mark_text(align="left", dx=6, color=t["text"], fontSize=11).encode(
        text=alt.Text(value_col + ":Q", format=fmt),
    )
    # Bant başına sabit adım: sayfa sayısı arttıkça grafik uzar, çubuklar ezilmez.
    return _style(alt.layer(bars, labels).properties(title=title), theme, alt.Step(34))


def status_bar(df: pd.DataFrame, theme: str, title: str) -> alt.Chart:
    """Sayfa başına yayında / bitmiş reklam. İki seri -> lejant + segment arası boşluk."""
    t = TOKENS[theme]
    order = (df.groupby("sayfa")["adet"].sum()
               .sort_values(ascending=False).index.tolist())
    durum_order = ["Yayında", "Bitmiş"]

    bars = alt.Chart(df).mark_bar(
        cornerRadiusEnd=4, stroke=t["surface"], strokeWidth=2,
    ).encode(
        y=alt.Y("sayfa:N", sort=order, title=None,
                scale=alt.Scale(paddingInner=0.28, paddingOuter=0.2),
                axis=alt.Axis(labelLimit=220)),
        x=alt.X("adet:Q", title="Reklam sayısı", stack=True),
        color=alt.Color("durum:N", sort=durum_order,
                        scale=color_scale(durum_order, theme),
                        legend=alt.Legend(title=None)),
        order=alt.Order("durum:N"),
        tooltip=[alt.Tooltip("sayfa:N", title="Sayfa"),
                 alt.Tooltip("durum:N", title="Durum"),
                 alt.Tooltip("adet:Q", title="Reklam")],
    )
    return _style(bars.properties(title=title), theme, alt.Step(34))


def volume_over_time(df: pd.DataFrame, theme: str, title: str) -> alt.Chart:
    """Haftalık yeni başlayan reklam sayısı. Tek seri -> lejant yok."""
    t = TOKENS[theme]
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, color=t["sequential"]).encode(
        x=alt.X("hafta:T", title=None),
        y=alt.Y("adet:Q", title="Yeni reklam"),
        tooltip=[alt.Tooltip("hafta:T", title="Hafta"),
                 alt.Tooltip("adet:Q", title="Yeni reklam")],
    )
    return _style(bars.properties(title=title), theme, 260)

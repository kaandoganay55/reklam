"""SQLite deposu: reklamlar, günlük geçmiş, sayfalar ve çekim kayıtları.

API sadece anlık durumu verir. Panelin asıl değeri ad_history tablosunda:
her çekimde reklamın harcama/gösterim aralığını o güne yazarız, böylece
"şu reklam ne zaman başladı, harcaması nasıl arttı, ne zaman durdu"
sorularını sonradan cevaplayabiliriz.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ads (
    ad_id            TEXT PRIMARY KEY,
    page_id          TEXT,
    page_name        TEXT,
    bylines          TEXT,
    ad_creation_time TEXT,
    delivery_start   TEXT,
    delivery_stop    TEXT,
    body             TEXT,
    link_title       TEXT,
    link_description TEXT,
    link_caption     TEXT,
    platforms        TEXT,
    languages        TEXT,
    currency         TEXT,
    spend_lower      REAL,
    spend_upper      REAL,
    impr_lower       REAL,
    impr_upper       REAL,
    audience_lower   REAL,
    audience_upper   REAL,
    demographics     TEXT,
    regions          TEXT,
    target_ages      TEXT,
    target_gender    TEXT,
    target_locations TEXT,
    snapshot_url     TEXT,
    is_active        INTEGER,
    first_seen       TEXT,
    last_seen        TEXT,
    raw              TEXT
);
CREATE INDEX IF NOT EXISTS idx_ads_page  ON ads(page_id);
CREATE INDEX IF NOT EXISTS idx_ads_start ON ads(delivery_start);

CREATE TABLE IF NOT EXISTS ad_history (
    ad_id       TEXT NOT NULL,
    seen_date   TEXT NOT NULL,
    spend_lower REAL,
    spend_upper REAL,
    impr_lower  REAL,
    impr_upper  REAL,
    is_active   INTEGER,
    PRIMARY KEY (ad_id, seen_date)
);

CREATE TABLE IF NOT EXISTS mentions (
    ad_id       TEXT NOT NULL,
    kisi        TEXT NOT NULL,
    ilk_gorulme TEXT,
    PRIMARY KEY (ad_id, kisi)
);
CREATE INDEX IF NOT EXISTS idx_mentions_kisi ON mentions(kisi);

CREATE TABLE IF NOT EXISTS pages (
    page_id    TEXT PRIMARY KEY,
    page_name  TEXT,
    label      TEXT,
    tracked    INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen  TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    mode        TEXT,
    query       TEXT,
    fetched     INTEGER DEFAULT 0,
    new_ads     INTEGER DEFAULT 0,
    error       TEXT
);
"""


def connect(path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounds(obj: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """spend/impressions aralık nesnesini (alt, üst) sayıya çevirir.

    Üst sınır bazen hiç gelmez ("100000+" gibi açık uçlu kovalar) -> None kalır.
    """
    if not isinstance(obj, dict):
        return None, None
    return _num(obj.get("lower_bound")), _num(obj.get("upper_bound"))


def _first(items: Any) -> Optional[str]:
    if isinstance(items, list) and items:
        return str(items[0])
    if isinstance(items, str):
        return items
    return None


def _joined(items: Any) -> Optional[str]:
    if isinstance(items, list):
        return ",".join(str(i) for i in items)
    if isinstance(items, str):
        return items
    return None


def _is_active(stop: Optional[str]) -> int:
    """Bitiş zamanı yoksa ya da gelecekteyse reklam hâlâ yayında sayılır."""
    if not stop:
        return 1
    try:
        stop_dt = datetime.fromisoformat(stop.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if stop_dt.tzinfo is None:
        stop_dt = stop_dt.replace(tzinfo=timezone.utc)
    return 1 if stop_dt > datetime.now(timezone.utc) else 0


def normalize(ad: Dict[str, Any]) -> Dict[str, Any]:
    """Ham API kaydını tablo satırına çevirir."""
    spend_lo, spend_hi = _bounds(ad.get("spend"))
    impr_lo, impr_hi = _bounds(ad.get("impressions"))
    aud_lo, aud_hi = _bounds(ad.get("estimated_audience_size"))
    stop = ad.get("ad_delivery_stop_time")

    return {
        "ad_id": ad["id"],
        "page_id": ad.get("page_id"),
        "page_name": ad.get("page_name"),
        "bylines": _joined(ad.get("bylines")),
        "ad_creation_time": ad.get("ad_creation_time"),
        "delivery_start": ad.get("ad_delivery_start_time"),
        "delivery_stop": stop,
        "body": _first(ad.get("ad_creative_bodies")),
        "link_title": _first(ad.get("ad_creative_link_titles")),
        "link_description": _first(ad.get("ad_creative_link_descriptions")),
        "link_caption": _first(ad.get("ad_creative_link_captions")),
        "platforms": _joined(ad.get("publisher_platforms")),
        "languages": _joined(ad.get("languages")),
        "currency": ad.get("currency"),
        "spend_lower": spend_lo,
        "spend_upper": spend_hi,
        "impr_lower": impr_lo,
        "impr_upper": impr_hi,
        "audience_lower": aud_lo,
        "audience_upper": aud_hi,
        "demographics": json.dumps(ad.get("demographic_distribution"), ensure_ascii=False)
        if ad.get("demographic_distribution") else None,
        "regions": json.dumps(ad.get("delivery_by_region"), ensure_ascii=False)
        if ad.get("delivery_by_region") else None,
        "target_ages": _joined(ad.get("target_ages")),
        "target_gender": ad.get("target_gender"),
        "target_locations": json.dumps(ad.get("target_locations"), ensure_ascii=False)
        if ad.get("target_locations") else None,
        "snapshot_url": ad.get("ad_snapshot_url"),
        "is_active": _is_active(stop),
        "raw": json.dumps(ad, ensure_ascii=False),
    }


_UPSERT_COLUMNS = [
    "page_id", "page_name", "bylines", "ad_creation_time", "delivery_start",
    "delivery_stop", "body", "link_title", "link_description", "link_caption",
    "platforms", "languages", "currency", "spend_lower", "spend_upper",
    "impr_lower", "impr_upper", "audience_lower", "audience_upper",
    "demographics", "regions", "target_ages", "target_gender",
    "target_locations", "snapshot_url", "is_active", "raw",
]


def upsert_ads(conn: sqlite3.Connection, ads: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    """Reklamları yazar. (toplam, yeni) döner. first_seen asla ezilmez."""
    now = _now()
    today = now[:10]
    total = 0
    new = 0

    insert_sql = (
        "INSERT INTO ads (ad_id, {cols}, first_seen, last_seen) "
        "VALUES (:ad_id, {binds}, :now, :now) "
        "ON CONFLICT(ad_id) DO UPDATE SET {updates}, last_seen = :now"
    ).format(
        cols=", ".join(_UPSERT_COLUMNS),
        binds=", ".join(":" + c for c in _UPSERT_COLUMNS),
        updates=", ".join("{0} = excluded.{0}".format(c) for c in _UPSERT_COLUMNS),
    )

    for ad in ads:
        row = normalize(ad)
        row["now"] = now
        existed = conn.execute(
            "SELECT 1 FROM ads WHERE ad_id = ?", (row["ad_id"],)
        ).fetchone() is not None
        conn.execute(insert_sql, row)
        if not existed:
            new += 1
        total += 1

        conn.execute(
            "INSERT INTO ad_history (ad_id, seen_date, spend_lower, spend_upper, "
            "impr_lower, impr_upper, is_active) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(ad_id, seen_date) DO UPDATE SET "
            "spend_lower = excluded.spend_lower, spend_upper = excluded.spend_upper, "
            "impr_lower = excluded.impr_lower, impr_upper = excluded.impr_upper, "
            "is_active = excluded.is_active",
            (row["ad_id"], today, row["spend_lower"], row["spend_upper"],
             row["impr_lower"], row["impr_upper"], row["is_active"]),
        )

        if row["page_id"]:
            conn.execute(
                "INSERT INTO pages (page_id, page_name, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(page_id) DO UPDATE SET "
                "page_name = excluded.page_name, last_seen = excluded.last_seen",
                (row["page_id"], row["page_name"], now, now),
            )

    conn.commit()
    return total, new


def record_mentions(conn: sqlite3.Connection, ad_ids: Iterable[str], kisi: str) -> int:
    """Bir kişi aramasında çıkan reklamları işaretler.

    Aynı reklam birden çok kişide çıkabilir (biri diğerinden bahsediyorsa),
    o yüzden ad_id + kisi birlikte anahtar.
    """
    now = _now()
    n = 0
    for ad_id in ad_ids:
        conn.execute(
            "INSERT INTO mentions (ad_id, kisi, ilk_gorulme) VALUES (?, ?, ?) "
            "ON CONFLICT(ad_id, kisi) DO NOTHING",
            (ad_id, kisi, now),
        )
        n += 1
    conn.commit()
    return n


def mark_tracked(conn: sqlite3.Connection, entries: Iterable[Dict[str, str]]) -> None:
    """config.json'daki takip listesini pages tablosuna yansıtır."""
    now = _now()
    conn.execute("UPDATE pages SET tracked = 0")
    for entry in entries:
        page_id = str(entry.get("page_id", "")).strip()
        if not page_id:
            continue
        conn.execute(
            "INSERT INTO pages (page_id, page_name, label, tracked, first_seen, last_seen) "
            "VALUES (?, ?, ?, 1, ?, ?) ON CONFLICT(page_id) DO UPDATE SET "
            "label = excluded.label, tracked = 1",
            (page_id, entry.get("label"), entry.get("label"), now, now),
        )
    conn.commit()


def start_run(conn: sqlite3.Connection, mode: str, query: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at, mode, query) VALUES (?, ?, ?)",
        (_now(), mode, query),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, fetched: int,
               new_ads: int, error: Optional[str] = None) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, fetched = ?, new_ads = ?, error = ? WHERE id = ?",
        (_now(), fetched, new_ads, error, run_id),
    )
    conn.commit()


def discovered_pages(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """Reklamı görülmüş tüm sayfalar, reklam sayısına göre sıralı."""
    return conn.execute(
        "SELECT p.page_id, COALESCE(p.label, p.page_name) AS ad_page_name, "
        "p.tracked, COUNT(a.ad_id) AS ad_count, "
        "SUM(a.is_active) AS active_count, MAX(a.delivery_start) AS last_ad "
        "FROM pages p LEFT JOIN ads a ON a.page_id = p.page_id "
        "GROUP BY p.page_id ORDER BY ad_count DESC"
    ).fetchall()

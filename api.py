"""Meta Ad Library API (ads_archive) istemcisi.

Türkiye için yalnızca POLITICAL_AND_ISSUE_ADS döner; ad_type=ALL sadece
AB/İngiltere'ye gösterilmiş reklamları kapsar.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence

import requests

GRAPH_VERSION = os.environ.get("FB_GRAPH_VERSION", "v23.0")
BASE_URL = "https://graph.facebook.com/{}/ads_archive".format(GRAPH_VERSION)

# TR'de dolu gelen alanlar. eu_total_reach ve age_country_gender_reach_breakdown
# yalnızca AB reklamlarında dolu olduğu için listeye alınmadı.
FIELDS: List[str] = [
    "id",
    "page_id",
    "page_name",
    "bylines",
    "ad_creation_time",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    "ad_creative_link_captions",
    "ad_snapshot_url",
    "publisher_platforms",
    "languages",
    "currency",
    "spend",
    "impressions",
    "estimated_audience_size",
    "demographic_distribution",
    "delivery_by_region",
    "target_ages",
    "target_gender",
    "target_locations",
]

# Throttling / geçici hata kodları -> bekle ve tekrar dene.
RETRY_CODES = {1, 2, 4, 17, 32, 341, 613}


class AdLibraryError(RuntimeError):
    """API'nin döndürdüğü hata; .code Graph API hata kodudur."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


def _token(explicit: Optional[str] = None) -> str:
    token = explicit or os.environ.get("FB_TOKEN", "").strip()
    if not token:
        raise AdLibraryError(
            "FB_TOKEN yok. .env dosyasına uzun ömürlü access token'ı koy "
            "veya export FB_TOKEN=... ile ver."
        )
    return token


def _request(url: str, params: Optional[Dict[str, Any]], max_retries: int = 5) -> Dict[str, Any]:
    delay = 30
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, timeout=90)
        try:
            body = resp.json()
        except ValueError:
            raise AdLibraryError("API JSON dönmedi (HTTP {}): {}".format(resp.status_code, resp.text[:300]))

        err = body.get("error")
        if not err:
            return body

        code = err.get("code")
        message = err.get("message", "")
        if code in RETRY_CODES and attempt < max_retries - 1:
            time.sleep(delay)
            delay = min(delay * 2, 600)
            continue
        if code == 190:
            raise AdLibraryError("Token geçersiz veya süresi dolmuş: {}".format(message), code)
        raise AdLibraryError("API hatası ({}): {}".format(code, message), code)

    raise AdLibraryError("Rate limit aşıldı, {} denemeden sonra vazgeçildi.".format(max_retries))


def fetch_ads(
    page_ids: Optional[Sequence[str]] = None,
    search_terms: Optional[str] = None,
    countries: Sequence[str] = ("TR",),
    active_status: str = "ALL",
    date_min: Optional[str] = None,
    date_max: Optional[str] = None,
    platforms: Optional[Sequence[str]] = None,
    media_type: Optional[str] = None,
    search_type: str = "KEYWORD_UNORDERED",
    limit: int = 250,
    max_pages: int = 200,
    token: Optional[str] = None,
    pause: float = 1.0,
) -> Iterator[Dict[str, Any]]:
    """ads_archive'ı sayfalayarak dolaşır, reklamları tek tek verir.

    page_ids veya search_terms'ten en az biri zorunlu. search_page_ids tek
    çağrıda en fazla 10 sayfa kabul ettiği için çağıran tarafın gruplaması gerekir.
    """
    if not page_ids and not search_terms:
        raise ValueError("page_ids veya search_terms verilmeli.")
    if page_ids and len(page_ids) > 10:
        raise ValueError("search_page_ids tek çağrıda en fazla 10 sayfa alır.")

    params: Dict[str, Any] = {
        "access_token": _token(token),
        "ad_reached_countries": json.dumps(list(countries)),
        "ad_type": "POLITICAL_AND_ISSUE_ADS",
        "ad_active_status": active_status,
        "fields": ",".join(FIELDS),
        "limit": limit,
    }
    if page_ids:
        params["search_page_ids"] = json.dumps([str(p) for p in page_ids])
    if search_terms:
        params["search_terms"] = search_terms
        # İsim ararken KEYWORD_EXACT_PHRASE şart: aksi halde "Halit Doğan"
        # sorgusu "halit" veya "doğan" geçen her reklamı getirir.
        params["search_type"] = search_type
    if date_min:
        params["ad_delivery_date_min"] = date_min
    if date_max:
        params["ad_delivery_date_max"] = date_max
    if platforms:
        params["publisher_platforms"] = json.dumps(list(platforms))
    if media_type:
        params["media_type"] = media_type

    url: str = BASE_URL
    for _ in range(max_pages):
        body = _request(url, params)
        for ad in body.get("data", []):
            yield ad

        nxt = (body.get("paging") or {}).get("next")
        if not nxt:
            return
        # next URL token'ı ve cursor'ı zaten taşıyor.
        url, params = nxt, None
        if pause:
            time.sleep(pause)


def fetch_ads_for_pages(page_ids: Sequence[str], **kwargs: Any) -> Iterator[Dict[str, Any]]:
    """10'ar 10'ar gruplayıp tüm sayfaların reklamlarını dolaşır."""
    ids = [str(p) for p in page_ids]
    for i in range(0, len(ids), 10):
        for ad in fetch_ads(page_ids=ids[i:i + 10], **kwargs):
            yield ad

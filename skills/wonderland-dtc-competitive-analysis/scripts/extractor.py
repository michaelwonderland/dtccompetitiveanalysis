"""
Extractor: given a discovered review URL template, fetch all reviews for a
list of products by calling the API directly with httpx (fast path).

Falls back to per-product Playwright re-discovery if direct calls fail.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse, urljoin

import httpx

from .models import Review
from .crawler import product_handle, USER_AGENT


# ---------- Field normalization ----------

def _get(d: dict, *keys: str, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
        # case-insensitive
        for actual_k, v in d.items():
            if actual_k.lower() == k.lower() and v not in (None, ""):
                return v
    return default


def _author_from(d: dict) -> Optional[str]:
    user = _get(d, "user", "reviewer", "author")
    if isinstance(user, dict):
        return _get(user, "displayName", "display_name", "name", "userName", "user_name", "fullName")
    if isinstance(user, str):
        return user
    return _get(d, "name", "author_name", "user_name", "displayName", "reviewer_name", "author")


def _rating_from(d: dict) -> Optional[float]:
    val = _get(d, "score", "rating", "stars", "starRating", "review_score", "ratingValue")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _verified_from(raw: dict) -> Optional[bool]:
    # Top-level (Yotpo: verifiedBuyer)
    v = _get(raw, "verifiedBuyer", "verified_buyer", "verified", "isVerifiedBuyer", "verifiedPurchase")
    if v is not None:
        return bool(v)
    # Nested under reviewer/user (Okendo: reviewer.isVerified)
    container = _get(raw, "reviewer", "user", "author")
    if isinstance(container, dict):
        v = _get(container, "isVerified", "verified", "verifiedBuyer", "verified_buyer")
        if v is not None:
            return bool(v)
    return None


def normalize_review(raw: dict, product_url: str) -> Review:
    return Review(
        product_url=product_url,
        product_handle=product_handle(product_url),
        review_id=str(_get(raw, "id", "review_id", "reviewId", "uuid") or "") or None,
        author=_author_from(raw),
        rating=_rating_from(raw),
        title=_get(raw, "title", "headline", "subject", "review_title"),
        body=_get(raw, "content", "body", "text", "review", "reviewBody", "comment", "review_text"),
        created_at=_get(raw, "createdAt", "created_at", "date", "submitted_at", "dateCreated"),
        verified=_verified_from(raw),
        helpful_count=_get(raw, "votesUp", "votes_up", "helpful_count", "helpfulCount", "upvotes"),
        raw=raw,
    )


# ---------- Pagination ----------

def _set_query_param(url: str, key: str, value: Any) -> str:
    """Set/replace a single query param without collapsing duplicates of others."""
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != key]
    pairs.append((key, str(value)))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


FILTER_KEYS = {"orderby", "order_by", "sort_by", "filter", "where"}


def _strip_filter_params(url: str) -> str:
    """Remove sort/filter params that narrow the review set.

    Many widgets request a filtered/highlighted subset on first load (e.g.
    Okendo's `orderBy=tag:UEADRRY desc` returns only tagged reviews). When
    scraping for the full review set, drop these.
    """
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    cleaned = []
    for k, v in pairs:
        kl = k.lower()
        # Drop tag-style filters embedded in sort params
        if kl in FILTER_KEYS and ":" in v:
            continue
        cleaned.append((k, v))
    return urlunparse(parsed._replace(query=urlencode(cleaned)))


def _drill_to_reviews(obj: Any) -> list:
    """Find the list of review-like dicts inside a JSON response.
    We mirror discovery._looks_like_review_array but actually return the list.
    """
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = {k.lower() for k in obj[0].keys()}
        review_indicators = {"rating", "score", "stars", "body", "content",
                             "review", "title", "author", "created_at", "createdat", "user"}
        if len(keys & review_indicators) >= 2:
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _drill_to_reviews(v)
            if result:
                return result
    return []


NEXT_URL_KEYS = ("nextUrl", "next_url", "nextPageUrl", "next_page_url", "nextPage")
NEXT_CONTAINER_KEYS = ("pagination", "paging", "links", "_links", "meta", "pageInfo", "page_info")


def _resolve_relative(rel: str, current_url: str) -> str:
    """Resolve a relative URL against the current URL.

    Standard urljoin works for most cases, but some APIs (e.g. Okendo) return
    a path-absolute next URL that omits an API-version prefix that's present
    in the current URL. Detect that and prepend the missing prefix.
    """
    if not rel.startswith("/"):
        return urljoin(current_url, rel)

    cur = urlparse(current_url)
    rp = urlparse(rel)
    cur_segs = cur.path.strip("/").split("/")
    rel_segs = rp.path.strip("/").split("/")

    if rel_segs and rel_segs[0] in cur_segs:
        idx = cur_segs.index(rel_segs[0])
        if idx > 0:
            prefix = "/" + "/".join(cur_segs[:idx])
            return f"{cur.scheme}://{cur.netloc}{prefix}{rel}"

    return urljoin(current_url, rel)


def _find_next_url(data: Any, current_url: str) -> Optional[str]:
    """Look for a 'next page URL' field in a paginated JSON response.

    Handles:
      - Top-level: {"nextUrl": "...", "reviews": [...]}    (Okendo)
      - Nested:    {"pagination": {"next": "..."}}          (many REST APIs)
      - HAL-style: {"_links": {"next": {"href": "..."}}}
    Returns an absolute URL or None.
    """
    if not isinstance(data, dict):
        return None

    def _abs(u: str) -> Optional[str]:
        if not u or not isinstance(u, str):
            return None
        return _resolve_relative(u, current_url)

    for k in NEXT_URL_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v:
            return _abs(v)

    for container_key in NEXT_CONTAINER_KEYS:
        c = data.get(container_key)
        if isinstance(c, dict):
            for k in ("next", *NEXT_URL_KEYS):
                v = c.get(k)
                if isinstance(v, str) and v:
                    return _abs(v)
                if isinstance(v, dict) and isinstance(v.get("href"), str):
                    return _abs(v["href"])
    return None


def _drill_total_count(obj: Any) -> Optional[int]:
    """Find a 'total reviews' integer in the JSON, if any."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in ("total", "totalreviews", "total_review", "total_count", "count"):
                if isinstance(v, int):
                    return v
                if isinstance(v, str) and v.isdigit():
                    return int(v)
            if isinstance(v, (dict, list)):
                t = _drill_total_count(v)
                if t is not None:
                    return t
    elif isinstance(obj, list):
        for item in obj:
            t = _drill_total_count(item)
            if t is not None:
                return t
    return None


# ---------- Product id resolver (delegates to platforms/) ----------

def resolve_product_id(client: httpx.Client, product_url: str,
                       platform: Optional[str] = None) -> Optional[str]:
    """Resolve a product page URL to its internal product ID.

    Delegates to platform-specific adapters in eca.platforms (Shopify first,
    generic HTML/JSON-LD fallback after). Pass `platform="shopify"` to skip
    the auto-detection.
    """
    from .platforms import resolve_product_id as _resolve
    pid, _name = _resolve(client, product_url, platform=platform)
    return pid


# Backwards-compatible alias for callers that explicitly want Shopify only.
def shopify_product_id(client: httpx.Client, product_url: str) -> Optional[str]:
    return resolve_product_id(client, product_url, platform="shopify")


# ---------- Main extraction ----------

class Extractor:
    def __init__(self, config: dict):
        """config is a discovery-result dict with review_url_template, etc."""
        self.config = config
        self.template: str = _strip_filter_params(config["review_url_template"])
        self.pagination_param: Optional[str] = config.get("pagination_param") or "page"
        self.size_param: Optional[str] = config.get("page_size_param")
        self.preferred_page_size = 100
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,*/*;q=0.8",
        }
        # Pull request hints from discovery
        for k, v in (config.get("request_headers") or {}).items():
            if k.lower() in ("accept", "referer", "origin", "x-requested-with", "accept-language"):
                self.headers[k] = v

    def _build_url(self, product_id: str, page: int) -> str:
        url = self.template.replace("{product_id}", product_id)
        url = _set_query_param(url, self.pagination_param, page)
        if self.size_param:
            url = _set_query_param(url, self.size_param, self.preferred_page_size)
        return url

    def fetch_reviews(self, client: httpx.Client, product_url: str, product_id: str,
                      max_pages: int = 500, sleep_s: float = 0.4) -> tuple[list[Review], dict]:
        reviews: list[Review] = []
        seen_ids: set[str] = set()
        meta = {"pages_fetched": 0, "total_reported": None, "stopped_reason": None,
                "pagination_mode": None}
        headers = dict(self.headers)
        headers.setdefault("Referer", product_url)

        # First request: build from template + page=1 (or whatever the template starts at)
        next_url: Optional[str] = self._build_url(product_id, 1)
        page_idx = 1

        for _ in range(max_pages):
            url = next_url
            try:
                r = client.get(url, headers=headers, timeout=30.0)
            except httpx.HTTPError as e:
                meta["stopped_reason"] = f"http_error:{e}"
                break
            if r.status_code != 200:
                meta["stopped_reason"] = f"status:{r.status_code}"
                break
            try:
                data = r.json()
            except Exception:
                meta["stopped_reason"] = "non_json_response"
                break

            page_idx_now = page_idx
            meta["pages_fetched"] = page_idx_now
            if meta["total_reported"] is None:
                meta["total_reported"] = _drill_total_count(data)

            page_reviews = _drill_to_reviews(data)
            if not page_reviews:
                meta["stopped_reason"] = "no_more_reviews"
                break

            new_count = 0
            for raw in page_reviews:
                rid = str(raw.get("id") or raw.get("review_id") or raw.get("reviewId") or "")
                if rid and rid in seen_ids:
                    continue
                if rid:
                    seen_ids.add(rid)
                reviews.append(normalize_review(raw, product_url))
                new_count += 1

            # Determine next page URL.
            api_next = _find_next_url(data, url)
            if api_next:
                # Provider gave us a next-URL (Okendo nextUrl, HAL _links.next, etc.).
                # Trust it — keep paginating regardless of total_reported (which
                # may reflect a filtered subset rather than the true total).
                if meta["pagination_mode"] is None:
                    meta["pagination_mode"] = "next-url"
                if api_next == url:
                    meta["stopped_reason"] = "next_url_loop"
                    break
                next_url = api_next
                page_idx += 1
            else:
                if meta["pagination_mode"] == "next-url":
                    # Cursor pagination ended cleanly.
                    meta["stopped_reason"] = "no_next_url"
                    break
                meta["pagination_mode"] = "incremental"
                if new_count == 0:
                    meta["stopped_reason"] = "all_duplicates"
                    break
                if len(page_reviews) < self.preferred_page_size and self.size_param:
                    meta["stopped_reason"] = "short_page"
                    break
                if meta["total_reported"] and len(reviews) >= meta["total_reported"]:
                    meta["stopped_reason"] = "reached_total"
                    break
                page_idx += 1
                next_url = self._build_url(product_id, page_idx)

            time.sleep(sleep_s)
        else:
            meta["stopped_reason"] = "max_pages"

        return reviews, meta


def _scan_count_from_response(data: Any) -> tuple[Optional[int], Optional[float]]:
    """Pull (count, avg_rating) out of a first-page response without paginating.

    Yotpo: bottomline.totalReview / bottomline.averageScore
    Okendo: total (count); avg from rating mean of the page
    Generic: pagination.total / total
    """
    if not isinstance(data, dict):
        return None, None
    # Yotpo bottomline
    bl = data.get("bottomline")
    if isinstance(bl, dict):
        n = bl.get("totalReview") or bl.get("total_review") or bl.get("total")
        avg = bl.get("averageScore") or bl.get("average_score")
        if isinstance(n, int):
            return n, float(avg) if avg is not None else None
    # Direct total field
    n = _drill_total_count(data)
    if n is not None:
        # Compute avg from page reviews if possible
        page = _drill_to_reviews(data)
        ratings = []
        for r in page:
            rv = _rating_from(r)
            if rv is not None:
                ratings.append(rv)
        avg = sum(ratings) / len(ratings) if ratings else None
        return n, avg
    return None, None


class Scanner:
    """Cheap one-page-per-product scanner, returns count + avg without paginating."""

    def __init__(self, extractor: Extractor):
        self.ext = extractor

    def scan(self, client: httpx.Client, product_url: str, product_id: str,
             max_pages: int = 20) -> tuple[Optional[int], Optional[float]]:
        """Return (count, avg_rating) for ranking purposes.

        Tries explicit total fields first (Yotpo bottomline, JSON total).
        If absent, follows the next-URL cursor up to max_pages and returns
        a count (exact if cursor exhausts; lower-bound capped at max_pages*page_size if not).
        """
        url = self.ext._build_url(product_id, 1)
        if self.ext.size_param:
            url = _set_query_param(url, self.ext.size_param, 100)
        headers = dict(self.ext.headers)
        headers.setdefault("Referer", product_url)

        all_ratings: list[float] = []
        total_seen = 0
        pages = 0
        next_url = url

        while next_url and pages < max_pages:
            try:
                r = client.get(next_url, headers=headers, timeout=15.0)
            except httpx.HTTPError:
                break
            if r.status_code != 200:
                break
            try:
                data = r.json()
            except Exception:
                break
            pages += 1

            # On the first page, look for an explicit total (Yotpo bottomline, etc.)
            if pages == 1:
                n, avg = _scan_count_from_response(data)
                if n is not None:
                    return n, avg

            page = _drill_to_reviews(data)
            if not page:
                break
            total_seen += len(page)
            for raw in page:
                rv = _rating_from(raw)
                if rv is not None:
                    all_ratings.append(rv)

            nxt = _find_next_url(data, next_url)
            if not nxt or nxt == next_url:
                # cursor exhausted - exact count
                avg = sum(all_ratings) / len(all_ratings) if all_ratings else None
                return total_seen, avg
            next_url = nxt

        avg = sum(all_ratings) / len(all_ratings) if all_ratings else None
        return total_seen, avg


def make_http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
        http2=False,
    )

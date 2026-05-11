"""
Discovery: load a product page in Playwright, intercept network traffic,
and identify the review-data endpoint heuristically.

The agent is provider-agnostic - we don't hardcode Yotpo/Judge.me/Okendo/etc.
We just look for JSON responses that LOOK like review data.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


PROVIDER_HINTS = re.compile(
    r"(yotpo|judge\.?me|stamped|okendo|loox|junip|fera|reviews\.io|bazaarvoice|"
    r"powerreviews|trustpilot|kudobuzz|opinew|growave|ryviu|reviewbit|vitals|"
    r"shopperapproved|reziew|alireview|reviews?-?api|/reviews?(/|\?|$)|"
    r"/ratings?(/|\?|$)|/ugc/|review[-_]?widget|review[-_]?summary)",
    re.IGNORECASE,
)

# JSON keys that strongly indicate review data
REVIEW_KEYS = {
    "rating", "score", "stars", "starRating", "review_score",
    "body", "content", "text", "review", "reviewBody", "comment",
    "author", "reviewer", "name", "user_name", "displayName",
    "title", "headline", "subject",
    "created_at", "createdAt", "date", "dateCreated", "submitted_at",
    "verified", "verifiedBuyer", "verified_buyer",
}


@dataclass
class CandidateResponse:
    url: str
    method: str
    status: int
    content_type: str
    body_preview: str  # first 1KB for logging
    parsed: Any = None  # parsed JSON
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    request_headers: dict = field(default_factory=dict)


def _looks_like_review_array(obj: Any, depth: int = 0) -> tuple[bool, int, str]:
    """Return (is_review_array, item_count, path_description) if obj is or
    contains a list of review-like objects.
    """
    if depth > 5:
        return False, 0, ""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        keys = set(obj[0].keys())
        # Lowercase compare
        keys_lower = {k.lower() for k in keys}
        review_keys_lower = {k.lower() for k in REVIEW_KEYS}
        overlap = len(keys_lower & review_keys_lower)
        if overlap >= 2:
            return True, len(obj), f"list[{len(obj)}]"
    if isinstance(obj, dict):
        for k, v in obj.items():
            ok, n, path = _looks_like_review_array(v, depth + 1)
            if ok:
                return True, n, f"{k}.{path}" if path else k
    return False, 0, ""


def score_candidate(c: CandidateResponse) -> None:
    score = 0
    reasons = []

    # URL-based hints
    if PROVIDER_HINTS.search(c.url):
        score += 30
        reasons.append("url-hint")

    # Content type
    if "json" in c.content_type.lower():
        score += 5
    else:
        score -= 5  # less likely to be a clean API

    # Status
    if c.status == 200:
        score += 2

    # Body shape
    if c.parsed is not None:
        ok, n_items, path = _looks_like_review_array(c.parsed)
        if ok:
            score += 50
            reasons.append(f"review-shape:{path}({n_items} items)")
        # bonus for explicit review-related top-level keys
        if isinstance(c.parsed, dict):
            top_keys = {k.lower() for k in c.parsed.keys()}
            if "reviews" in top_keys or "results" in top_keys or "items" in top_keys:
                score += 10
                reasons.append("review-key-at-top")
            if "pagination" in top_keys or "total" in top_keys or "page" in top_keys:
                score += 5
                reasons.append("paginated")

    c.score = score
    c.reasons = reasons


def _identify_product_id(url: str, body: Any) -> Optional[str]:
    """Try to extract a product id from the request URL or response body.

    We look in path segments and query params for things that look like ids:
    /products/12345/reviews, ?productId=12345, ?product_id=12345
    """
    parsed = urlparse(url)

    # Path: look for digit-only or sku-like segments
    path_parts = [p for p in parsed.path.split("/") if p]
    for i, p in enumerate(path_parts):
        if p in ("products", "product") and i + 1 < len(path_parts):
            cand = path_parts[i + 1]
            if cand.isdigit() or re.match(r"^[a-zA-Z0-9_-]{6,}$", cand):
                return cand

    # Query params
    qs = parse_qs(parsed.query)
    for key in ("productId", "product_id", "pid", "productID", "sku"):
        if key in qs:
            return qs[key][0]

    return None


@dataclass
class DiscoveryResult:
    found: bool
    review_url: Optional[str] = None
    review_url_template: Optional[str] = None  # with {product_id} placeholder
    product_id: Optional[str] = None
    product_id_param: Optional[str] = None  # name of the query/path param
    pagination_param: Optional[str] = None  # 'page', 'p', 'offset', 'after', etc.
    page_size_param: Optional[str] = None  # 'per_page', 'limit', 'take'
    page_size: Optional[int] = None
    candidate_count: int = 0
    top_candidates: list[dict] = field(default_factory=list)
    request_headers: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


COMMON_PAGE_PARAMS = ["page", "p", "pageNumber", "page_number", "pageNum"]
COMMON_OFFSET_PARAMS = ["offset", "from", "skip", "start"]
COMMON_CURSOR_PARAMS = ["cursor", "after", "afterCursor", "next", "nextToken"]
COMMON_SIZE_PARAMS = ["per_page", "perPage", "limit", "take", "count", "pageSize", "page_size"]


def _identify_pagination(url: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """Inspect the URL and return (page_param, offset_param, size_param, size_value).
    Only one of page_param/offset_param will be non-None.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    page_param = next((p for p in COMMON_PAGE_PARAMS if p in qs), None)
    offset_param = next((p for p in COMMON_OFFSET_PARAMS if p in qs), None)
    cursor_param = next((p for p in COMMON_CURSOR_PARAMS if p in qs), None)
    size_param = next((p for p in COMMON_SIZE_PARAMS if p in qs), None)
    size_value = None
    if size_param and qs.get(size_param):
        try:
            size_value = int(qs[size_param][0])
        except ValueError:
            size_value = None
    return page_param or cursor_param, offset_param, size_param, size_value


def discover(product_url: str, *, headless: bool = True, timeout_ms: int = 30000) -> DiscoveryResult:
    """Open product_url in Playwright, intercept network traffic, return the
    most likely review-data endpoint.
    """
    candidates: list[CandidateResponse] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                # Only inspect text-ish responses
                if "json" not in ct.lower() and "javascript" not in ct.lower() and "text" not in ct.lower():
                    return
                # Skip large responses
                try:
                    body_bytes = resp.body()
                except Exception:
                    return
                if len(body_bytes) > 2_000_000:
                    return
                try:
                    text = body_bytes.decode("utf-8", errors="replace")
                except Exception:
                    return
                parsed = None
                if "json" in ct.lower():
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        # Some review widgets return JSONP (callback({...}))
                        m = re.match(r"\s*[A-Za-z_$][\w$]*\s*\((.*)\)\s*;?\s*$", text, re.DOTALL)
                        if m:
                            try:
                                parsed = json.loads(m.group(1))
                            except Exception:
                                parsed = None
                else:
                    # Try to find JSON inside script-like text
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = None

                req = resp.request
                cand = CandidateResponse(
                    url=resp.url,
                    method=req.method,
                    status=resp.status,
                    content_type=ct,
                    body_preview=text[:1024],
                    parsed=parsed,
                    request_headers=dict(req.headers),
                )
                score_candidate(cand)
                if cand.score > 0:
                    candidates.append(cand)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PWTimeoutError:
            pass

        # Trigger lazy-loading content
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeoutError:
            pass

        # Scroll to bottom to trigger any lazy review widgets
        try:
            page.evaluate("""
                async () => {
                    await new Promise(resolve => {
                        let total = 0;
                        const distance = 400;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            total += distance;
                            if (total >= document.body.scrollHeight) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 200);
                    });
                }
            """)
        except Exception:
            pass

        # Try to click any element that mentions reviews to expand them
        for selector in [
            "text=/reviews?/i",
            "a[href*='#reviews']",
            "button:has-text('Reviews')",
            "button:has-text('See all')",
            "button:has-text('Load more')",
            "button:has-text('Show more')",
        ]:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=500):
                    el.click(timeout=2000)
                    page.wait_for_timeout(1500)
            except Exception:
                pass

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeoutError:
            pass

        # Final scroll pass to trigger load-more on infinite scroll
        try:
            for _ in range(5):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(400)
        except Exception:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PWTimeoutError:
            pass

        browser.close()

    if not candidates:
        return DiscoveryResult(found=False, candidate_count=0, notes=["No JSON candidates captured"])

    candidates.sort(key=lambda c: c.score, reverse=True)
    top = candidates[0]
    if top.score < 30:
        return DiscoveryResult(
            found=False,
            candidate_count=len(candidates),
            top_candidates=[
                {"url": c.url, "score": c.score, "reasons": c.reasons}
                for c in candidates[:5]
            ],
            notes=[f"Top score {top.score} below threshold (30)"],
        )

    product_id = _identify_product_id(top.url, top.parsed)
    page_param, offset_param, size_param, size_value = _identify_pagination(top.url)

    # Build a URL template by replacing the product_id with {product_id}
    url_template = top.url
    if product_id:
        url_template = url_template.replace(product_id, "{product_id}")

    return DiscoveryResult(
        found=True,
        review_url=top.url,
        review_url_template=url_template,
        product_id=product_id,
        pagination_param=page_param or offset_param,
        page_size_param=size_param,
        page_size=size_value,
        candidate_count=len(candidates),
        top_candidates=[
            {"url": c.url, "score": c.score, "reasons": c.reasons}
            for c in candidates[:5]
        ],
        request_headers={k: v for k, v in top.request_headers.items()
                         if k.lower() in ("accept", "accept-language", "referer", "origin", "x-requested-with")},
        notes=[],
    )

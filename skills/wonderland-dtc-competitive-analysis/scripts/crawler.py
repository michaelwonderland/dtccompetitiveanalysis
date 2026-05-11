from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"}


def _normalize_base(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch(client: httpx.Client, url: str) -> Optional[str]:
    try:
        r = client.get(url, timeout=20.0, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except httpx.HTTPError:
        return None
    return None


from typing import Optional


def _extract_locs(xml_text: str) -> list[str]:
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text)
    return [loc.strip() for loc in locs]


def crawl_products(site_url: str, max_products: Optional[int] = None) -> list[str]:
    """Return a list of absolute product page URLs for the given site.

    Strategy:
      1. Try /sitemap.xml (and any nested product sitemaps).
      2. If no sitemap, fall back to scraping /collections/all and the homepage
         for /products/ links.
    """
    base = _normalize_base(site_url)
    found: list[str] = []
    seen: set[str] = set()

    with httpx.Client(headers=DEFAULT_HEADERS, timeout=20.0, follow_redirects=True) as client:
        # 1. Sitemap path
        sitemap_url = base + "/sitemap.xml"
        xml = _fetch(client, sitemap_url)
        if xml:
            queue = [sitemap_url]
            visited_sitemaps: set[str] = set()
            while queue:
                sm = queue.pop(0)
                if sm in visited_sitemaps:
                    continue
                visited_sitemaps.add(sm)
                body = _fetch(client, sm)
                if not body:
                    continue
                locs = _extract_locs(body)
                for loc in locs:
                    if loc.endswith(".xml") or "/sitemap" in loc:
                        # nested sitemap
                        if "products" in loc.lower() or "sitemap" in loc.lower():
                            queue.append(loc)
                    elif "/products/" in loc and not loc.endswith(".jpg") and not loc.endswith(".png"):
                        if loc not in seen:
                            seen.add(loc)
                            found.append(loc)
                            if max_products and len(found) >= max_products:
                                return found

        if found:
            return found

        # 2. Fallback: scrape /collections/all and home for product links
        for path in ("/collections/all", "/products", "/"):
            html = _fetch(client, base + path)
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for a in soup.select("a[href]"):
                href = a.get("href") or ""
                if "/products/" in href:
                    abs_url = urljoin(base, href.split("?")[0].split("#")[0])
                    if abs_url not in seen:
                        seen.add(abs_url)
                        found.append(abs_url)
                        if max_products and len(found) >= max_products:
                            return found

    return found


def product_handle(url: str) -> str:
    """Extract the product slug/handle from a /products/{handle} URL."""
    m = re.search(r"/products/([^/?#]+)", url)
    if m:
        return m.group(1)
    # Fallback: last path segment
    return urlparse(url).path.rstrip("/").split("/")[-1] or "product"

"""
Shopify product-id resolver.

Shopify exposes /products/{handle}.js for every storefront product. The
response includes the numeric `id` we need to pass to review widgets like
Yotpo, Judge.me, and Okendo.
"""
from __future__ import annotations

import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse

import httpx


_HANDLE_RE = re.compile(r"/products/([^/?#]+)")


def _product_handle(url: str) -> Optional[str]:
    m = _HANDLE_RE.search(url)
    return m.group(1) if m else None


def resolve(client: httpx.Client, product_url: str,
            retries: int = 3, sleep_s: float = 0.5) -> Optional[str]:
    """Fetch /products/{handle}.js and return the numeric product id, or None.

    Retries transient errors instead of silently swallowing them — the original
    one-shot version caused catalogue scans to return product_id=None during a
    network blip, which then made downstream review-API calls (Yotpo etc.) look
    like "no reviews" for those products.
    """
    handle = _product_handle(product_url)
    if not handle:
        return None
    parsed = urlparse(product_url)
    js_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.js"
    last_err: Optional[str] = None
    for attempt in range(retries):
        try:
            r = client.get(js_url, timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                pid = data.get("id") or data.get("product_id")
                if pid:
                    return str(pid)
                last_err = f"200 OK but no id in response: {list(data)[:5]}"
            else:
                last_err = f"HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt + 1 < retries:
            time.sleep(sleep_s * (attempt + 1))
    print(
        f"[shopify.resolve] FAILED for {js_url} after {retries} attempts: {last_err}",
        file=sys.stderr,
    )
    return None

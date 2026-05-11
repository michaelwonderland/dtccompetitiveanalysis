"""
Shopify product-id resolver.

Shopify exposes /products/{handle}.js for every storefront product. The
response includes the numeric `id` we need to pass to review widgets like
Yotpo, Judge.me, and Okendo.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import httpx


_HANDLE_RE = re.compile(r"/products/([^/?#]+)")


def _product_handle(url: str) -> Optional[str]:
    m = _HANDLE_RE.search(url)
    return m.group(1) if m else None


def resolve(client: httpx.Client, product_url: str) -> Optional[str]:
    """Fetch /products/{handle}.js and return the numeric product id, or None."""
    handle = _product_handle(product_url)
    if not handle:
        return None
    parsed = urlparse(product_url)
    js_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.js"
    try:
        r = client.get(js_url, timeout=15.0)
        if r.status_code == 200:
            data = r.json()
            pid = data.get("id") or data.get("product_id")
            if pid:
                return str(pid)
    except (httpx.HTTPError, ValueError):
        return None
    return None

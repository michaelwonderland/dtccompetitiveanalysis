"""
Generic product-id resolver fallback.

Tries to extract a product id from common HTML patterns when no platform-specific
adapter matches. Looks for:

  - JSON-LD <script type="application/ld+json"> with @type Product and a sku/productID
  - <meta property="product:retailer_item_id" content="...">
  - data-product-id="..." attributes
  - The last URL segment before /products/

This is best-effort. For a new platform, prefer adding a dedicated adapter in
`eca/platforms/<name>.py` and registering it in `__init__.py`.
"""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


def _product_handle(url: str) -> Optional[str]:
    m = re.search(r"/products?/([^/?#]+)", url)
    return m.group(1) if m else None


def resolve(client: httpx.Client, product_url: str) -> Optional[str]:
    try:
        r = client.get(product_url, timeout=15.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    html = r.text
    soup = BeautifulSoup(html, "lxml")

    # 1. JSON-LD with Product schema
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            blob = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        for obj in blob if isinstance(blob, list) else [blob]:
            if not isinstance(obj, dict):
                continue
            t = obj.get("@type", "")
            if (isinstance(t, str) and "Product" in t) or (isinstance(t, list) and any("Product" in x for x in t)):
                for k in ("productID", "sku", "mpn", "@id"):
                    v = obj.get(k)
                    if isinstance(v, (int, str)) and str(v).strip():
                        return str(v).strip()

    # 2. meta tags
    for prop in ("product:retailer_item_id", "og:product:retailer_item_id", "product:sku"):
        m = soup.find("meta", attrs={"property": prop})
        if m and m.get("content"):
            return str(m["content"]).strip()

    # 3. data-product-id attributes
    for attr in ("data-product-id", "data-productid", "data-product"):
        el = soup.find(attrs={attr: True})
        if el:
            v = el.get(attr)
            if v and str(v).strip():
                return str(v).strip()

    # 4. Fallback: handle from URL (some review APIs accept the slug)
    return _product_handle(product_url)

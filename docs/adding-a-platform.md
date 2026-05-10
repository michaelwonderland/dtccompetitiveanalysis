# Adding a platform adapter

The toolkit's crawler, discovery, and extraction logic is platform-agnostic. The one place it needs platform-specific knowledge is **per-product ID resolution** — given a product page URL like `https://shop.example.com/products/foo`, return the internal numeric/slug ID that the review-widget API expects.

For Shopify this is trivial (`/products/{handle}.js`). For other platforms it requires a small adapter.

## Where adapters live

`eca/platforms/` — one module per platform, each exposing a single function:

```python
def resolve(client: httpx.Client, product_url: str) -> Optional[str]:
    """Return the product ID, or None."""
```

`__init__.py` registers adapters in priority order:

```python
_RESOLVERS = [
    ("shopify", _shopify.resolve),
    ("generic", _generic.resolve),
]
```

The first one returning non-None wins. The `generic` adapter is the always-available fallback (JSON-LD / meta tags / `data-product-id` / URL slug).

## How to add a new adapter

### Step 1 — figure out where the platform exposes the ID

Open one product page in dev tools. Look for:

- A JSON endpoint at a predictable path (Shopify's `/products/{handle}.js`, BigCommerce's `/api/storefront/products/{id}`)
- A `data-product-id="..."` attribute on a wrapper element
- A `<meta property="product:retailer_item_id">` tag
- A JSON-LD `<script type="application/ld+json">` block with `@type: Product` and `productID`/`sku`

Pick the most reliable signal.

### Step 2 — write the adapter

Example for a hypothetical platform that exposes `/api/products/by-slug/{handle}`:

```python
# eca/platforms/myplatform.py
from __future__ import annotations
import re
from typing import Optional
from urllib.parse import urlparse
import httpx


def resolve(client: httpx.Client, product_url: str) -> Optional[str]:
    m = re.search(r"/products?/([^/?#]+)", product_url)
    if not m:
        return None
    handle = m.group(1)
    parsed = urlparse(product_url)
    api_url = f"{parsed.scheme}://{parsed.netloc}/api/products/by-slug/{handle}"
    try:
        r = client.get(api_url, timeout=15.0)
        if r.status_code == 200:
            data = r.json()
            return str(data.get("id") or data.get("product_id") or "") or None
    except (httpx.HTTPError, ValueError):
        return None
    return None
```

### Step 3 — register it

```python
# eca/platforms/__init__.py
from . import myplatform as _myplatform

_RESOLVERS = [
    ("shopify", _shopify.resolve),
    ("myplatform", _myplatform.resolve),
    ("generic", _generic.resolve),  # fallback last
]
```

### Step 4 — test it

```bash
eca scrape https://example-myplatform-site.com --top 5 --platform myplatform
```

The `--platform` flag skips auto-detection and uses your adapter directly — useful for verifying it works in isolation.

## Common platform notes

- **Shopify** — covered by `shopify.py`. The `.js` endpoint is universal across themes.
- **BigCommerce** — products typically expose JSON-LD with `@type: Product`. The `generic` adapter often catches them. For dedicated support, use `/api/storefront/products?include=*` (storefront API) once you know the channel.
- **WooCommerce** — varies wildly by theme. Often has `data-product_id` on add-to-cart buttons. Generic JSON-LD usually works.
- **Magento** — `[data-product-id]` on the main product container; or look for `Magento_Catalog/.../product` JS config blobs in the page source.
- **Squarespace** — embed-based, IDs surfaced via JSON-LD or `data-item-id`.
- **Custom builds** — if no platform applies, the generic adapter will try its best. If that fails, the URL slug itself works for some review providers (Loox, Reviews.io).

## When the generic adapter is enough

If the site's review provider accepts a slug (not a numeric ID) — many do — the generic adapter's "URL slug fallback" is sufficient. Try a scrape without specifying `--platform` first and see if it works before writing a custom adapter.

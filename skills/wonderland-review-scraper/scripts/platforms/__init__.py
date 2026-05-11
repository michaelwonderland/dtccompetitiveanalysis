"""
Per-platform product-id resolvers.

Given a product URL like https://example.com/products/foo, return the
internal numeric/slug ID that the review widget API expects.

Each platform module exposes a `resolve(client, product_url) -> Optional[str]`
function. The unified `resolve_product_id` here tries them in order.
"""
from __future__ import annotations

from typing import Optional, Callable
import httpx

from . import shopify as _shopify
from . import generic as _generic


# Ordered list — first match wins. Add new platforms here.
_RESOLVERS: list[tuple[str, Callable[[httpx.Client, str], Optional[str]]]] = [
    ("shopify", _shopify.resolve),
    ("generic", _generic.resolve),
]


def resolve_product_id(client: httpx.Client, product_url: str,
                       platform: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Return (product_id, platform_name) or (None, None) if no resolver matched.

    If `platform` is given (e.g. "shopify"), only that resolver is tried.
    Otherwise resolvers are tried in order until one returns non-None.
    """
    if platform:
        for name, fn in _RESOLVERS:
            if name == platform:
                pid = fn(client, product_url)
                return (pid, name) if pid else (None, None)
        return (None, None)

    for name, fn in _RESOLVERS:
        pid = fn(client, product_url)
        if pid:
            return pid, name
    return None, None

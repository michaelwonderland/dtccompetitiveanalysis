# Architecture

A four-tier cascade. Each tier is more expensive than the last. The toolkit tries the cheap path first and falls back automatically.

## Tier 1 — sitemap-based product URL discovery

`crawler.py` requests `/sitemap.xml` from the target domain. Most ecommerce platforms (Shopify, BigCommerce, WooCommerce, Magento, Squarespace) expose one. The crawler walks nested sitemap files, collects URLs containing `/products/`, and returns a list. If the sitemap is missing or empty, it falls back to scraping `/collections/all`, `/products`, and `/` for `/products/` links.

**Why this works**: every ecommerce platform indexes its products. The exact format differs but the entry point is standard.

**When it fails**: sites with sitemaps that exclude products, or sites that put products at non-standard URLs (e.g. `/store/<slug>` instead of `/products/<slug>`). For those, you'd extend `crawler.py` with a custom URL pattern.

## Tier 2 — Playwright network interception (discovery)

`discovery.py` opens one product page in a headless Chromium, attaches a response listener that captures every JSON XHR, and heuristically scores each captured response:
- URL keywords (`review`, `rating`, `ugc`, provider names like `yotpo`, `judge.me`, `okendo`)
- Content-type (`application/json`)
- Body shape (object containing an array of dicts where each dict has 2+ of: rating/score/stars, body/content/text, author/name, title, created_at)

The highest-scoring response wins. Its URL becomes the review-data endpoint template; pagination params (`page`, `cursor`, `lastEvaluated`) and page-size params (`limit`, `perPage`, `take`) are detected automatically. The result is cached at `cache/{domain}.json` so future runs skip discovery entirely.

**Why this works**: every modern review widget loads its data via XHR/fetch. By watching network traffic during a real page load, we don't have to know the provider — the page tells us.

**When it fails**: sites that server-render reviews (rare in 2024+) or sites where the review widget is gated behind aggressive anti-bot. Tier 4 is the fallback.

## Tier 3 — direct API extraction

`extractor.py` hits the discovered endpoint directly with `httpx`, paginating until the API stops returning new reviews. Two pagination modes are detected at runtime:

- **Incremental**: `?page=1`, `?page=2`, … (Yotpo, Judge.me)
- **Cursor-based**: response includes `nextUrl` / `pagination.next` / HAL `_links.next` (Okendo, JSON:API style)

Per-product IDs are resolved by `eca/platforms/`:
- `shopify.py` — fetches `/products/{handle}.js` and reads the numeric `id`
- `generic.py` — falls back to JSON-LD, meta tags, `data-product-id` attributes, or the URL slug

Reviews are normalized into a common schema (`product_url, product_handle, author, rating, title, body, created_at, verified, helpful_count, review_id`) regardless of provider — alternate field names like `score`/`rating`, `dateCreated`/`createdAt`, `reviewer.isVerified`/`verifiedBuyer` are mapped automatically.

**Why this is the fast path**: at 2–3 requests per second per product, scraping a 50-product top 10 takes ~1–2 minutes per domain. No browser spin-up overhead.

**When it fails**: API returns 403/429 (rate-limit or IP block). Tier 4 takes over for the affected products.

## Tier 4 — DOM fallback

`dom_fallback.py` opens the product page in Playwright, scrolls/clicks "load more" buttons up to N times, then scrapes structured review data from the rendered DOM:

1. **Schema.org Review microdata** — `[itemtype*="Review"]` with `[itemprop]` children. Cleanest path; works on sites that mark up reviews properly for SEO.
2. **Provider-class selectors** — `.yotpo-review`, `.jdgm-rev`, `.stamped-review`, etc.
3. **Generic class match** — `[class*="review-item"]`, `[class*="reviewItem"]`, `[class*="reviewCard"]`.

This is lossy — only what's rendered is captured (often 10–20 reviews per product, vs hundreds via API) — but it works on sites where the API path is blocked.

## Why "provider-agnostic"

Most review-scraping tools require a per-provider adapter. This toolkit doesn't because it doesn't try to *understand* the provider — it just identifies the JSON response that *looks like reviews* and follows the pagination contract that response advertises. New providers work without code changes as long as they:
- Serve reviews via XHR/fetch in a recognizable JSON shape
- Either incrementally paginate (`?page=N`) or self-describe their next URL

About 95% of ecommerce review widgets on the market today fit this contract.

## What's deliberately not in the cascade

- **JavaScript reverse-engineering**: we don't read the widget JS, decode obfuscated tokens, or re-implement provider auth flows. If a site requires that, it's beyond this toolkit's scope.
- **Anti-bot evasion**: no browser fingerprint randomization, no proxy rotation, no CAPTCHA solving. Sites with Cloudflare/DataDome will return 403; the toolkit reports the failure honestly. Wire in a scraping API yourself if you need this.
- **Sentiment analysis**: the toolkit surfaces phrase frequencies and clusters; it does not score sentiment polarity. You (or Claude in a session) interpret meaning.

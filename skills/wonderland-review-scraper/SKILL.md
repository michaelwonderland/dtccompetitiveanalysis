---
name: wonderland-review-scraper
description: Use this skill when the user wants to programmatically pull customer reviews from one or more ecommerce websites. Triggers on requests like "scrape reviews from [domain]", "pull customer feedback for [brand]", "get me reviews from [site]", or any flow where the user has identified specific ecommerce domains and needs structured review data (CSVs, HTML, JSON) for downstream use — competitive analysis, social proof curation, sentiment work, NPI research, ad copy. Provider-agnostic — works across Yotpo, Judge.me, Okendo, Stamped, Loox, Bazaarvoice via a four-tier cascade (sitemap → Playwright network interception → API replay → DOM fallback). Surfaces anti-bot blocks (Cloudflare, DataDome) honestly with remediation options. Do NOT trigger for code review, document review, or non-ecommerce uses of "review."
---

# Scrape Reviews from Any Ecommerce Site

## What this skill does

Given an ecommerce domain (e.g. `example.com`), this skill pulls structured customer review data — CSVs (one row per review) and HTML (human-readable per product) — using a **four-tier cascade** that handles whichever review-widget provider the site uses (Yotpo, Judge.me, Okendo, Stamped, Loox, Bazaarvoice, custom). No provider-specific configuration required.

The skill is **provider-agnostic**: it identifies the review API by intercepting network calls during a real page load, then replays those calls directly. Works on most modern ecommerce sites without code changes.

## When to use this skill

- The user pastes an ecommerce domain or brand and asks for the customer reviews.
- The user wants to pull review data for downstream work (competitive analysis, social proof, sentiment work, ad copy mining, NPI research).
- The user has clearly named one or more specific ecommerce sites — not asking abstract "how do reviews work" questions.

**Do not use** for code review, document review, performance review, or non-ecommerce contexts.

## Setup (first run only)

The skill bundles its own scraping logic. Dependencies need to be installed once. Check:

```bash
python -c "import playwright, httpx, bs4, lxml, jinja2, click" 2>&1
```

If anything is missing, set up a project venv and install:

```bash
cd <user's working directory>
python3 -m venv .venv
source .venv/bin/activate
pip install -r ~/.claude/skills/wonderland-review-scraper/requirements.txt
python -m playwright install chromium
```

The user's working directory is where outputs will land — not the skill directory.

## How to invoke

From the user's working directory (with the venv activated):

```bash
python -m scripts.cli <domain> --top 10 \
  --sleep 0.5
```

But because the package lives at `~/.claude/skills/wonderland-review-scraper/scripts/`, you need to add it to `PYTHONPATH`:

```bash
PYTHONPATH=~/.claude/skills/wonderland-review-scraper python -m scripts.cli <domain> --top 10
```

Useful flags:

| Flag | What it does |
|---|---|
| `<domain>` | Required. The ecommerce site, e.g. `example.com` (no `https://` needed). |
| `--top N` | Scan all products, then full-fetch only the top N by review count. Recommended for sites with 100+ products. |
| `--max-products N` | Hard cap on products scanned. Useful for testing. |
| `--rediscover` | Force re-discovery of the review endpoint (otherwise cached). |
| `--headed` | Show the Playwright browser window during discovery. |
| `--dom-fallback` | Skip API path entirely; scrape rendered DOM. Slower and lossier. |
| `--platform shopify` | Force the Shopify product-id resolver. Auto-detected by default. |
| `--save-raw` | Also save the raw provider JSON per product. |

## Output structure

Outputs land in the user's current working directory:

```
output/
└── {domain}/
    ├── _scan.json                full-catalog scan: {handle, count, avg_rating} per product
    ├── {handle}.csv              one row per review · normalized schema
    ├── {handle}.html             readable per-product page with rating distribution + reviews
    └── index.html                per-domain summary, sorted by review count
cache/
└── {domain}.json                 discovered review-endpoint config (skip discovery on rerun)
```

CSV columns: `product_url, product_handle, author, rating, title, body, created_at, verified, helpful_count, review_id`.

## The 4-tier cascade (how it works)

1. **Sitemap discovery** — fetches `/sitemap.xml`, follows nested sitemaps, collects `/products/` URLs. Falls back to scraping `/collections/all` and homepage if no sitemap.
2. **Playwright network interception** — opens one product page in headless Chromium, intercepts every JSON XHR/fetch response, scores each by URL keywords + body shape (rating/body/author/created_at keys), picks the highest-scoring response as the review-data endpoint. Caches the URL template per domain.
3. **Direct API replay** — hits the discovered endpoint with `httpx`, paginates via either `?page=N` or provider-supplied `nextUrl` cursors, normalizes responses into a common schema. Fast: hundreds of products in seconds.
4. **DOM fallback** — if API yields 0 reviews for a product (provider quirk, gated product), reopens in Playwright and scrapes the rendered DOM. Lossier (only what's rendered) but always works.

Most runs never reach Tier 4. The cascade fails fast at each tier and tells you why.

## Anti-bot handling — IMPORTANT

If the API returns **HTTP 403** (typical for Cloudflare or DataDome blocks), the CLI logs:

```
⚠ ANTI-BOT DETECTED: API returned 403 (Cloudflare/DataDome).
  Halt and ask the user: ScrapingBee key, skip site, or DOM fallback?
```

When you see this in the output, **stop and ask the user**:

> "The site `<domain>` is blocking the scraper (HTTP 403, likely Cloudflare or DataDome). You have three paths forward:
> 
> **(a)** Provide a `SCRAPINGBEE_API_KEY` (or `BRIGHTDATA_*`) env var and I'll route through them. Best data, costs money. Sign up at scrapingbee.com or brightdata.com.
> 
> **(b)** Skip this site and continue with the others. Cleanest if you're running a multi-domain analysis.
> 
> **(c)** Use the DOM fallback (`--dom-fallback`). Slower (~10× per product) and lossier (~10–20% of the data), but no key needed and no cost.
> 
> Which do you want me to do?"

Do **not** silently fall through to DOM scraping. The user should make this call — different remediations have different cost, time, and data-completeness tradeoffs.

If the user picks (a), ScrapingBee integration is not yet built into this skill — surface that and offer to build it as a follow-up.

## ToS guardrails

Public review data is not the same as scrape-able-at-scale data. If the user is going to scrape **>100 products from a single domain or >5,000 reviews total**, surface a brief reminder:

> "Heads up — this scrape is at a scale where some sites consider it a ToS violation. Public review data isn't always public-to-scrape data. You're responsible for honoring each site's terms. Continue?"

This is not legal advice. It's polite operator hygiene.

## Common failure modes

| Symptom | Likely cause | What to do |
|---|---|---|
| Discovery fails, "Top score below threshold" | Site renders reviews server-side (no XHR) | Use `--dom-fallback` |
| All products return 0 reviews | Wrong endpoint cached | Run with `--rediscover` |
| 403 on API call | Cloudflare/DataDome | Anti-bot path above |
| Product IDs returning None | Non-Shopify platform | Try `--platform generic` |
| Pagination loops or stops at 100 | Provider has a rate limit | Increase `--sleep` to 1.0–2.0 |

## Boundaries

- **Don't** modify the user's working directory beyond `output/` and `cache/`.
- **Don't** install global packages — always use a venv.
- **Don't** make scraping decisions on the user's behalf when they're consequential (anti-bot, ToS, scale).
- **Do** show progress as it runs — multi-product scrapes can take several minutes.
- **Do** report the final review count + per-product breakdown so the user knows what they got.

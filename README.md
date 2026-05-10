# ecom-competitive-analysis

A provider-agnostic ecommerce review scraper, packaged as a Claude Code toolkit. Point it at a list of competitor domains, get back structured review data per product, distinctive-phrase synthesis across the corpus, and HTML dashboards. The strategic narrative is yours (or Claude's) to write — this toolkit gives you the evidence.

## What it does

- **Scrapes reviews** from ecommerce sites by intercepting the network calls that the site's own review widget makes (Yotpo, Judge.me, Okendo, Stamped, Loox, Bazaarvoice, etc.). No provider-specific code; the scraper identifies whichever review API the site uses and follows its pagination.
- **Aggregates the corpus** into per-brand review counts, rating distributions, and distinctive-phrase clusters that emerge from the actual reviews — not from a hardcoded persona list.
- **Renders HTML deliverables** — a top-N comparison dashboard and a templated narrative report.
- **Designed for Claude Code.** A `CLAUDE.md` at the repo root tells Claude how to run the pipeline; `prompts/` contains starter analysis playbooks. Open the repo in Claude Code and ask for the analysis.

## Why it exists

Most "competitive analysis" tooling either (a) charges thousands per month for SimilarWeb-style traffic guesswork or (b) requires you to manually scroll through a competitor's reviews page. This sits in between: it pulls the actual review corpus directly from each competitor's review widget, then synthesizes patterns from that data. The result is concrete (every claim is backed by a quote) and reproducible (re-run any time, same code).

## What it does NOT do

- It does not bypass anti-bot protection (Cloudflare, DataDome, etc.). About 5–10% of ecommerce sites will return 403. To support those, wire in a scraping API yourself.
- It does not write the strategic narrative. It surfaces patterns; you (or Claude in the session) interpret them. Forced narrative-from-template produces bland output.
- It does not promise legality. Public data is not the same as scrape-able-at-scale data. Honor each site's ToS; the user is responsible.
- It does not yet support non-Shopify platforms out of the box for product-id resolution. The crawler/discovery/extractor logic is platform-agnostic, but the per-product ID lookup currently has only a Shopify adapter. Adding BigCommerce/WooCommerce/custom is a one-file PR — see `docs/adding-a-platform.md`.

## Install

Requires Python 3.9+ and Node (no, just kidding — Node was for a deck generator that's been removed; Python only).

```bash
git clone <your-repo-url> ecom-competitive-analysis
cd ecom-competitive-analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

## Use

The simplest path:

```bash
# Full pipeline — scrape, aggregate, dashboard, report — with one command
eca pipeline <domain1> <domain2> <domain3> --top 10
# Outputs land in output/
```

Or run each step explicitly:

```bash
eca scrape <domain> --top 10                      # one domain at a time
eca aggregate <d1> <d2> <d3>                      # cross-brand synthesis
eca dashboard <d1> <d2> <d3>                      # comparison HTML
eca report <d1> <d2> <d3>                         # templated narrative HTML
```

Useful flags:

| Flag | Effect |
|---|---|
| `--top N` | Scan all products, pick top N by review count, full-fetch only those |
| `--max-products N` | Hard cap on products scanned |
| `--rediscover` | Force re-discovery of the review endpoint (otherwise cached) |
| `--headed` | Show the browser window during discovery |
| `--dom-fallback` | Skip the API path entirely; scrape rendered DOM |
| `--save-raw` | Also save the raw provider JSON per product |

## Outputs (per run)

```
output/
  {domain}/
    {product-handle}.csv          one row per review, normalized schema
    {product-handle}.html         styled per-product review page
    _scan.json                    full-catalog scan: review counts per product
    index.html                    per-domain summary
  _aggregate.json                 cross-brand: distinctive phrases, themes, samples
  dashboard.html                  cross-competitor top-N comparison
  report.html                     templated narrative (Claude fills the synthesis)
```

CSV schema: `product_url, product_handle, author, rating, title, body, created_at, verified, helpful_count, review_id`.

## Workflow with Claude Code

The recommended way to use this toolkit:

1. Clone into a working folder.
2. Open the folder in Claude Code.
3. Type something like: *"Run the competitive analysis on luxury-bedding-brand-a.com and luxury-bedding-brand-b.com — focus on gaps and strategic recommendations."*
4. Claude reads `CLAUDE.md`, runs the pipeline, reads `_aggregate.json`, and writes the synthesis directly into the conversation (and optionally into `report.html`).

You can also run it standalone — see `eca --help`.

## Architecture (one paragraph)

A four-tier cascade. **Tier 1**: pull product URLs from `/sitemap.xml`. **Tier 2**: open one product page in Playwright; intercept all XHR/fetch responses; heuristically score each (URL keywords + JSON body shape) to identify the review-data endpoint; cache the URL template per domain. **Tier 3**: hit the API directly with `httpx`, paginate via either page numbers or provider-supplied `nextUrl` cursors, normalize into a common Review schema. **Tier 4** (fallback): if the API path yields zero reviews for a product, re-open in Playwright and scrape the rendered DOM. Most runs never reach Tier 4. See [`docs/architecture.md`](docs/architecture.md) for details.

## Caveats and limitations

See [`docs/caveats.md`](docs/caveats.md) for a longer list. Highlights:
- Phrase synthesis is shallow — it captures recurring language, not sentiment, not sarcasm, not negation.
- Sample-size matters — a phrase mentioned in 30 reviews of 30,000 is signal, not certainty.
- Discovery can pick the wrong endpoint when sites have multiple review-shaped JSON responses (e.g. recommender widgets that include star ratings). Inspect `cache/{domain}.json` if numbers look off.

## License

MIT — see [LICENSE](LICENSE). Use freely.

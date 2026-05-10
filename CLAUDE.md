# CLAUDE.md — operator instructions

You are working inside the `ecom-competitive-analysis` toolkit. Its job is to produce structured review-data primitives from ecommerce sites; **your job is to read those primitives and synthesize the analysis** the user is asking for.

## Standard pipeline

For a competitive analysis between N domains, run these in order:

```bash
# 1. Per domain — scrape top N products by review count
eca scrape <domain> --top 10
# Outputs: output/{domain}/{handle}.csv, {handle}.html, _scan.json, index.html

# 2. Aggregate across all domains — distinctive-phrase synthesis
eca aggregate <domain1> <domain2> ... --out output/_aggregate.json
# Outputs: _aggregate.json with per-brand frequencies, distinctive phrases,
#          candidate themes (clusters of co-occurring distinctive phrases),
#          and sample quotes per theme.

# 3. Dashboard — cross-competitor top-N HTML
eca dashboard <domain1> <domain2> ... --out output/dashboard.html

# 4. Report (templated narrative — you fill it in)
eca report <domain1> <domain2> ... --out output/report.html
```

Or `eca pipeline <domain1> <domain2> ...` to do all four with sane defaults.

## Where the synthesis happens

`_aggregate.json` is the file you read when the user asks for analysis. It contains:

- `per_brand[domain]` — review count, avg rating, distribution, low-rated count
- `per_brand[domain].top_phrases` — n-grams over-represented vs the rest of the corpus, with frequencies and 2-3 sample quotes each
- `themes` — clusters of co-occurring distinctive phrases, with per-brand share of voice and candidate theme labels (mechanically derived from top phrases — feel free to rename them based on what the cluster actually represents)
- `cross_brand_overlap` — phrases that appear distinctively in multiple brands
- `negative_themes` — distinctive phrases within reviews rated ≤3, by brand

**The toolkit does not name personas.** Top-phrase clusters are surfaced; you decide which represent customer personas vs product attributes vs marketing language, and you write the narrative.

## Limitations to communicate clearly to the user

1. **Sample-size honesty.** If a phrase appears in 50 reviews out of 50,000, the relative percentage is meaningful only as a directional signal. Don't over-interpret tiny clusters.
2. **Regex/n-gram synthesis is shallow.** It captures recurring language; it does not capture sentiment polarity, sarcasm, or context. Cross-check distinctive phrases against the sample quotes before citing them as evidence.
3. **Bot-blocked sites fail silently.** If `eca scrape` returns 0 reviews for a domain that visibly has reviews, it likely hit Cloudflare/DataDome. The toolkit does not currently route around those. Tell the user.
4. **Shopify is the best-supported platform.** Other platforms work in many cases (sitemap + Playwright discovery is platform-agnostic) but per-product ID resolution may need a platform-specific adapter — see `docs/adding-a-platform.md`.
5. **Public data ≠ permission to scrape at scale.** The user is responsible for honoring each site's ToS. Surface this if a scrape is unusually large.

## Starter prompts the user may invoke

The `prompts/` directory contains reusable playbooks. If the user says "run the competitive analysis on these domains," follow `prompts/competitive-analysis.md`. If they ask for personas specifically, follow `prompts/persona-deep-dive.md`. These are not strict — adapt to what the user actually wants.

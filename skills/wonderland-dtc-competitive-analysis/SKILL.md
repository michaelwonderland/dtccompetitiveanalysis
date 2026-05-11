---
name: wonderland-dtc-competitive-analysis
description: Use this skill when the user wants a head-to-head competitive analysis of 2–5 ecommerce DTC brands using public customer reviews as the evidence base. Triggers on requests like "compare these competitors", "analyze [brand A] vs [brand B] vs [brand C]", "do a competitive analysis on [domain list]", or any framing where the user has named multiple competitor domains and asks strategic questions (positioning, personas served, category gaps, differentiation, hero SKUs). Runs the full pipeline — scrape each brand's reviews → cross-corpus distinctive-phrase synthesis → cross-brand dashboard + narrative report → surfaces operator questions for the user to direct. Does NOT trigger for single-brand sentiment analysis (use wonderland-review-scraper instead) or for non-ecommerce industries.
---

# DTC Competitive Analysis from Customer Reviews

## What this skill does

Given 2–5 ecommerce brand domains (e.g. `carawayhome.com`, `fromourplace.com`, `hexclad.com`), this skill runs the full competitive-analysis pipeline:

1. **Scrape** each brand's top-10 products by review count (provider-agnostic — Yotpo, Judge.me, Okendo, Stamped, Loox, etc.)
2. **Aggregate** the corpus across brands — distinctive-phrase synthesis, theme clustering, persona signals
3. **Render** a cross-brand HTML dashboard + a templated narrative report
4. **Surface operator questions** for the user to direct what comes next

Then **stops and waits** for the user to choose which strategic question to dig into. The skill produces the evidence; the user (with Claude's help) makes the strategic call.

## When to use this skill

- The user names 2 or more specific ecommerce domains and asks a comparative or strategic question.
- The user wants positioning, persona, hero-SKU, or category-gap analysis across brands.
- The user uses framing like "compare", "analyze", "competitive analysis", "vs", "head to head", "where are we losing", "what are they doing better".

**Do not use** for:

- Single-brand sentiment work (use `wonderland-review-scraper` skill instead).
- Non-ecommerce competitive intelligence (B2B SaaS, services, etc.).
- Pure financial / market-share comparison (this skill works on review language, not revenue data).

## Setup (first run only)

The skill bundles its own scraping and analysis logic. Dependencies need to be installed once. From the user's working directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r ~/.claude/skills/wonderland-dtc-competitive-analysis/requirements.txt
python -m playwright install chromium
```

## How to invoke

The skill exposes a unified CLI with subcommands. Recommended path is the `pipeline` subcommand which orchestrates all steps:

```bash
PYTHONPATH=~/.claude/skills/wonderland-dtc-competitive-analysis \
  python -m scripts.cli pipeline domain-a.com domain-b.com domain-c.com --top 10
```

This produces, in the user's working directory:

```
output/
├── domain-a.com/
│   ├── _scan.json
│   ├── {handle}.csv               (× 10 products)
│   ├── {handle}.html              (× 10 products)
│   └── index.html
├── domain-b.com/
│   └── (same structure)
├── domain-c.com/
│   └── (same structure)
├── _aggregate.json                cross-brand synthesis: phrases, themes, samples
├── dashboard.html                 cross-competitor comparison view
└── report.html                    narrative report with observations
```

Useful flags on `pipeline`:

| Flag | What it does |
|---|---|
| `--top N` | Top-N products per brand to fully scrape (default 10). Lower for quick tests, higher for completeness. |
| `--platform shopify` | Force Shopify product-id resolver for all domains (skip auto-detection). |
| `--skip-scrape` | Reuse existing `output/{domain}/` folders. Only re-runs aggregate + dashboard + report. Useful for iteration. |

## Pipeline stages — what to expect

**Stage 1 — Scrape (5–30 min depending on volume)**: each domain in turn. Big-volume sites (10K+ reviews per top product) can take 2–5 min per brand. Show the per-product progress to the user as it runs. If one site hits a 403, **stop the whole pipeline and ask** — see Anti-bot below.

**Stage 2 — Aggregate (~30 sec)**: tokenizes review bodies, computes distinctive phrases per brand (smoothed lift × √frequency), clusters phrases into themes by review co-occurrence (Jaccard ≥ 0.30 union-find). Output: `_aggregate.json`.

**Stage 3 — Dashboard render (~5 sec)**: top stats + cross-brand themes table + per-brand top products + distinctive phrases. Output: `dashboard.html`.

**Stage 4 — Report render (~5 sec)**: narrative-style HTML with auto-generated thesis, per-theme commentary, per-brand summaries. Output: `report.html`.

**Stage 5 — Operator questions (this is where you stop)**: do NOT continue. Surface the menu of strategic questions. See `prompts/operator-questions.md` for the exact text. Wait for the user to pick.

## Anti-bot handling — IMPORTANT

If any domain returns HTTP 403 during the scrape stage, the CLI logs:

```
⚠ ANTI-BOT DETECTED: API returned 403 (Cloudflare/DataDome).
  Halt and ask the user: ScrapingBee key, skip site, or DOM fallback?
```

**Stop the pipeline and ask the user**:

> "The site `<domain>` is blocking the scraper (HTTP 403, likely Cloudflare or DataDome). You have three paths forward:
> 
> **(a)** Provide a `SCRAPINGBEE_API_KEY` env var and route through them (best data, costs money).
> 
> **(b)** Drop this domain from the analysis and run the comparison without it (cleanest if you have 3+ domains).
> 
> **(c)** Use the DOM fallback for this domain only (`--dom-fallback`). Slower and lossier but free.
> 
> Which do you want?"

Don't silently fall through. The user picks.

## The operator-questions phase — IMPORTANT

After Stage 4, **do not auto-answer the strategic question**. Instead, surface the menu of six questions from `prompts/operator-questions.md`, plus your own one-line opinion drawn from the data — e.g. *"Question 4 looks most interesting here: Brand B's #1 SKU pulls 38% of their top-10 review volume — 2× the others, suggesting hero-dependence."*

Wait for the user to pick. When they do, dig into that specific question by reading `_aggregate.json` + the per-product CSVs. Cite specific numbers and quotes — don't generalize.

This is the "Claude as direct report, not search engine" pattern: the user makes the strategic call. You produce evidence on demand.

## ToS guardrails

A typical run scrapes 30 product histories across 3 domains — usually a few thousand reviews. If the user is scaling beyond that (5+ domains, or `--top 50` plus), surface a brief reminder:

> "Heads up — this scrape is at a scale where some sites consider it a ToS violation. Public review data isn't always public-to-scrape data. You're responsible for honoring each site's terms. Continue?"

## Boundaries

- **Don't** hallucinate insights. Every claim must trace to a number or phrase in `_aggregate.json` or a CSV.
- **Don't** make brand judgments without data. "Brand A is better than Brand B" is a quality judgment that belongs to the user. "Brand A's distinctive complaint phrases include 'X', 'Y', 'Z'" is a fact.
- **Don't** auto-answer multiple operator questions in one go. One question at a time, with the user's direction.
- **Do** show progress as the pipeline runs.
- **Do** surface anti-bot blocks immediately, not at the end.
- **Do** suggest a follow-up move at the end of any analysis ("Want me to also check Q3?") — but only one at a time.

## Common failure modes

| Symptom | Likely cause | What to do |
|---|---|---|
| Discovery fails on one domain | Site renders reviews server-side | Use `--dom-fallback` for that domain only |
| 403 on a domain | Anti-bot block | Anti-bot path above |
| Dashboard themes look like brand names | Brand tokens leaking through filter | Pass `--exclude-terms "brand,product-line,sku-prefix"` to the aggregate command |
| One brand has way more reviews than others | Different time on market or different review-collection rigor | Don't conflate review volume with brand health; surface the caveat |
| Aggregate finds <5 themes | Corpus too small (< ~1000 reviews per brand) | Increase `--top` to capture more SKUs |

## Related skill

For single-brand review scraping (no cross-brand analysis), use **`wonderland-review-scraper`** instead. This skill duplicates the scraping logic for self-containment but it's the same engine.

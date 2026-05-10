"""
Narrative competitive-analysis report HTML.

Reads the JSON produced by `eca aggregate` and renders a longer-form HTML
report with auto-generated prose around the data. Intended as a starting
point that Claude (in a Claude Code session) can read and rewrite with
sharper synthesis — but it is publishable as-is.

Brand-agnostic and category-agnostic. No assumptions about industry or
persona vocabulary; everything is derived from the corpus.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from jinja2 import Template

from .dashboard import palette_for, PALETTE


# -----------------------------------------------------------------------------
# Auto-generated prose helpers
# -----------------------------------------------------------------------------

def _fmt(n) -> str:
    if n is None:
        return "—"
    if isinstance(n, (int, float)):
        return f"{int(n):,}" if float(n).is_integer() else f"{n:.2f}"
    return str(n)


def _generate_thesis(data: dict) -> dict:
    """Build a 2-3 sentence headline finding from the data."""
    brands = data.get("brands", {})
    domains = data.get("global", {}).get("all_brands", list(brands.keys()))
    if len(domains) < 2:
        return {"headline": "Single-brand corpus — no comparative thesis available.", "supporting": ""}

    # Volume ranking
    by_reviews = sorted(domains, key=lambda d: -(brands[d].get("review_count") or 0))
    biggest, smallest = by_reviews[0], by_reviews[-1]
    biggest_n = brands[biggest].get("review_count") or 0
    smallest_n = brands[smallest].get("review_count") or 0
    ratio = (biggest_n / smallest_n) if smallest_n else 0

    # Quality ranking
    rated = [d for d in domains if brands[d].get("avg_rating") is not None]
    by_quality = sorted(rated, key=lambda d: -brands[d]["avg_rating"]) if rated else []
    by_complaint = sorted(
        rated,
        key=lambda d: -(brands[d].get("low_rated_count") or 0) / max(1, brands[d].get("review_count") or 1),
    ) if rated else []

    parts = []
    if ratio >= 2:
        parts.append(
            f"<b>{biggest}</b> has roughly {ratio:.1f}× the review volume of <b>{smallest}</b> "
            f"({_fmt(biggest_n)} vs {_fmt(smallest_n)})."
        )
    if by_quality and by_complaint and by_quality[0] != by_complaint[0]:
        best = by_quality[0]
        parts.append(
            f"<b>{best}</b> carries the highest weighted rating "
            f"({brands[best]['avg_rating']:.2f}/5)."
        )

    headline = " ".join(parts) or f"{len(domains)} brands compared across {_fmt(data.get('global',{}).get('total_reviews'))} reviews."
    return {
        "headline": headline,
        "biggest": biggest, "smallest": smallest, "ratio": ratio,
    }


def _theme_commentary(theme: dict, domains: list[str]) -> str:
    """One-sentence auto-commentary on a theme's brand distribution."""
    shares = theme.get("brand_share_pct", {})
    if not shares:
        return ""
    sorted_brands = sorted(domains, key=lambda d: -shares.get(d, 0))
    top = sorted_brands[0]
    top_pct = shares.get(top, 0)
    if len(domains) >= 2:
        runner = sorted_brands[1]
        runner_pct = shares.get(runner, 0)
        if top_pct > 0 and runner_pct > 0:
            ratio = top_pct / runner_pct if runner_pct else 999
            if ratio >= 1.4:
                return f"Heavily skewed toward <b>{top}</b> ({top_pct:.1f}% of reviews) — {ratio:.1f}× <b>{runner}</b> ({runner_pct:.1f}%)."
            elif ratio >= 1.1:
                return f"<b>{top}</b> leads ({top_pct:.1f}%) but <b>{runner}</b> follows close ({runner_pct:.1f}%)."
        return f"Most prominent in <b>{top}</b> ({top_pct:.1f}% of reviews)."
    return f"<b>{top}</b>: {top_pct:.1f}% of reviews."


def _brand_summary_line(brand_data: dict, domain: str) -> str:
    """Sentence describing what's most distinctive about this brand's reviews."""
    distinct = brand_data.get("distinctive_phrases", [])[:3]
    if not distinct:
        return f"No phrases distinctively over-indexed for <b>{domain}</b>."
    phrases = ", ".join(f"<i>{p['phrase']}</i> ({p['lift']:.1f}×)" for p in distinct)
    return f"<b>{domain}</b>'s most distinctive language: {phrases}."


# -----------------------------------------------------------------------------
# HTML template
# -----------------------------------------------------------------------------

REPORT_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Competitive review analysis — {{ domains|join(' · ') }}</title>
<style>
:root { --fg:#111827; --muted:#6b7280; --border:#e5e7eb; --bg:#fff; --soft:#f9fafb; --insight:#92400e; }
* { box-sizing: border-box; }
body { font-family: ui-serif, Georgia, "Iowan Old Style", Baskerville, "Times New Roman", serif; max-width: 800px; margin: 3rem auto; padding: 0 1.5rem; color: var(--fg); line-height: 1.65; font-size: 17px; }
h1, h2, h3, h4 { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; letter-spacing: -0.015em; }
h1 { font-size: 2.4rem; line-height: 1.15; margin: 0.5rem 0 1rem; }
h2 { font-size: 1.7rem; margin: 3.5rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border); }
h3 { font-size: 1.2rem; margin: 2rem 0 0.5rem; }
.kicker { color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.78rem; font-weight: 600; font-family: -apple-system, sans-serif; }
.lede { font-size: 1.1rem; line-height: 1.55; color: #1f2937; margin: 1rem 0 0; }
.muted { color: var(--muted); font-size: 0.92rem; }
.hero { padding-bottom: 1.5rem; border-bottom: 3px solid #111827; }
em { color: #1f2937; font-style: italic; }

.stats { display: grid; grid-template-columns: repeat({{ domains|length }}, 1fr); gap: 0.75rem; margin: 1.5rem 0 2rem; font-family: -apple-system, sans-serif; }
.stat { padding: 1rem; border-radius: 10px; }
.stat .domain { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
.stat .big { font-size: 2rem; font-weight: 700; line-height: 1.1; margin: 0.2rem 0; font-variant-numeric: tabular-nums; }
.stat .sub { font-size: 0.84rem; opacity: 0.85; }

.theme { padding: 1rem 1.2rem; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 1rem; }
.theme h4 { margin: 0 0 0.5rem; font-size: 1.05rem; }
.theme .pills { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.5rem 0; }
.theme .pill { background: var(--soft); border: 1px solid var(--border); padding: 0.1rem 0.5rem; border-radius: 99px; font-size: 0.82rem; font-family: ui-monospace, "SF Mono", monospace; }
.theme .commentary { font-family: -apple-system, sans-serif; font-size: 0.92rem; color: #374151; }
.theme blockquote { background: var(--soft); border-left: 3px solid var(--border); padding: 0.5rem 0.8rem; margin: 0.5rem 0 0; font-size: 0.9rem; line-height: 1.5; color: #374151; font-family: -apple-system, sans-serif; }
.theme blockquote .meta { font-size: 0.74rem; color: var(--muted); margin-bottom: 0.25rem; }

.placeholder { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); padding: 1rem 1.25rem; border-radius: 10px; border-left: 4px solid #f59e0b; margin: 1rem 0 1.5rem; font-family: -apple-system, sans-serif; font-size: 0.95rem; }
.placeholder .marker { font-size: 0.75rem; color: var(--insight); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; margin-bottom: 0.4rem; }
.placeholder ul { margin: 0.4rem 0 0 1rem; padding: 0; }

.brand-block { padding: 1rem 1.2rem; border-radius: 10px; margin-bottom: 1.5rem; font-family: -apple-system, sans-serif; }
.brand-block .domain { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; margin-bottom: 0.5rem; }
.brand-block h3 { margin: 0 0 0.4rem; font-size: 1.15rem; }
.brand-block .pills { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.5rem 0; }
.brand-block .pill { background: rgba(255,255,255,0.7); border: 1px solid rgba(0,0,0,0.06); padding: 0.1rem 0.5rem; border-radius: 99px; font-size: 0.82rem; font-family: ui-monospace, monospace; }
.brand-block .pill .lift { color: var(--muted); margin-left: 0.25rem; font-size: 0.75rem; }

.footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; font-family: -apple-system, sans-serif; }
</style>
</head>
<body>

<header class="hero">
<div class="kicker">Competitive review analysis · {{ '{:,}'.format(total_reviews) }} reviews</div>
<h1>{{ domains|join(' vs ') }}</h1>
<p class="lede">{{ thesis.headline|safe }}</p>
</header>

<section>
<div class="stats">
{% for d in domains %}
{% set b = brands[d] %}
{% set p = palette[d] %}
<div class="stat" style="background: #{{ p.bg }};">
  <div class="domain" style="color: #{{ p.fg }};">{{ d }}</div>
  <div class="big" style="color: #{{ p.fg }};">{{ '{:,}'.format(b.review_count or 0) }}</div>
  <div class="sub">reviews · avg {{ '%.2f'|format(b.avg_rating) if b.avg_rating else '—' }} / 5 · {{ '%.1f'|format((b.low_rated_count or 0) / (b.review_count or 1) * 100) }}% low-rated</div>
</div>
{% endfor %}
</div>
</section>

<section>
<h2>Themes that emerged from the corpus</h2>
<p class="muted">Each block below is a cluster of distinctive phrases that frequently co-occur in reviews. Theme labels are mechanical (top phrases joined). Brand-share % = % of that brand's reviews mentioning at least one phrase in the cluster.</p>

{% for t in themes %}
<div class="theme">
  <h4>{{ t.label }}</h4>
  <div class="pills">{% for ph in t.phrases[:10] %}<span class="pill">{{ ph }}</span>{% endfor %}{% if t.phrases|length > 10 %}<span class="muted" style="font-family: -apple-system, sans-serif; font-size: 0.85rem;"> +{{ t.phrases|length - 10 }} more</span>{% endif %}</div>
  <div class="commentary">{{ theme_commentary[loop.index0]|safe }}</div>
  {% for d in domains %}<span class="muted" style="font-size: 0.78rem; margin-right: 0.6rem;">{{ d }}: <b style="color: #{{ palette[d].fg }};">{{ '%.1f'|format(t.brand_share_pct.get(d, 0)) }}%</b></span>{% endfor %}
  {% if t.samples %}
  <blockquote>
    <div class="meta">{{ t.samples[0].author or 'Anonymous' }} · {{ t.dominant_brand }}/{{ t.samples[0].handle }} · {{ t.samples[0].rating|int }}★</div>
    {{ t.samples[0].body }}
  </blockquote>
  {% endif %}
</div>
{% endfor %}

<div class="placeholder">
<div class="marker">For Claude (or you) to fill in</div>
Above is what the data surfaces. Read each theme cluster against its sample quote and decide which represent customer personas (e.g. "the hot sleeper"), which represent product attributes (e.g. "softness"), and which represent marketing language (e.g. "luxurious"). Then write 3–5 takeaways below — connecting themes to strategic implications for whichever brand is the focus of the analysis.
<ul>
<li><i>Take 1: …</i></li>
<li><i>Take 2: …</i></li>
<li><i>Take 3: …</i></li>
</ul>
</div>
</section>

<section>
<h2>What's distinctive about each brand</h2>
{% for d in domains %}
{% set b = brands[d] %}
{% set p = palette[d] %}
<div class="brand-block" style="background: #{{ p.bg }}; border: 1px solid #{{ p.fg }}33;">
  <div class="domain" style="color: #{{ p.fg }};">{{ d }}</div>
  <h3>{{ '{:,}'.format(b.review_count) }} reviews · avg {{ '%.2f'|format(b.avg_rating) if b.avg_rating else '—' }}</h3>
  <p class="muted" style="margin: 0.25rem 0 0.5rem;">{{ brand_summaries[d]|safe }}</p>

  <div class="pills">
  {% for ph in b.distinctive_phrases[:20] %}
  <span class="pill"><b>{{ ph.phrase }}</b><span class="lift">{{ '%.1f'|format(ph.lift) }}× · {{ '{:,}'.format(ph.freq) }}</span></span>
  {% endfor %}
  </div>

  {% if b.distinctive_phrases and b.distinctive_phrases[0].samples %}
  <blockquote style="background: rgba(255,255,255,0.6); border-left: 3px solid #{{ p.fg }}; padding: 0.5rem 0.85rem; margin-top: 0.6rem; border-radius: 4px; font-size: 0.9rem;">
    <div class="muted" style="font-size: 0.75rem; margin-bottom: 0.2rem;"><b>"{{ b.distinctive_phrases[0].phrase }}"</b> · {{ b.distinctive_phrases[0].samples[0].author or 'Anonymous' }} · {{ b.distinctive_phrases[0].samples[0].handle }} · {{ b.distinctive_phrases[0].samples[0].rating|int }}★</div>
    {{ b.distinctive_phrases[0].samples[0].body }}
  </blockquote>
  {% endif %}

  {% if b.negative_distinctive_phrases %}
  <div style="margin-top: 0.8rem;">
    <div class="muted" style="font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.3rem;">Distinctive in low-rated reviews</div>
    <div class="pills">
    {% for ph in b.negative_distinctive_phrases[:10] %}
    <span class="pill" style="background: #fef2f2; border-color: #fecaca;"><b>{{ ph.phrase }}</b><span class="lift">{{ '%.1f'|format(ph.lift) }}× · {{ '{:,}'.format(ph.freq) }}</span></span>
    {% endfor %}
    </div>
  </div>
  {% endif %}
</div>
{% endfor %}
</section>

<section>
<h2>Methodology</h2>
<p class="muted">Reviews were collected from each brand's review-widget API (Yotpo, Okendo, Judge.me, etc.) via a provider-agnostic scraper. For each brand the entire product catalogue was scanned for review counts; the top products by count were fully extracted.</p>
<p class="muted">Distinctive phrases per brand are 1–3 grams over-represented vs the rest of the corpus, scored by smoothed lift × √frequency on review-presence (a phrase counts once per review, not once per occurrence). Common stopwords and pure-stopword n-grams are filtered. Themes are clusters of distinctive phrases that co-occur in the same reviews above a Jaccard-similarity threshold (union-find).</p>
<p class="muted">Caveat: phrase synthesis captures recurring language, not sentiment, sarcasm, or negation. Cross-check distinctive phrases against sample quotes before citing them as evidence of intent. Sample sizes per phrase are reported as raw counts — interpret single-digit-percentage differences cautiously.</p>
</section>

<div class="footer">
Generated by <code>eca report</code>. Source data: <code>_aggregate.json</code>. Re-run any time with the same code; the data updates with the corpus.
</div>

</body>
</html>
""")


def render(aggregate_path: Path, out_path: Path) -> None:
    data = json.loads(aggregate_path.read_text())
    domains: list[str] = data.get("global", {}).get("all_brands", [])
    if not domains:
        domains = list(data.get("brands", {}).keys())

    brands = data.get("brands", {})
    themes = data.get("themes", [])
    palette = palette_for(domains)
    thesis = _generate_thesis(data)
    theme_commentary = [_theme_commentary(t, domains) for t in themes]
    brand_summaries = {d: _brand_summary_line(brands.get(d, {}), d) for d in domains}

    html_text = REPORT_TEMPLATE.render(
        domains=domains,
        brands=brands,
        themes=themes,
        palette=palette,
        thesis=thesis,
        theme_commentary=theme_commentary,
        brand_summaries=brand_summaries,
        total_reviews=data.get("global", {}).get("total_reviews", 0),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")

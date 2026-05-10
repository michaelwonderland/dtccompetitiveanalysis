"""
Cross-competitor dashboard HTML generator.

Reads the JSON produced by `eca aggregate` and renders a single HTML page
with: stat cards per brand, cross-brand themes table (corpus-synthesized
clusters), per-brand distinctive phrases, and per-brand top products.

No category or brand assumptions — works for any list of domains.
"""
from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Optional

from jinja2 import Template


# Color palette per brand index (cycles if more than 5 brands).
PALETTE = [
    {"name": "rose", "fg": "DB2777", "bg": "FCE7F3"},
    {"name": "indigo", "fg": "4F46E5", "bg": "E0E7FF"},
    {"name": "emerald", "fg": "059669", "bg": "D1FAE5"},
    {"name": "amber", "fg": "D97706", "bg": "FEF3C7"},
    {"name": "cyan", "fg": "0891B2", "bg": "CFFAFE"},
    {"name": "violet", "fg": "7C3AED", "bg": "EDE9FE"},
]


def palette_for(domains: list[str]) -> dict[str, dict]:
    return {d: PALETTE[i % len(PALETTE)] for i, d in enumerate(domains)}


DASHBOARD_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Competitive review dashboard — {{ domains|join(' · ') }}</title>
<style>
:root { --fg:#111827; --muted:#6b7280; --border:#e5e7eb; --bg:#fff; --soft:#f9fafb; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 1200px; margin: 2rem auto; padding: 0 1.5rem; color: var(--fg); }
h1 { letter-spacing: -0.015em; margin-bottom: 0.25rem; font-size: 2rem; }
h2 { margin: 3rem 0 0.5rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--border); font-size: 1.5rem; letter-spacing: -0.01em; }
h3 { margin: 2rem 0 0.5rem; font-size: 1.15rem; }
.subtitle { color: var(--muted); margin-bottom: 2rem; }
.muted { color: var(--muted); font-size: 0.9rem; }

.stats { display: grid; grid-template-columns: repeat({{ domains|length }}, 1fr); gap: 0.75rem; margin: 1.5rem 0 2rem; }
.stat { padding: 1.1rem; border-radius: 10px; }
.stat .domain { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 700; }
.stat .big { font-size: 2.2rem; font-weight: 700; line-height: 1.05; margin: 0.25rem 0; font-variant-numeric: tabular-nums; }
.stat .sub { font-size: 0.86rem; opacity: 0.85; }
.stat .extra { margin-top: 0.4rem; font-size: 0.78rem; opacity: 0.8; border-top: 1px dashed rgba(0,0,0,0.15); padding-top: 0.4rem; }

table { border-collapse: collapse; width: 100%; font-size: 0.92rem; margin: 0.5rem 0 1.5rem; }
th, td { padding: 0.55rem 0.7rem; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--soft); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.right { text-align: right; }
.center { text-align: center; }

.theme-share { display: inline-flex; gap: 4px; align-items: center; }
.theme-share .bar-track { width: 80px; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
.theme-share .bar-fill { height: 100%; }
.theme-share .num { font-variant-numeric: tabular-nums; font-size: 0.82rem; min-width: 35px; }

.tag { display: inline-block; font-size: 0.78rem; padding: 0.15rem 0.55rem; border-radius: 99px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }

.phrases { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0; }
.phrase-pill { background: var(--soft); border: 1px solid var(--border); padding: 0.15rem 0.55rem; border-radius: 99px; font-size: 0.85rem; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.phrase-pill .lift { color: var(--muted); margin-left: 0.3rem; font-size: 0.78rem; }

blockquote.q { background: var(--soft); border-left: 3px solid var(--border); padding: 0.55rem 0.85rem; margin: 0.4rem 0; font-size: 0.9rem; line-height: 1.5; color: #374151; }
blockquote.q .meta { font-size: 0.74rem; color: var(--muted); margin-bottom: 0.25rem; }

.brand-section { padding: 1rem 1.2rem; border-radius: 10px; margin-bottom: 1.5rem; }
.brand-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.75rem; }
.brand-header h3 { margin: 0; font-size: 1.2rem; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
.footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; }
</style>
</head>
<body>

<h1>Competitive review dashboard</h1>
<p class="subtitle">{{ domains|length }} brands · {{ '{:,}'.format(total_reviews) }} reviews aggregated</p>

<div class="stats">
{% for d in domains %}
{% set b = brands[d] %}
{% set p = palette[d] %}
<div class="stat" style="background: #{{ p.bg }};">
  <div class="domain" style="color: #{{ p.fg }};">{{ d }}</div>
  <div class="big" style="color: #{{ p.fg }};">{{ '{:,}'.format(b.review_count or 0) }}</div>
  <div class="sub">reviews collected · avg {{ '%.2f'|format(b.avg_rating) if b.avg_rating else '—' }} / 5</div>
  <div class="extra">
    Low-rated (≤3★): {{ '{:,}'.format(b.low_rated_count or 0) }} ({{ '%.1f'|format((b.low_rated_count or 0) / (b.review_count or 1) * 100) }}%)<br>
    Top product: {{ b.products[0].handle if b.products else '—' }} ({{ '{:,}'.format(b.products[0].count) if b.products else 0 }})
  </div>
</div>
{% endfor %}
</div>

<h2>Cross-brand themes (synthesized from review corpus)</h2>
<p class="muted">Clusters of distinctive phrases that co-occur in reviews. Brand-share % = % of that brand's reviews mentioning at least one phrase in the cluster.</p>
<table>
<thead>
<tr>
  <th>Theme (top phrases)</th>
  <th>All cluster phrases</th>
  {% for d in domains %}<th class="right">{{ d }}</th>{% endfor %}
  <th>Sample</th>
</tr>
</thead>
<tbody>
{% for t in themes %}
<tr>
  <td><b>{{ t.label }}</b></td>
  <td><div class="phrases">{% for p in t.phrases[:8] %}<span class="phrase-pill">{{ p }}</span>{% endfor %}{% if t.phrases|length > 8 %}<span class="muted">+{{ t.phrases|length - 8 }} more</span>{% endif %}</div></td>
  {% set max_share = (t.brand_share_pct.values()|list|max) if t.brand_share_pct else 0 %}
  {% for d in domains %}
  {% set share = t.brand_share_pct.get(d, 0) %}
  <td class="right">
    <div class="theme-share">
      <span class="bar-track"><span class="bar-fill" style="width: {{ (share / max_share * 100) if max_share else 0 }}%; background: #{{ palette[d].fg }};"></span></span>
      <span class="num">{{ '%.1f'|format(share) }}%</span>
    </div>
  </td>
  {% endfor %}
  <td>
    {% if t.samples %}
    <blockquote class="q">
      <div class="meta">{{ t.samples[0].author or 'Anonymous' }} · {{ t.dominant_brand }}/{{ t.samples[0].handle }}</div>
      {{ t.samples[0].body|truncate(180, True, '…') }}
    </blockquote>
    {% endif %}
  </td>
</tr>
{% endfor %}
</tbody>
</table>

{% for d in domains %}
{% set b = brands[d] %}
{% set p = palette[d] %}

<div class="brand-section" style="background: #{{ p.bg }}; border: 1px solid #{{ p.fg }}33;">
<div class="brand-header">
  <h3 style="color: #{{ p.fg }};">{{ d }}</h3>
  <span class="muted">{{ '{:,}'.format(b.review_count) }} reviews · {{ b.products|length }} products</span>
</div>

<h4 style="margin: 1rem 0 0.4rem; font-size: 0.95rem;">Top products by review volume</h4>
<table>
<thead>
<tr><th>#</th><th>Product</th><th class="right">Reviews</th><th class="right">Avg</th></tr>
</thead>
<tbody>
{% for prod in b.products[:10] %}
<tr>
<td class="muted">{{ loop.index }}</td>
<td><a href="{{ prod.product_url }}" target="_blank">{{ prod.handle }}</a></td>
<td class="right">{{ '{:,}'.format(prod.count) }}</td>
<td class="right">{{ '%.2f'|format(prod.avg_rating) if prod.avg_rating else '—' }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<h4 style="margin: 1rem 0 0.4rem; font-size: 0.95rem;">Distinctive language (over-indexed vs other brands)</h4>
<div class="phrases">
{% for ph in b.distinctive_phrases[:25] %}
<span class="phrase-pill"><b>{{ ph.phrase }}</b><span class="lift">{{ '%.1f'|format(ph.lift) }}× · {{ '{:,}'.format(ph.freq) }}</span></span>
{% endfor %}
</div>

{% if b.distinctive_phrases and b.distinctive_phrases[0].samples %}
<h4 style="margin: 1rem 0 0.4rem; font-size: 0.95rem;">Sample quotes from top distinctive phrases</h4>
{% for ph in b.distinctive_phrases[:3] %}
{% for s in ph.samples[:1] %}
<blockquote class="q">
<div class="meta"><b style="color: #{{ p.fg }};">"{{ ph.phrase }}"</b> · {{ s.author or 'Anonymous' }} · {{ s.handle }} · {{ s.rating|int }}★</div>
{{ s.body }}
</blockquote>
{% endfor %}
{% endfor %}
{% endif %}

{% if b.negative_distinctive_phrases %}
<h4 style="margin: 1rem 0 0.4rem; font-size: 0.95rem;">Distinctive language in low-rated reviews (≤3★)</h4>
<div class="phrases">
{% for ph in b.negative_distinctive_phrases[:15] %}
<span class="phrase-pill" style="background: #fef2f2; border-color: #fecaca;"><b>{{ ph.phrase }}</b><span class="lift">{{ '%.1f'|format(ph.lift) }}× · {{ '{:,}'.format(ph.freq) }}</span></span>
{% endfor %}
</div>
{% endif %}
</div>

{% endfor %}

<div class="footer">
Generated by <code>eca dashboard</code>. Theme labels are mechanical (top cluster phrases joined). For interpretation and naming, read this dashboard alongside <code>_aggregate.json</code> and propose human-readable theme names. Phrase distinctiveness uses smoothed lift on review-presence frequencies — not raw token counts. Sample quotes are filtered to mid-length (80–400 chars) for readability.
</div>

</body>
</html>
""")


def render(aggregate_path: Path, out_path: Path) -> None:
    data = json.loads(aggregate_path.read_text())
    domains: list[str] = data.get("global", {}).get("all_brands", [])
    if not domains:
        # Backwards-compat: infer from `brands` keys.
        domains = list(data.get("brands", {}).keys())

    palette = palette_for(domains)
    html_text = DASHBOARD_TEMPLATE.render(
        domains=domains,
        brands=data.get("brands", {}),
        themes=data.get("themes", []),
        total_reviews=data.get("global", {}).get("total_reviews", 0),
        palette=palette,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")

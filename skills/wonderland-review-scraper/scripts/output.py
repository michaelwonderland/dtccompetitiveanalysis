"""
Output: write per-product CSV and HTML, plus a top-level index.html summary.
"""
from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from jinja2 import Template

from .models import Review, CSV_FIELDS


PRODUCT_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Reviews — {{ handle }}</title>
<style>
:root { --fg:#1a1a1a; --muted:#6b7280; --border:#e5e7eb; --bg:#fff; --accent:#f59e0b; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 880px; margin: 2rem auto; padding: 0 1.5rem; color: var(--fg); background: var(--bg); }
h1 { margin-bottom: 0.25rem; }
.meta { color: var(--muted); margin-bottom: 2rem; font-size: 0.9rem; }
.summary { display: flex; gap: 2rem; padding: 1rem 1.25rem; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 2rem; flex-wrap: wrap; }
.summary .stat { display: flex; flex-direction: column; }
.summary .stat .label { color: var(--muted); font-size: 0.85rem; }
.summary .stat .value { font-size: 1.5rem; font-weight: 600; }
.review { padding: 1.25rem 0; border-top: 1px solid var(--border); }
.review:first-of-type { border-top: 0; }
.review-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }
.author { font-weight: 600; }
.date { color: var(--muted); font-size: 0.85rem; }
.stars { color: var(--accent); letter-spacing: 1px; }
.title { font-weight: 600; margin: 0.5rem 0 0.25rem; }
.body { white-space: pre-wrap; line-height: 1.55; }
.tag { display: inline-block; font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 99px; background: #ecfdf5; color: #065f46; margin-left: 0.5rem; }
a { color: #2563eb; }
</style>
</head>
<body>
<h1>{{ handle }}</h1>
<p class="meta"><a href="{{ product_url }}">{{ product_url }}</a></p>

<div class="summary">
  <div class="stat"><span class="label">Reviews</span><span class="value">{{ count }}</span></div>
  {% if avg_rating %}<div class="stat"><span class="label">Average rating</span><span class="value">{{ '%.2f' % avg_rating }} / 5</span></div>{% endif %}
  {% if rating_dist %}<div class="stat"><span class="label">Distribution</span><span class="value" style="font-size:0.95rem;font-weight:400;">
    {% for star in [5,4,3,2,1] %}{{ star }}★ {{ rating_dist.get(star, 0) }}&nbsp;&nbsp;{% endfor %}
  </span></div>{% endif %}
</div>

{% for r in reviews %}
<div class="review">
  <div class="review-head">
    <span>
      <span class="author">{{ r.author or 'Anonymous' }}</span>
      {% if r.verified %}<span class="tag">verified buyer</span>{% endif %}
    </span>
    <span class="date">{{ r.created_at or '' }}</span>
  </div>
  {% if r.rating %}<div class="stars">{{ '★' * (r.rating|int) }}{{ '☆' * (5 - (r.rating|int)) }}</div>{% endif %}
  {% if r.title %}<div class="title">{{ r.title }}</div>{% endif %}
  <div class="body">{{ r.body or '' }}</div>
</div>
{% endfor %}
</body>
</html>
""")


INDEX_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Review scrape — {{ domain }}</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1.5rem; color: #1a1a1a; }
h1 { margin-bottom: 0.25rem; }
.meta { color: #6b7280; margin-bottom: 2rem; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 0.6rem 0.75rem; text-align: left; border-bottom: 1px solid #e5e7eb; font-size: 0.95rem; }
th { background: #f9fafb; font-weight: 600; }
tr:hover { background: #fafafa; }
a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }
.muted { color: #6b7280; font-size: 0.85rem; }
.right { text-align: right; }
</style>
</head>
<body>
<h1>{{ domain }}</h1>
<p class="meta">{{ summary.total_products }} products scanned · {{ summary.products_with_reviews }} with reviews · {{ summary.total_reviews }} reviews collected</p>

<table>
  <thead>
    <tr>
      <th>Product</th>
      <th class="right">Reviews</th>
      <th class="right">Avg rating</th>
      <th>Files</th>
      <th>Source</th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr>
      <td><a href="{{ row.product_url }}" target="_blank">{{ row.handle }}</a></td>
      <td class="right">{{ row.count }}</td>
      <td class="right">{{ '%.2f' % row.avg if row.avg else '—' }}</td>
      <td>
        {% if row.html_path %}<a href="{{ row.html_path }}">html</a>{% endif %}
        {% if row.html_path and row.csv_path %} · {% endif %}
        {% if row.csv_path %}<a href="{{ row.csv_path }}">csv</a>{% endif %}
      </td>
      <td class="muted">{{ row.source or '' }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

</body>
</html>
""")


def write_csv(path: Path, reviews: Iterable[Review]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in reviews:
            row = r.to_row()
            for k, v in list(row.items()):
                if isinstance(v, str):
                    # Strip whitespace, normalize newlines
                    row[k] = v.strip()
            w.writerow(row)


def write_product_html(path: Path, product_url: str, handle: str, reviews: list[Review]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ratings = [r.rating for r in reviews if r.rating is not None]
    avg = sum(ratings) / len(ratings) if ratings else None
    dist = Counter(int(round(r)) for r in ratings) if ratings else {}
    html_text = PRODUCT_TEMPLATE.render(
        handle=handle,
        product_url=product_url,
        count=len(reviews),
        avg_rating=avg,
        rating_dist=dist,
        reviews=reviews,
    )
    path.write_text(html_text, encoding="utf-8")


def write_index_html(path: Path, domain: str, summary: dict, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = INDEX_TEMPLATE.render(domain=domain, summary=summary, rows=rows)
    path.write_text(text, encoding="utf-8")


def write_raw_json(path: Path, reviews: list[Review]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"normalized": r.to_row(), "raw": r.raw} for r in reviews]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

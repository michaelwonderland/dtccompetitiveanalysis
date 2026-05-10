"""
CLI entry point.

Subcommands:
  scrape     — pull reviews for one domain
  aggregate  — synthesize distinctive phrases + themes across N domains
  dashboard  — render cross-competitor HTML dashboard
  report     — render narrative HTML report
  pipeline   — scrape + aggregate + dashboard + report in one go
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click

from .crawler import crawl_products, product_handle
from .discovery import discover
from .extractor import Extractor, Scanner, make_http_client, resolve_product_id
from .dom_fallback import scrape_dom
from .output import write_csv, write_product_html, write_index_html, write_raw_json
from . import aggregate as aggregate_mod
from . import dashboard as dashboard_mod
from . import report as report_mod


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

CWD = Path.cwd()
OUTPUT_DIR = CWD / "output"
CACHE_DIR = CWD / "cache"


def _domain(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    netloc = urlparse(url).netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _cache_path(domain: str) -> Path:
    return CACHE_DIR / f"{domain}.json"


def _stderr(msg: str) -> None:
    click.echo(msg, err=True)


# =============================================================================
# scrape
# =============================================================================

@click.group()
@click.version_option(package_name="ecom-competitive-analysis")
def main() -> None:
    """ecom-competitive-analysis (eca) — scrape and synthesize ecommerce review data."""


@main.command("scrape")
@click.argument("site_url")
@click.option("--max-products", type=int, default=None, help="Cap number of products scanned")
@click.option("--top", "top_n", type=int, default=None, help="Scan all, then full-fetch only top N by count")
@click.option("--rediscover", is_flag=True, help="Force re-discovery of the review endpoint")
@click.option("--headed", is_flag=True, help="Show browser window during discovery")
@click.option("--sleep", "sleep_s", type=float, default=0.4, help="Delay between API requests, seconds")
@click.option("--save-raw", is_flag=True, help="Also save raw provider JSON per product")
@click.option("--dom-fallback", is_flag=True, help="Skip API path; scrape DOM only")
@click.option("--platform", type=click.Choice(["shopify", "generic"]), default=None,
              help="Force a platform adapter for product-id resolution")
def cmd_scrape(site_url: str, max_products: Optional[int], top_n: Optional[int],
               rediscover: bool, headed: bool, sleep_s: float, save_raw: bool,
               dom_fallback: bool, platform: Optional[str]) -> None:
    """Pull reviews for a single domain (e.g. example.com)."""
    domain = _domain(site_url)
    site_output = OUTPUT_DIR / domain
    site_output.mkdir(parents=True, exist_ok=True)

    _stderr(f"[1/4] Crawling product URLs for {domain}…")
    products = crawl_products(site_url, max_products=max_products)
    if not products:
        _stderr("  No product URLs found. Aborting.")
        sys.exit(1)
    _stderr(f"  Found {len(products)} products.")

    config: Optional[dict] = None
    cp = _cache_path(domain)
    if cp.exists() and not rediscover and not dom_fallback:
        config = json.loads(cp.read_text())
        _stderr(f"[2/4] Using cached config: {cp}")
    elif not dom_fallback:
        _stderr(f"[2/4] Discovering review endpoint via Playwright (using {products[0]})…")
        result = discover(products[0], headless=not headed)
        if not result.found:
            _stderr("  Discovery failed. Top candidates:")
            for c in result.top_candidates[:3]:
                _stderr(f"    score={c['score']} reasons={c['reasons']} url={c['url']}")
            _stderr("  Falling back to DOM scraping.")
            dom_fallback = True
        else:
            config = result.to_dict()
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(config, indent=2))
            _stderr(f"  Found endpoint:")
            _stderr(f"    {result.review_url_template}")
            _stderr(f"    pagination_param={result.pagination_param} size_param={result.page_size_param}")

    if dom_fallback:
        _scrape_dom_path(site_output, products, headed)
        return

    # Optional pre-scan to identify top N
    extractor = Extractor(config)
    product_pid_pairs: list[tuple[str, Optional[str]]]

    if top_n:
        _stderr(f"[2.5/4] Pre-scanning {len(products)} products to find top {top_n} by review count…")
        scanner = Scanner(extractor)
        client_scan = make_http_client()
        scan_rows: list[dict] = []
        try:
            for i, url in enumerate(products, 1):
                handle = product_handle(url)
                pid = resolve_product_id(client_scan, url, platform=platform) or (config.get("product_id") if i == 1 else None)
                if not pid:
                    scan_rows.append({"handle": handle, "product_url": url, "product_id": None, "count": None, "avg_rating": None})
                    continue
                count, avg = scanner.scan(client_scan, url, pid)
                scan_rows.append({"handle": handle, "product_url": url, "product_id": pid, "count": count, "avg_rating": avg})
                if i % 25 == 0 or i == len(products):
                    _stderr(f"  scanned {i}/{len(products)}")
        finally:
            client_scan.close()
        scan_path = site_output / "_scan.json"
        scan_path.write_text(json.dumps(scan_rows, indent=2))
        _stderr(f"  Scan saved to {scan_path}")
        ranked = sorted(scan_rows, key=lambda r: -(r["count"] or -1))
        top_products = [r for r in ranked if r["count"] is not None][:top_n]
        product_pid_pairs = [(r["product_url"], r["product_id"]) for r in top_products]
        _stderr(f"  Top {len(product_pid_pairs)} selected. Counts: " + ", ".join(str(r["count"]) for r in top_products))
    else:
        product_pid_pairs = [(url, None) for url in products]

    _stderr(f"[3/4] Extracting reviews from API for {len(product_pid_pairs)} products…")
    summary = {"total_products": len(product_pid_pairs), "products_with_reviews": 0, "total_reviews": 0}
    rows: list[dict] = []
    fallback_count = 0
    client = make_http_client()

    try:
        for i, (url, prefetched_pid) in enumerate(product_pid_pairs, 1):
            handle = product_handle(url)
            t0 = time.time()
            pid = prefetched_pid or resolve_product_id(client, url, platform=platform)
            if not pid and config.get("product_id") and i == 1:
                pid = config.get("product_id")

            reviews, meta, source = [], {}, "api"
            if pid:
                reviews, meta = extractor.fetch_reviews(client, url, pid, sleep_s=sleep_s)
            if not reviews:
                _stderr(f"  ({i}/{len(product_pid_pairs)}) {handle} — API yielded 0 reviews; trying DOM fallback…")
                try:
                    reviews = scrape_dom(url, headless=not headed)
                    source = "dom-fallback"
                    fallback_count += 1
                except Exception as e:
                    _stderr(f"    DOM fallback error: {e}")

            elapsed = time.time() - t0
            _stderr(f"  ({i}/{len(product_pid_pairs)}) {handle} — {len(reviews)} reviews "
                    f"(pages={meta.get('pages_fetched','-')}, total={meta.get('total_reported','?')}, "
                    f"src={source}, {elapsed:.1f}s)")

            if reviews:
                write_csv(site_output / f"{handle}.csv", reviews)
                write_product_html(site_output / f"{handle}.html", url, handle, reviews)
                if save_raw:
                    write_raw_json(site_output / "raw" / f"{handle}.json", reviews)
                summary["products_with_reviews"] += 1
                summary["total_reviews"] += len(reviews)

            avg = (sum(r.rating for r in reviews if r.rating) / max(1, sum(1 for r in reviews if r.rating))) if reviews else None
            rows.append({"handle": handle, "product_url": url, "count": len(reviews), "avg": avg,
                         "html_path": f"{handle}.html" if reviews else None,
                         "csv_path": f"{handle}.csv" if reviews else None, "source": source})
    finally:
        client.close()

    rows.sort(key=lambda r: r["count"], reverse=True)
    write_index_html(site_output / "index.html", domain, summary, rows)
    _stderr(f"\n[4/4] Done. {summary['total_reviews']} reviews across "
            f"{summary['products_with_reviews']}/{summary['total_products']} products. "
            f"Output: {site_output}")
    if fallback_count:
        _stderr(f"  Note: {fallback_count} product(s) used DOM fallback.")


def _scrape_dom_path(site_output: Path, products: list[str], headed: bool) -> None:
    _stderr("[3/4] Extracting reviews via DOM fallback…")
    summary = {"total_products": len(products), "products_with_reviews": 0, "total_reviews": 0}
    rows: list[dict] = []
    for i, url in enumerate(products, 1):
        handle = product_handle(url)
        try:
            reviews = scrape_dom(url, headless=not headed)
        except Exception as e:
            _stderr(f"  ({i}/{len(products)}) {handle} — error: {e}")
            reviews = []
        _stderr(f"  ({i}/{len(products)}) {handle} — {len(reviews)} reviews (DOM)")
        if reviews:
            write_csv(site_output / f"{handle}.csv", reviews)
            write_product_html(site_output / f"{handle}.html", url, handle, reviews)
            summary["products_with_reviews"] += 1
            summary["total_reviews"] += len(reviews)
        avg = (sum(r.rating for r in reviews if r.rating) / max(1, sum(1 for r in reviews if r.rating))) if reviews else None
        rows.append({"handle": handle, "product_url": url, "count": len(reviews), "avg": avg,
                     "html_path": f"{handle}.html" if reviews else None,
                     "csv_path": f"{handle}.csv" if reviews else None, "source": "dom"})
    rows.sort(key=lambda r: r["count"], reverse=True)
    write_index_html(site_output / "index.html", site_output.name, summary, rows)
    _stderr(f"\n[4/4] Done. Output: {site_output}")


# =============================================================================
# aggregate
# =============================================================================

@main.command("aggregate")
@click.argument("domains", nargs=-1, required=True)
@click.option("--out", "out_path", type=click.Path(), default=None, help="Output JSON path (default: output/_aggregate.json)")
@click.option("--top-per-brand", type=int, default=50, help="Distinctive phrases kept per brand")
@click.option("--theme-top", type=int, default=30, help="Phrases per brand fed into cross-brand clustering")
@click.option("--min-brand-freq", type=int, default=30, help="Minimum review-presence count for a phrase to be considered")
@click.option("--min-lift", type=float, default=1.5, help="Minimum lift over rest-of-corpus")
@click.option("--exclude-terms", default=None,
              help="Comma-separated tokens to exclude from analysis (e.g. brand or product-line names). "
                   "Domain-derived brand tokens are added automatically.")
def cmd_aggregate(domains: tuple[str, ...], out_path: Optional[str],
                  top_per_brand: int, theme_top: int, min_brand_freq: int, min_lift: float,
                  exclude_terms: Optional[str]) -> None:
    """Synthesize distinctive phrases + themes across N domains."""
    out = Path(out_path) if out_path else OUTPUT_DIR / "_aggregate.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    excl_set = set()
    if exclude_terms:
        excl_set = {t.strip().lower() for t in exclude_terms.split(",") if t.strip()}

    _stderr(f"Aggregating {len(domains)} domains: {', '.join(domains)}")
    data = aggregate_mod.aggregate(
        list(domains), OUTPUT_DIR,
        top_per_brand=top_per_brand, theme_top=theme_top,
        min_brand_freq=min_brand_freq, min_lift=min_lift,
        exclude_terms=excl_set,
    )
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    _stderr(f"Wrote {out}")
    for d in domains:
        b = data["brands"].get(d, {})
        n = b.get("review_count", 0)
        _stderr(f"  {d}: {n:,} reviews · {len(b.get('distinctive_phrases', []))} distinctive phrases")
    _stderr(f"  Cross-brand themes: {len(data.get('themes', []))}")


# =============================================================================
# dashboard
# =============================================================================

@main.command("dashboard")
@click.argument("domains", nargs=-1, required=False)
@click.option("--aggregate-path", type=click.Path(), default=None, help="Path to _aggregate.json (default: output/_aggregate.json)")
@click.option("--out", "out_path", type=click.Path(), default=None, help="Output HTML path (default: output/dashboard.html)")
def cmd_dashboard(domains: tuple[str, ...], aggregate_path: Optional[str], out_path: Optional[str]) -> None:
    """Render the cross-competitor dashboard HTML from _aggregate.json."""
    agg = Path(aggregate_path) if aggregate_path else OUTPUT_DIR / "_aggregate.json"
    if not agg.exists():
        _stderr(f"Missing {agg}. Run `eca aggregate <domain1> <domain2> …` first.")
        sys.exit(1)
    out = Path(out_path) if out_path else OUTPUT_DIR / "dashboard.html"
    dashboard_mod.render(agg, out)
    _stderr(f"Wrote {out}")


# =============================================================================
# report
# =============================================================================

@main.command("report")
@click.argument("domains", nargs=-1, required=False)
@click.option("--aggregate-path", type=click.Path(), default=None, help="Path to _aggregate.json")
@click.option("--out", "out_path", type=click.Path(), default=None, help="Output HTML path (default: output/report.html)")
def cmd_report(domains: tuple[str, ...], aggregate_path: Optional[str], out_path: Optional[str]) -> None:
    """Render the templated narrative report from _aggregate.json."""
    agg = Path(aggregate_path) if aggregate_path else OUTPUT_DIR / "_aggregate.json"
    if not agg.exists():
        _stderr(f"Missing {agg}. Run `eca aggregate <domain1> <domain2> …` first.")
        sys.exit(1)
    out = Path(out_path) if out_path else OUTPUT_DIR / "report.html"
    report_mod.render(agg, out)
    _stderr(f"Wrote {out}")


# =============================================================================
# pipeline
# =============================================================================

@main.command("pipeline")
@click.argument("domains", nargs=-1, required=True)
@click.option("--top", "top_n", type=int, default=10, help="Top-N products per domain to fully scrape")
@click.option("--platform", type=click.Choice(["shopify", "generic"]), default=None)
@click.option("--skip-scrape", is_flag=True, help="Reuse existing output/{domain}/ folders; only run aggregate+dashboard+report")
@click.pass_context
def cmd_pipeline(ctx, domains: tuple[str, ...], top_n: int, platform: Optional[str], skip_scrape: bool) -> None:
    """End-to-end: scrape each domain → aggregate → dashboard → report."""
    if not skip_scrape:
        for d in domains:
            _stderr(f"\n=== Scraping {d} ===")
            ctx.invoke(cmd_scrape, site_url=d, top_n=top_n, platform=platform,
                       max_products=None, rediscover=False, headed=False, sleep_s=0.4,
                       save_raw=False, dom_fallback=False)

    _stderr("\n=== Aggregating across all brands ===")
    ctx.invoke(cmd_aggregate, domains=domains, out_path=None,
               top_per_brand=50, theme_top=30, min_brand_freq=30, min_lift=1.5,
               exclude_terms=None)

    _stderr("\n=== Rendering dashboard ===")
    ctx.invoke(cmd_dashboard, domains=domains, aggregate_path=None, out_path=None)

    _stderr("\n=== Rendering report ===")
    ctx.invoke(cmd_report, domains=domains, aggregate_path=None, out_path=None)

    _stderr(f"\n✔ Pipeline complete. Outputs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

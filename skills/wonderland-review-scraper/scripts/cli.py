"""
CLI entry point for the wonderland-review-scraper skill.

Single command: scrape reviews from one ecommerce domain.

Usage:
    python -m scripts.cli <domain> [--top N] [--max-products N] [--rediscover]
    python -m scripts.cli example.com --top 10
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


@click.command()
@click.argument("site_url")
@click.option("--max-products", type=int, default=None,
              help="Cap number of products scanned (for testing)")
@click.option("--top", "top_n", type=int, default=None,
              help="Scan all products, then full-fetch only top N by review count")
@click.option("--rediscover", is_flag=True, help="Force re-discovery of the review endpoint")
@click.option("--headed", is_flag=True, help="Show the Playwright browser")
@click.option("--sleep", "sleep_s", type=float, default=0.4, help="Delay between API requests")
@click.option("--save-raw", is_flag=True, help="Also save raw provider JSON per product")
@click.option("--dom-fallback", is_flag=True, help="Skip API path; scrape DOM only")
@click.option("--platform", type=click.Choice(["shopify", "generic"]), default=None)
def main(site_url: str, max_products: Optional[int], top_n: Optional[int],
         rediscover: bool, headed: bool, sleep_s: float, save_raw: bool,
         dom_fallback: bool, platform: Optional[str]) -> None:
    """Scrape reviews from one ecommerce domain.

    Anti-bot policy: this CLI does not silently fall through to DOM scraping
    when an API call returns 403. It logs a clear ANTI-BOT DETECTED warning
    so the orchestrator (Claude reading the SKILL.md) can halt and ask the
    user how to proceed.
    """
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

    if dom_fallback:
        _scrape_dom_path(site_output, products, headed)
        return

    extractor = Extractor(config)
    product_pid_pairs: list[tuple[str, Optional[str]]]

    if top_n:
        _stderr(f"[2.5/4] Pre-scanning {len(products)} products to find top {top_n}…")
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
    blocked_403 = False
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
                if str(meta.get("stopped_reason", "")).startswith("status:403"):
                    blocked_403 = True
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
                    f"src={source}, stopped={meta.get('stopped_reason','-')}, {elapsed:.1f}s)")

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
    if blocked_403:
        _stderr(f"  ⚠ ANTI-BOT DETECTED: API returned 403 (Cloudflare/DataDome).")
        _stderr(f"  Halt and ask the user: ScrapingBee key, skip site, or DOM fallback?")
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


if __name__ == "__main__":
    main()

"""
DOM-based fallback extractor.

Used when API extraction fails (no clean API, anti-bot, etc.).
Loads the page in Playwright, expands all reviews, then scrapes the DOM.

Lossy compared to API path - only what's rendered is captured. Use for
sites without clean JSON APIs.
"""
from __future__ import annotations

import re
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

from .models import Review
from .crawler import product_handle


def _extract_rating_from_text(text: str) -> Optional[float]:
    m = re.search(r"(\d(?:\.\d)?)\s*(?:/|out of|of)\s*5", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


JS_EXPAND_AND_SCRAPE = r"""
async () => {
    // Try to click "load more" buttons up to N times
    const maxClicks = 30;
    const loadMoreSelectors = [
        'button:has-text("Load more")',
        'button:has-text("Show more")',
        'button:has-text("More reviews")',
        '[class*="load-more"]',
        '[class*="loadMore"]',
        '[class*="show-more"]',
    ];
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));

    for (let i = 0; i < maxClicks; i++) {
        let clicked = false;
        for (const sel of loadMoreSelectors) {
            const btns = document.querySelectorAll(sel);
            for (const b of btns) {
                if (b.offsetParent !== null) {
                    b.click();
                    clicked = true;
                    break;
                }
            }
            if (clicked) break;
        }
        if (!clicked) break;
        await sleep(1500);
    }

    // Strategy 1: schema.org Review microdata
    const microReviews = [];
    document.querySelectorAll('[itemtype*="Review" i], [itemtype$="/Review"]').forEach(el => {
        const get = (prop) => {
            const node = el.querySelector(`[itemprop="${prop}"]`);
            if (!node) return null;
            return node.getAttribute('content') || node.textContent?.trim() || null;
        };
        microReviews.push({
            author: get('author'),
            rating: get('ratingValue'),
            title: get('name'),
            body: get('reviewBody'),
            created_at: get('datePublished'),
        });
    });
    if (microReviews.length > 0) return { source: 'schema.org', reviews: microReviews };

    // Strategy 2: common provider class names
    const providerSelectors = [
        '.yotpo-review',
        '.jdgm-rev',
        '.stamped-review',
        '[class*="okendo-review"]',
        '.loox-review',
        '.junip-review',
        '[class*="reviews-io-review"]',
    ];
    for (const sel of providerSelectors) {
        const els = document.querySelectorAll(sel);
        if (els.length === 0) continue;
        const reviews = [];
        els.forEach(el => {
            const text = el.textContent || '';
            const author = el.querySelector('[class*="author"], [class*="reviewer"], [class*="name"]')?.textContent?.trim();
            const title = el.querySelector('[class*="title"], [class*="headline"]')?.textContent?.trim();
            const body = el.querySelector('[class*="content"], [class*="body"], [class*="text"]')?.textContent?.trim();
            const date = el.querySelector('[class*="date"], time')?.textContent?.trim();
            // Stars: count filled stars
            const starsFilled = el.querySelectorAll('[class*="star"][class*="full"], [class*="star"][class*="filled"], .icon-star').length;
            reviews.push({ author, title, body, created_at: date, rating: starsFilled || null, _full_text: text.slice(0, 800) });
        });
        return { source: sel, reviews };
    }

    // Strategy 3: anything with class containing 'review' that has multiple instances
    const generic = document.querySelectorAll('[class*="review-item"], [class*="reviewItem"], [class*="reviewCard"]');
    if (generic.length > 1) {
        const reviews = [];
        generic.forEach(el => {
            reviews.push({
                _full_text: (el.textContent || '').slice(0, 800),
                body: el.textContent?.trim(),
            });
        });
        return { source: 'generic-class', reviews };
    }

    return { source: 'none', reviews: [] };
}
"""


def scrape_dom(product_url: str, *, headless: bool = True) -> list[Review]:
    reviews: list[Review] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        except PWTimeoutError:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeoutError:
            pass

        # Scroll to bottom slowly
        try:
            page.evaluate("""
                async () => {
                    await new Promise(resolve => {
                        let total = 0;
                        const distance = 500;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            total += distance;
                            if (total >= document.body.scrollHeight + 2000) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 250);
                    });
                }
            """)
        except Exception:
            pass

        try:
            result = page.evaluate(JS_EXPAND_AND_SCRAPE)
        except Exception:
            result = {"reviews": []}

        browser.close()

    for r in result.get("reviews", []):
        rating = r.get("rating")
        try:
            rating_f = float(rating) if rating not in (None, "") else None
        except (ValueError, TypeError):
            rating_f = _extract_rating_from_text(r.get("_full_text", "") or "")
        reviews.append(Review(
            product_url=product_url,
            product_handle=product_handle(product_url),
            author=r.get("author"),
            rating=rating_f,
            title=r.get("title"),
            body=r.get("body"),
            created_at=r.get("created_at"),
            raw=r,
        ))
    return reviews

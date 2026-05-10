# Caveats and limitations

This document catalogs everything you should know before reading conclusions from this toolkit's output as if they were ground truth. The reviews are real; the synthesis is honest; but data has texture and you should respect it.

## On scraping legality and ethics

- **Public data is not the same as scrape-able-at-scale data.** Most review widgets serve their JSON publicly because the site's own front-end loads it that way. That doesn't grant blanket permission to scrape. Each site's ToS applies.
- **Rate limits exist for a reason.** The toolkit defaults to 0.4s between requests per product. Don't lower this without thinking about the site's load.
- **Anti-bot is a signal.** If a site returns 403/429, that's the operator telling you "no". The toolkit doesn't bypass these — see the README for what to do.

## On scraping completeness

- **Discovery can pick the wrong endpoint.** Some sites have multiple review-shaped JSON responses on the page (a recommender widget that includes ratings, for example). The heuristic scoring usually picks correctly but not always. If a brand's numbers look implausibly low or high, inspect `cache/{domain}.json`. Use `--rediscover` after deleting the cache file to retry.
- **The first run on a domain uses Playwright.** Subsequent runs use the cached config and are 10–100× faster. If a site changes its review provider, delete the cache.
- **The `--top N` mode requires an accurate scan.** For providers that expose `bottomline.totalReview` (Yotpo) the scan is exact. For providers without a total field (Okendo), the scan follows the cursor up to 20 pages and reports a lower bound — products with >2,000 reviews are bucketed together at "≥2,000" for ranking. The actual full-fetch will get the true count.
- **Some products are gated.** If a product is unpublished, region-locked, or behind a password, the scraper won't see it. The full-catalog scan only sees what `/sitemap.xml` exposes.

## On phrase synthesis (`aggregate`)

- **Regex/n-gram synthesis is shallow.** It captures recurring language; it does not capture sentiment polarity, sarcasm, negation, or context. *"I'm NOT a hot sleeper"* and *"I'm a hot sleeper"* both match a `hot sleeper` phrase. With 80,000+ reviews, false positives roughly cancel — but for any specific claim, **cross-check the sample quotes** before citing the phrase as evidence.
- **Stopwords are conservative.** The built-in stopword list keeps content words like `soft`, `warm`, `cool`, `quality` because they're meaningful in product reviews. It removes filler like `the`, `is`, `really`, `pretty`. If you're seeing phrases that feel too generic, tighten the stopword list in `eca/aggregate.py`.
- **Lift × frequency favors phrases that are both distinctive AND well-attested.** A phrase that's 50× over-indexed but appears in only 12 reviews ranks below one that's 3× over-indexed in 1,000 reviews. This is by design — small sample sizes lie. The `--min-brand-freq` flag controls the floor.
- **Theme clusters use review co-occurrence.** Two phrases are merged if they appear in the same review at a Jaccard similarity of ≥0.30. This catches obvious clusters ("cooling" + "breathable" + "bamboo") but misses phrases that mean the same thing but rarely co-occur ("quality" + "well-made" might end up in different clusters). Read clusters together; don't treat the clustering as definitive.
- **Theme labels are mechanical.** The toolkit joins the top three phrases of a cluster as the label. This is a placeholder. Read the cluster's phrases and quotes and rename it into something a human can actually use ("the wellness seeker", "the hot sleeper", "the gift giver").

## On sample quotes

- **Selection is biased toward mid-length, high-rated reviews** (80–400 chars, sorted by rating desc) for readability. This means quotes will skew positive even when the underlying phrase distribution is neutral. For low-rated context, look at `negative_distinctive_phrases` and the quotes attached there.
- **Verbatim quotes can include typos and informal language.** Don't clean them up — that misrepresents the source. If you're including a quote in client work, you can lightly trim/`[sic]` if needed but flag the edit.

## On comparing brands

- **Time on market is not controlled for.** A brand with 10× more reviews may be 10× as popular OR 5× as old. The data alone can't separate the two. Use other signals (founding date, traffic) to disambiguate when it matters.
- **Review-widget configuration affects volume.** Brand A may aggressively post-purchase email for reviews; Brand B may have lower opt-in. A "review volume" comparison is not a "sales volume" comparison — though the two are usually directionally correlated.
- **Quality perception at scale is real but noisy.** A brand with 30,000 reviews and 4.5 avg has earned that rating from a much wider sample than a brand with 3,000 reviews and 4.9. The averages are comparable, but the variance shrinks with scale; a 4.9 from 3,000 is more impressive than from 30, but less impressive than 4.7 from 30,000. State this carefully when you cite ratings.
- **Negative reviews are over-represented in the early days of a brand.** New brands tend to get more polarized reviews; mature brands regress to the mean. If one brand is much younger, weight this in.

## On output reproducibility

- **Each run scrapes fresh.** If you re-run today vs last week, new reviews will appear. The toolkit doesn't snapshot — re-running gives you "as of now". For longitudinal work, archive the `output/` folder per run with a date.
- **Discovery results are cached but data is not.** Cached `cache/{domain}.json` only stores the *endpoint URL template*. The actual reviews are pulled fresh every run.
- **Aggregation is deterministic given the same input.** Same CSVs in → same `_aggregate.json` out. Tokenization and clustering use no randomness.

## On strategic interpretation

- **The toolkit does not think strategically. You do (or Claude does, in a session).** The phrase clusters are evidence; the *meaning* is interpretation. Don't paste raw aggregate output into a deck and call it analysis — that produces noise.
- **Recommendations are easy to overfit.** It is tempting to read every distinctive phrase as a "strategic gap". Be ruthless about which ones matter for the brand's actual situation. Often only 2–3 themes are decision-grade; the rest are interesting but tangential.
- **Causation is not in the data.** "Brand X over-indexes on phrase Y" tells you what their customers say. It does not tell you whether Y is *why* customers chose them, *what* they actually want, or *whether* Brand X should double down on Y. The data narrows the question; it doesn't answer it.

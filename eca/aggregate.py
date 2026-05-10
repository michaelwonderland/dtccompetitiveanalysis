"""
Cross-brand review-corpus synthesis.

Given the per-product CSVs produced by `eca scrape`, this module:

  1. Loads all review text per brand.
  2. Tokenizes into 1-3 grams (filtered against a built-in stopword list).
  3. Computes distinctive phrases per brand (over-represented vs the rest of
     the corpus) using smoothed lift.
  4. Clusters co-occurring distinctive phrases into candidate "themes" using
     simple Jaccard-similarity union-find on review-membership sets.
  5. Attaches sample quotes per phrase and per theme.

The toolkit deliberately does NOT name themes. Top phrases per cluster are
surfaced; Claude (or you) labels them in interpretation.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path.cwd()


# -----------------------------------------------------------------------------
# Stopwords — concise English list. Keep words like "soft", "warm", "cool"
# OUT of stopwords (they're meaningful in product reviews).
# -----------------------------------------------------------------------------

STOPWORDS = set("""
a about above after again against all am an and any are aren as at be because
been before being below between both but by can cannot could couldn did didn
do does doesn doing don down during each few for from further had hadn has
hasn have haven having he her here hers herself him himself his how i if in
into is isn it its itself just like ll me might more most mustn my myself no
nor not now of off on once only or other our ours ourselves out over own re
same shan she should shouldn so some such than that the their theirs them
themselves then there these they this those through to too under until up
ve very was wasn we were weren what when where which while who whom why will
with won would wouldn you your yours yourself yourselves get got going
also even another way thing things even though although still really
quite pretty kind sort little bit much many lot lots ever never always
something anything everything nothing one two three four five six seven eight
nine ten first second next last new old big small large get got know know
think feel went going come came see sees seen look looks looking
make makes made made try tries tried use uses used using need needs needed
want wants wanted give gives gave taken take takes took tell told just
gonna wanna got gotten doesnt didnt isnt arent wasnt werent dont wont
ya yeah yep yes yup nope wow oh ok okay aw ahh ahem hi hello bye
its their theyre theyll im ive id youre youll youve hes shes were weve
say says said tell tells thanks thank thanks thanks please everything
much same etc thats whats whos whose although however
day days week weeks month months year years time times moment moments
left right inside outside front back top bottom side sides
review reviews item items product products order orders
nice good great love loved loving wonderful amazing awesome excellent perfect
fantastic best worst better worse okay alright fine cool decent superb
glad happy thrilled pleased disappointed dissatisfied satisfied unsatisfied
recommend recommended recommending recommends purchased purchase buy buying
bought ordering ordered shipping shipped received receiving delivery delivered
absolutely actually basically certainly definitely especially generally
honestly literally probably really seriously simply totally truly usually
""".split())


# -----------------------------------------------------------------------------
# Tokenization and n-gram extraction
# -----------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z]+")


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "") if len(w) >= 3]


def ngrams_for_text(text: str, max_n: int = 3,
                    exclude_terms: Optional[set[str]] = None) -> set[str]:
    """Return the SET of n-grams (1..max_n) present in `text`.

    Filters:
      - n-grams composed entirely of stopwords
      - n-grams whose only non-stopword tokens are all in `exclude_terms`
        (used to suppress brand names and SKU words from analysis)

    Returns a set so a phrase appearing twice in one review counts as 1
    (presence-based — review-level frequency, not token frequency).
    """
    tokens = tokenize(text)
    out: set[str] = set()
    n_tokens = len(tokens)
    excl = exclude_terms or set()
    for n in range(1, max_n + 1):
        for i in range(n_tokens - n + 1):
            gram_tokens = tokens[i:i + n]
            non_stop = [t for t in gram_tokens if t not in STOPWORDS]
            if not non_stop:
                continue
            if excl and all(t in excl for t in non_stop):
                continue
            out.add(" ".join(gram_tokens))
    return out


def derive_brand_terms(domain: str) -> set[str]:
    """Best-effort: extract brand-name tokens from a domain.

    Splits on non-alpha — works for hyphenated/underscored domains
    (e.g. 'sunday-citizen.co' -> {'sunday', 'citizen'}). For monolithic
    domains like 'sundaycitizen.co' it returns a single token; users
    should pass --exclude-terms to add the split version.
    """
    parts = domain.split(".")
    name = ".".join(parts[:-1]) if len(parts) > 1 else domain
    raw = set(re.findall(r"[a-z]+", name.lower()))
    raw -= {"www", "shop", "store", "us", "uk", "eu"}
    return raw


# -----------------------------------------------------------------------------
# Loading reviews from per-product CSVs
# -----------------------------------------------------------------------------

def load_reviews(output_root: Path, domain: str) -> tuple[list[dict], list[dict]]:
    """Return (reviews, products) for one domain.

    Each review dict mirrors the CSV columns. The products list summarizes
    each per-product CSV (count, avg rating, handle).
    """
    site_dir = output_root / domain
    if not site_dir.exists():
        return [], []
    reviews: list[dict] = []
    products: list[dict] = []
    for csv_path in sorted(site_dir.glob("*.csv")):
        if csv_path.name.startswith("_"):
            continue
        rows: list[dict] = []
        with csv_path.open() as f:
            for row in csv.DictReader(f):
                rows.append(row)
        ratings = []
        for r in rows:
            try:
                if r.get("rating"):
                    ratings.append(float(r["rating"]))
            except ValueError:
                pass
        avg = sum(ratings) / len(ratings) if ratings else None
        products.append({
            "handle": csv_path.stem,
            "count": len(rows),
            "avg_rating": avg,
            "product_url": rows[0].get("product_url") if rows else f"https://{domain}/products/{csv_path.stem}",
        })
        reviews.extend(rows)
    return reviews, products


def _safe_rating(r: dict) -> float:
    try:
        return float(r.get("rating") or 0)
    except (ValueError, TypeError):
        return 0


# -----------------------------------------------------------------------------
# Phrase frequency (review-level / presence-based)
# -----------------------------------------------------------------------------

def compute_phrase_freq(reviews: list[dict], max_n: int = 3,
                        exclude_terms: Optional[set[str]] = None
                        ) -> tuple[Counter, list[set[str]]]:
    """Return (counter, per-review phrase sets).
    The per-review sets are kept around so we can later compute co-occurrence
    without re-tokenizing.
    """
    freq: Counter = Counter()
    per_review: list[set[str]] = []
    for r in reviews:
        text = (r.get("title") or "") + " " + (r.get("body") or "")
        present = ngrams_for_text(text, max_n=max_n, exclude_terms=exclude_terms)
        per_review.append(present)
        for p in present:
            freq[p] += 1
    return freq, per_review


# -----------------------------------------------------------------------------
# Distinctiveness scoring
# -----------------------------------------------------------------------------

def distinctive_phrases(brand_freq: Counter, brand_total: int,
                        rest_freq: Counter, rest_total: int,
                        min_brand_freq: int = 30,
                        min_lift: float = 1.5,
                        smooth: int = 1) -> list[dict]:
    """Phrases over-represented in `brand_freq` vs `rest_freq`, ranked by
    lift * sqrt(freq) (balances distinctiveness with statistical magnitude).
    """
    out: list[dict] = []
    for phrase, fb in brand_freq.items():
        if fb < min_brand_freq:
            continue
        fr = rest_freq.get(phrase, 0)
        rate_brand = (fb + smooth) / (brand_total + smooth)
        rate_rest = (fr + smooth) / (rest_total + smooth)
        if rate_rest <= 0:
            continue
        lift = rate_brand / rate_rest
        if lift < min_lift:
            continue
        score = lift * (fb ** 0.5)
        out.append({
            "phrase": phrase,
            "freq": fb,
            "rate_pct": round(rate_brand * 100, 2),
            "lift": round(lift, 2),
            "score": round(score, 2),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# -----------------------------------------------------------------------------
# Sample quotes
# -----------------------------------------------------------------------------

def sample_quotes_for_phrase(reviews: list[dict], per_review_phrases: list[set[str]],
                             phrase: str, n: int = 2,
                             min_chars: int = 80, max_chars: int = 400,
                             min_rating: float = 0) -> list[dict]:
    """Pick `n` representative reviews containing `phrase`. Prefer high-rated,
    in-bounds-length reviews. Dedupe by the first ~5 words of body.
    """
    candidates: list[tuple[float, dict]] = []
    seen_sigs: set[str] = set()
    for r, present in zip(reviews, per_review_phrases):
        if phrase not in present:
            continue
        body = (r.get("body") or "").strip()
        if not (min_chars <= len(body) <= max_chars):
            continue
        rating = _safe_rating(r)
        if rating < min_rating:
            continue
        sig = " ".join(body.split()[:5]).lower()
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        candidates.append((rating, r))

    candidates.sort(key=lambda c: -c[0])
    out: list[dict] = []
    for rating, r in candidates[:n]:
        body = (r.get("body") or "").strip()
        if len(body) > max_chars:
            body = body[:max_chars].rsplit(" ", 1)[0] + "…"
        out.append({
            "author": (r.get("author") or "").strip() or None,
            "rating": rating,
            "title": (r.get("title") or "").strip() or None,
            "body": body,
            "handle": r.get("product_handle"),
        })
    return out


# -----------------------------------------------------------------------------
# Theme clustering (co-occurrence Jaccard + union-find)
# -----------------------------------------------------------------------------

def cluster_phrases(top_phrases: list[str],
                    per_review_phrase_sets: list[set[str]],
                    jaccard_threshold: float = 0.30,
                    min_phrase_reviews: int = 20) -> list[list[str]]:
    """Cluster phrases that frequently co-occur in the same review.

    Two phrases A and B are merged if Jaccard(reviews(A), reviews(B)) >= threshold.
    Single-phrase clusters are kept (they're valid themes).
    """
    # Phrase -> set of review indices it appears in
    phrase_reviews: dict[str, set[int]] = {p: set() for p in top_phrases}
    for i, present in enumerate(per_review_phrase_sets):
        for p in top_phrases:
            if p in present:
                phrase_reviews[p].add(i)

    # Filter phrases that appear in too few reviews to cluster reliably
    phrases = [p for p in top_phrases if len(phrase_reviews[p]) >= min_phrase_reviews]

    parent = {p: p for p in phrases}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, p1 in enumerate(phrases):
        s1 = phrase_reviews[p1]
        for p2 in phrases[i + 1:]:
            s2 = phrase_reviews[p2]
            denom = len(s1 | s2)
            if denom == 0:
                continue
            jac = len(s1 & s2) / denom
            if jac >= jaccard_threshold:
                union(p1, p2)

    clusters: dict[str, list[str]] = defaultdict(list)
    for p in phrases:
        clusters[find(p)].append(p)
    return list(clusters.values())


# -----------------------------------------------------------------------------
# Top-level aggregation
# -----------------------------------------------------------------------------

def aggregate(domains: list[str], output_root: Path,
              top_per_brand: int = 50, theme_top: int = 30,
              max_n: int = 3, min_brand_freq: int = 30,
              min_lift: float = 1.5,
              exclude_terms: Optional[set[str]] = None) -> dict:
    """Run the full corpus synthesis. Returns the JSON-serializable result.

    `exclude_terms` is a set of single-token brand/SKU words to drop. The
    function auto-augments it with each domain's derived brand tokens so
    monolithic brand n-grams don't dominate distinctive-phrase rankings.
    """

    # Auto-augment exclude_terms with per-domain brand tokens
    excl: set[str] = set(exclude_terms or set())
    for d in domains:
        excl |= derive_brand_terms(d)

    brand_reviews: dict[str, list[dict]] = {}
    brand_products: dict[str, list[dict]] = {}
    brand_per_review: dict[str, list[set[str]]] = {}
    brand_freq: dict[str, Counter] = {}

    for d in domains:
        reviews, products = load_reviews(output_root, d)
        brand_reviews[d] = reviews
        brand_products[d] = products
        freq, per_review = compute_phrase_freq(reviews, max_n=max_n, exclude_terms=excl)
        brand_freq[d] = freq
        brand_per_review[d] = per_review

    # Per-brand block
    brands_out: dict[str, dict] = {}
    for d in domains:
        reviews = brand_reviews[d]
        if not reviews:
            brands_out[d] = {"review_count": 0, "products": [], "distinctive_phrases": []}
            continue

        ratings = [_safe_rating(r) for r in reviews if _safe_rating(r) > 0]
        avg = sum(ratings) / len(ratings) if ratings else None
        dist = Counter(int(round(r)) for r in ratings)
        low_rated = [(r, present) for r, present in zip(reviews, brand_per_review[d]) if _safe_rating(r) <= 3]

        # Rest of corpus
        rest_freq: Counter = Counter()
        rest_total = 0
        for d2 in domains:
            if d2 == d:
                continue
            rest_total += len(brand_reviews[d2])
            for p, n in brand_freq[d2].items():
                rest_freq[p] += n

        # Distinctive (positive-side: full corpus)
        distinct = distinctive_phrases(brand_freq[d], len(reviews), rest_freq, rest_total,
                                       min_brand_freq=min_brand_freq, min_lift=min_lift)
        for p in distinct[:top_per_brand]:
            p["samples"] = sample_quotes_for_phrase(reviews, brand_per_review[d], p["phrase"], n=2)

        # Distinctive (negative-side: only ≤3-star reviews)
        if low_rated:
            low_reviews = [lr[0] for lr in low_rated]
            low_present = [lr[1] for lr in low_rated]
            low_freq: Counter = Counter()
            for present in low_present:
                for p in present:
                    low_freq[p] += 1
            # vs ALL reviews of OTHER brands
            neg_distinct = distinctive_phrases(
                low_freq, len(low_reviews), rest_freq, rest_total,
                min_brand_freq=max(10, min_brand_freq // 3), min_lift=min_lift,
            )
            for p in neg_distinct[:top_per_brand // 2]:
                p["samples"] = sample_quotes_for_phrase(low_reviews, low_present, p["phrase"], n=2)
        else:
            neg_distinct = []

        brands_out[d] = {
            "review_count": len(reviews),
            "avg_rating": round(avg, 3) if avg else None,
            "rating_distribution": {str(k): v for k, v in sorted(dist.items())},
            "low_rated_count": len(low_rated),
            "products": sorted(brand_products[d], key=lambda p: -p["count"]),
            "distinctive_phrases": distinct[:top_per_brand],
            "negative_distinctive_phrases": neg_distinct[:top_per_brand // 2],
        }

    # Cross-brand themes — cluster top distinctive phrases across all brands
    theme_phrases: list[str] = []
    seen: set[str] = set()
    for d in domains:
        for p in brands_out[d].get("distinctive_phrases", [])[:theme_top]:
            if p["phrase"] not in seen:
                seen.add(p["phrase"])
                theme_phrases.append(p["phrase"])

    # Build a unified per-review phrase set across all brands (with brand attribution)
    all_per_review_with_brand: list[tuple[set[str], str, dict]] = []
    for d in domains:
        for present, r in zip(brand_per_review[d], brand_reviews[d]):
            all_per_review_with_brand.append((present, d, r))

    # Cluster using unified review-presence
    unified_per_review = [t[0] for t in all_per_review_with_brand]
    clusters = cluster_phrases(theme_phrases, unified_per_review,
                               jaccard_threshold=0.30, min_phrase_reviews=20)

    # For each cluster, compute brand share + sample quotes
    themes_out: list[dict] = []
    for cluster in clusters:
        # Top phrases by total brand-aggregate frequency
        cluster_sorted = sorted(cluster, key=lambda p: -sum(brand_freq[d].get(p, 0) for d in domains))
        # Per-brand share = (reviews mentioning ANY phrase in cluster) / reviews-of-that-brand
        share: dict[str, float] = {}
        cluster_set = set(cluster)
        for d in domains:
            n_reviews = len(brand_reviews[d])
            if not n_reviews:
                share[d] = 0.0
                continue
            n_match = sum(1 for present in brand_per_review[d] if present & cluster_set)
            share[d] = round(n_match / n_reviews * 100, 2)

        dominant = max(share, key=share.get) if share else None
        # Pull samples from the dominant brand
        samples: list[dict] = []
        if dominant:
            for p in cluster_sorted[:3]:
                qs = sample_quotes_for_phrase(brand_reviews[dominant], brand_per_review[dominant], p, n=1)
                samples.extend(qs)
        # Mechanical label = top 3 cluster phrases joined
        label = " · ".join(cluster_sorted[:3])
        themes_out.append({
            "label": label,
            "phrases": cluster_sorted,
            "brand_share_pct": share,
            "dominant_brand": dominant,
            "review_count_in_dominant": int(round((share.get(dominant, 0) / 100) * len(brand_reviews.get(dominant, [])))) if dominant else 0,
            "samples": samples[:3],
        })

    # Sort themes by spread — biggest dominant share first
    themes_out.sort(key=lambda t: -max(t["brand_share_pct"].values()) if t["brand_share_pct"] else 0)

    return {
        "brands": brands_out,
        "themes": themes_out,
        "global": {
            "all_brands": domains,
            "total_reviews": sum(len(rs) for rs in brand_reviews.values()),
            "exclude_terms": sorted(excl),
        },
    }

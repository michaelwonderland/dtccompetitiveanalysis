# Prompt: full competitive analysis

Use this when the user wants a complete competitive analysis across N domains, focused on gaps and strategic recommendations.

## What to do

1. **Run the pipeline** for the given domains:
   ```bash
   eca pipeline <domain1> <domain2> ... --top 10
   ```
   This produces `output/{domain}/...`, `output/_aggregate.json`, `output/dashboard.html`, and `output/report.html`.

2. **Read `output/_aggregate.json`** as your primary source. Specifically:
   - `brands[domain].review_count` — volume comparison
   - `brands[domain].avg_rating` and `low_rated_count` — quality at scale comparison
   - `brands[domain].products[:10]` — what each brand is leading with
   - `brands[domain].distinctive_phrases` — language each brand over-indexes on
   - `brands[domain].negative_distinctive_phrases` — what each brand gets criticized for
   - `themes` — corpus-level clusters of co-occurring distinctive phrases

3. **Synthesize and label**. The toolkit produces themes labeled mechanically (top phrases joined). Read each cluster's phrases and sample quotes; rename themes into customer personas, product attributes, or marketing-language buckets — whichever describes the cluster best.

4. **Write the analysis** with these sections, in this order:
   - **Headline finding** — one or two sentences. Don't bury the lead.
   - **The volume / quality picture** — what the raw numbers say.
   - **Themes that emerged** — pick the 4–6 most strategically meaningful clusters. For each: which brand dominates, what the quotes show, what it means.
   - **Each competitor's distinctive language** — what does each brand uniquely "own"? Cite top distinctive phrases with their lift values.
   - **What each brand gets criticized for** — pull from `negative_distinctive_phrases`. This is gold for finding gaps.
   - **Strategic gaps** — for the brand the user is focused on (often the smallest, or the one they're consulting for): where is it under-served? Where is a competitor solving a problem it isn't?
   - **Recommended moves** — specific, evidence-backed. Each recommendation should cite a phrase, sample quote, or volume comparison.

5. **Be honest about limitations**:
   - Phrase lift × frequency surfaces signal, not certainty.
   - Sample quotes should be cross-checked against the phrase before you cite them as evidence — regex matching is shallow.
   - When making claims, prefer concrete numbers ("Brand X has 12× the rate of Y") over abstract ones ("Brand X tends to focus on Y").

## What to avoid

- Don't oversell what the smaller brand "does well" if the data doesn't support it. The user usually knows where the gaps are; they want them sharpened.
- Don't invent personas the data doesn't support. If the corpus doesn't show distinctive language for a "hot sleeper" in this category, don't write about hot sleepers.
- Don't lean on hardcoded category vocabulary ("for hot sleepers", "weighted blanket users"). Let the corpus name the themes.

## Output format

By default, write the analysis directly into the conversation. Optionally also rewrite `output/report.html` — the placeholder section in the rendered report (yellow callout in the "Themes that emerged" section) is intended for your synthesis paragraphs.

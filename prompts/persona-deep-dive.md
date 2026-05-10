# Prompt: persona deep-dive

Use this when the user wants to understand which customer personas each competitor best serves, derived from review language.

## What to do

1. **Run aggregate if not already**:
   ```bash
   eca aggregate <domain1> <domain2> ...
   ```

2. **Read `output/_aggregate.json` themes section**. Each theme is a cluster of distinctive phrases. Some themes will represent customer personas; others will represent product attributes or marketing language. Your job is to triage:

   - **Persona-flavored**: phrases describing *who the customer is* or *what they're trying to solve* (e.g. "anxiety", "weighted", "hot sleeper", "for my mom", "gift").
   - **Product-attribute-flavored**: phrases describing what the product *is* (e.g. "soft", "cooling", "luxurious", "durable").
   - **Marketing-language**: phrases describing *vibe* (e.g. "amazing", "obsessed", "5 stars").

3. **For each persona-flavored theme**, write a short profile:
   - Persona name (your call — give it a human-readable label like "the gift giver" or "the anxious sleeper").
   - Profile — 1–2 sentences describing who this is and what they want.
   - Brand share — which brand wins this persona, by what margin? Cite the brand-share percentages from the theme.
   - Evidence — quote 2–3 of the cluster's top phrases, with their lift values.
   - Quote — pull one sample review from the dominant brand that exemplifies the persona.
   - Implication — what does it mean strategically that brand X owns this persona vs Y?

4. **Cross-reference with negative themes**. Look at `negative_distinctive_phrases` for each brand. If a brand over-indexes negatively on a phrase that appears positively for another brand (e.g., "too hot" in low-rated reviews of Brand A vs "cooling" in Brand B's distinctive phrases), that's a persona Brand A is actively *failing* to serve.

5. **Be specific about WHO and WHY**. "Hot sleepers prefer Brand B" is weaker than "Hot sleepers prefer Brand B because their bamboo viscose is positioned as 'cooling without sacrificing softness' — Brand A's 'snug' / 'cozy' / 'warm' lexicon excludes this audience".

## What to avoid

- Don't force a persona where the data doesn't show one. If a theme is just product-attribute language ("soft", "good quality"), don't label it as a persona.
- Don't claim personas without evidence quotes. Every persona should be backed by 2+ distinctive phrases AND at least one verbatim quote.
- Don't generalize across themes. Each persona deserves its own short profile.

## Output format

Write directly into the conversation. Optionally update `output/report.html` if the user wants a shareable artifact.

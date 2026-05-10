# Prompt: category mix and product strategy

Use this when the user wants to understand each competitor's product strategy by looking at WHICH products they lead with — not just what people say about them.

## What to do

1. **Read `output/_aggregate.json` per-brand `products` array**. The toolkit lists each brand's products sorted by review count (which is a proxy for sales volume). The top 5–10 products per brand are the brand's *de facto* hero SKUs — the ones their customer base is buying.

2. **Categorize the products** in your head. There's no taxonomy in the toolkit; you read the product handles and group them. For each brand:
   - What single category dominates the top 10 by review volume?
   - What's the spread? Is it heavily concentrated in 1–2 categories (hero-driven) or balanced (diversified)?
   - Are any categories conspicuously absent? (E.g., Brand A's top 10 has no sheets — interesting if Brand B's top 10 is 60% sheets.)

3. **Compute a "category share of voice"**. For each brand × category bucket: number of products and total review count. The most-reviewed category is where the brand has the most pull.

4. **Write the analysis** with:
   - **What each brand leads with** — one sentence per brand summarizing the category dominance.
   - **Where they overlap** — categories that appear in 2+ brands' top 10. For these, who wins on volume? On rating?
   - **Where they don't overlap** — categories one brand dominates and others ignore. Either a strategic moat or a strategic gap, depending on which brand is the focus.
   - **Hero-SKU concentration** — if a brand's #1 product is 2× or more its #2, flag it as hero-dependent. That's both a strength (clear winner) and a risk (concentration).

5. **Cross-check with the themes section**. Sometimes a category bias and a theme bias align (e.g. brand dominates in cooling-oriented language AND their top products are sheets/sleepwear). When they do, the brand has a coherent positioning. When they don't, it's worth flagging.

## What to avoid

- Don't fabricate a taxonomy. Use product names as they are; don't shoehorn them into MECE categories that distort the data.
- Don't over-weight low-volume products. A product with 50 reviews vs another with 5,000 isn't "second place" — it's a different game.
- Don't read causation into correlation. A brand having lots of pillow reviews doesn't mean they're "winning pillows" — they may simply have collected reviews longer.

## Output format

Write directly into the conversation. A simple comparison table works well — categories down the left, brands across the top, cells show "N products / X,XXX reviews".

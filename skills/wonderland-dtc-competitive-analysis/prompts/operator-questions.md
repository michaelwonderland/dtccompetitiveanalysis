# Operator questions to surface to the user

After the pipeline completes (scrape → aggregate → dashboard → report), the skill produces a fully populated `output/_aggregate.json` and rendered HTML. At that point, **stop and surface this menu** to the user.

Format the message exactly like this — the menu plus a one-line opinion (drawn from the corpus) on which question seems most actionable given what the data showed:

---

The competitive corpus is loaded. Six strategic questions an expert ecom operator would ask next — pick one (or multiple) and I'll dig in:

**01.** *How does each brand's top-5 product mix differ — hero-SKU-dependent vs balanced, premium vs entry, single-category vs cross-category? That's their strategic bet, made visible by what their customers actually buy.*

**02.** *Which customer persona is captured better by the competition than by you? The persona competitors over-serve is usually a category gap they figured out before you did — and the persona no brand serves well is whitespace.*

**03.** *Does any competitor sustain high review volume without quality erosion? The brand with both high volume AND low complaint rate is the operationally hardest one to compete with — figure out why before scaling head-on.*

**04.** *How concentrated is each competitor's review volume in their #1 SKU? A brand whose hero pulls 25%+ of top-10 review volume is hero-dependent — both a risk for them and a moat to be aware of for you.*

**05.** *What complaint pattern is unique to each competitor's low-rated reviews? Where they overlap with your own product weaknesses → fix you. Where they're absent from your reviews → that's a gap you can exploit publicly.*

**06.** *Which language themes are present in one competitor's reviews and wholly absent in another's? Absent themes are positioning whitespace — no brand is clearly serving that customer need yet.*

---

**My take from the data:** [insert one specific observation drawn from `_aggregate.json` — e.g., "Question 4 looks most interesting here: Brand B's `bath-mat` SKU pulls 38% of their top-10 review volume — that's a 2× concentration vs the others." Always cite specific numbers/phrases from the actual aggregate output, not generic placeholders.]

Which question(s) do you want me to dig into?

---

## Implementation notes for the orchestrator

- **Always cite specifics**, not generalities. The user has the data; vague observations ("Brand X has interesting patterns") are AI slop. Pull a specific number or phrase from the aggregate output.
- **Don't auto-answer** more than one question on your own initiative. Wait for the user to direct.
- **If the user picks a question**, dig in by reading the relevant fields of `_aggregate.json` (distinctive_phrases, themes, negative_distinctive_phrases) and the per-product CSVs. Cite quotes verbatim where useful.
- **If the user has a different question** entirely, answer that one — the menu is a starting point, not a constraint.

## What to suggest if they're stuck

If the user says "I don't know, what would you recommend?" — pick the question your one-line opinion was about and run with it. Show your work.

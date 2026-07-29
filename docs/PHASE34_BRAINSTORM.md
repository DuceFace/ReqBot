# Phase 34 Brainstorm — Actionability Fix Options

**Status:** Brainstorm / discussion draft — **not** a locked phase doc yet. This intentionally
carries more "why" narrative than a normal phase doc would (see
`~/reqbot-agent-docs/reqbot/references/work-package-workflow.md` for the normal format) — the goal
here is to react to and refine the approach before it gets locked into WP scope, success criteria,
and guardrails.

**Source:** WP-33.3's spike (`docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings, PR #156). This
doc assumes that write-up as background; the recap below is short on purpose.

---

## 1. The problem, briefly

WP-33.3 hand-labeled a random sample of the (small — 2 documents, 173 records) live corpus and
found 37.5% of requirements show some form of "cannot be trusted/verified as extracted." That
decomposes into five distinct failure modes, not one "too vague" problem:

| # | Failure mode | Size (of 40) | Danger |
|---|---|---|---|
| 1 | Reference/bibliography-list entries extracted as requirements, often with a fabricated `description` | 7 (17.5%) | High volume, but usually recognizable |
| 2 | Genuine vagueness/administrative meta-statements ("comply with X policy") | 5 (12.5%) | Real but least tractable |
| 3 | Truncated list-header fragments (`"The MC4EB will:"`) with a **fabricated** `description` completing them | 1 (2.5%) | **Most dangerous** — confident-reading, invented content |
| 4 | Background/definitional prose extracted despite no obligation language | 1 (2.5%) | Low |
| 5 | Form/questionnaire content mis-extracted as an obligation | 1 (2.5%) | Low, rare |

We also live-tested whether stricter Step C prompt wording alone fixes this. It doesn't, reliably —
categories 1 and 3 never fully closed across two independent test runs, and the revised (longer)
prompt reproducibly made the model regurgitate its own few-shot examples verbatim on a chunk that
normally extracts cleanly (identical fabricated text, twice). Prompt-only fixes are off the table for
categories 1 and 3; WP-32.1's existing Step D grounding check already happens to catch the
regurgitation failure mode as a side effect, which is reassuring but not something to lean on as a
plan.

**Why this matters enough to fix:** ReqBot's whole value proposition is "verbatim, trustworthy
extraction — ingestion captures verbatim, never invents obligations" (`REQBOT_SKILL.md`'s own core
architecture principle). Category 3 in particular is a direct violation of that principle already in
production: a record that *reads* like a complete, sourced requirement but whose obligation content
was invented by Step D.5, not the source document. That's the one I'd weight most heavily regardless
of its small sample count.

---

## 2. Candidate fixes, per category — open questions, not decisions

### Category 3 — fragment quotes with fabricated completions (recommend: fix first)

**Idea:** a structural rejection check in Step D's existing per-requirement validation loop
(`pipeline/parse_and_normalize.py`), same shape as the existing `errata_change_entry`/empty-quote
checks — no LLM call, deterministic, cheap.

**Open question — what's the actual rule?** Candidates:
- `quote.rstrip().endswith(":")` alone — simple, but could a legitimate quote ever end in a colon
  for a non-fragment reason? Haven't found a counterexample in the corpus, but n=173 is small.
- `endswith(":")` AND short (under some word count) — compound condition, lower false-positive risk,
  but need to pick a threshold with actual evidence, not a guess.
- Something checking for a real verb/predicate after removing the colon — more robust in theory,
  cheap NLP heuristics get unreliable fast; probably not worth the complexity for a first pass.

**Bigger idea worth at least naming and then probably deferring:** instead of just rejecting these,
could Step D *salvage* them structurally — pull the actual list-item text from the same chunk (no LLM
call, just string ops) and concatenate it into a complete quote? That would recover real content
instead of just dropping it. Feels like scope creep for a first pass (more moving parts, more ways to
get it subtly wrong) — leaning toward reject-only now, salvage as a possible follow-up once we know
how often this pattern actually recurs in a bigger corpus.

### Category 1 — reference-list misextraction (recommend: fix second, needs more validation)

**Idea:** similar Step D structural rejection, but the detection rule is the hard part.

**Open question — where does the rejection rule even go?** Two options:
- Step D (`parse_and_normalize.py`), matching category 3 and precedent (`errata_change_entry`,
  WP-32.1's grounding check) — consistent home for "reject a structurally-bad requirement."
- Step C's own `validate_requirement()` (`pipeline/llm_extract_requirements.py`) — closer to the
  LLM output, means a fabricated citation-shaped record never gets a `chunk_id`-keyed row at all.
  Less consistent with where similar checks already live, though.
- Leaning Step D for consistency, but genuinely open on this one.

**Open question — what's the actual detection rule, and how do we avoid false positives?** This is
the one I'm least confident about. Citation lines look like `"DoDI 8500.01, Cybersecurity, March 14,
2014"` — roughly: short document-ID-like token, comma-separated title, trailing date. A regex could
catch that shape. But a **real requirement can legitimately contain a date** (e.g. a deadline: "...
by January 1, 2025") — a naive "ends in a date" rule risks rejecting genuinely correct, actionable
requirements, which would be a new regression worse than the problem (same lesson WP-32.1 already
learned the hard way about exact-match grounding checks). This needs real design + testing against
both the known-bad examples *and* a deliberately-checked set of real dated requirements before it
ships, not just a regex that looks right on 7 examples.

### Categories 2, 4, 5 — probably not this phase

- **Category 2 (vagueness)**: the demonstrated regression risk from touching Step C's prompt applies
  most directly here (it's the category most naturally suited to a prompt fix, and that's exactly
  what didn't work reliably). Leaning toward "accept as a known limitation for now," revisit only if
  a bigger corpus shows the rate is worse than 12.5%.
- **Category 4 (background prose)** and **category 5 (form/questionnaire content)**: too rare (1/40
  each) to justify dedicated mechanisms on their own. Might get incidentally caught by a broader
  "does this even look like an obligation" check someday, but not a planned line item.

### The bigger one — description-grounding/entailment check (Tier 2, own investigation)

This is the highest-value fix (it's what actually catches the *fabricated description* symptom in
both categories 1 and 3), but per Codex's PR #156 review it can't reuse WP-32.1's existing grounding
check as-is — that check does fuzzy substring matching between a **verbatim** quote and its verbatim
chunk, and `description` is an intentional paraphrase (Step D.5's own prompt asks for "one precise
sentence summarizing"). A faithful summary would legitimately fail a literal substring match.

Rough candidate directions, none evaluated yet:
- Cheap/weak: check that named entities, numbers, and control-IDs mentioned in `description` actually
  appear somewhere in `source_quote` — automatable, no LLM call, but a weak signal (catches gross
  fabrication, misses subtler invented claims).
- LLM self-check: have Step D.5 also state whether its own description is fully supported by the
  quote, as an extra field on the same call it already makes. No new LLM round-trip, but this is
  both a **schema change** (new field on the enriched record) and arguably a **new LLM-generation
  judgment** — both on the project's stop-and-ask list, needs explicit sign-off before any
  implementation work starts.
- Constrain `description` to be more extractive/verbatim-anchored by prompt design — plausible, but
  we just demonstrated real regression risk from editing a similar prompt (Step C, not D.5 — risk
  doesn't automatically transfer, but it's a reason for caution, not confidence).

**Recommendation: scope this as its own investigation, separate from Tier 1, not bundled in.** It
needs a real design pass before implementation, not just "extend the existing check" (already wrong
once).

---

## 3. Cross-cutting open question: is a 173-record corpus enough to validate any of this on?

Every number in WP-33.3's findings comes from 2 documents. Before locking in a specific regex/
threshold for category 1 or 3, it'd help to validate against more real data than the ~7 examples we
already know about by heart — otherwise we risk overfitting a rule to exactly the cases we've already
seen and missing the shape of cases we haven't. Two options:
- Re-ingest a few more documents from the original 44-doc corpus first (this also revisits the
  explicit "rest-of-corpus re-ingest" decision WP-32.1 deliberately deferred and never actually
  made), giving both a bigger validation set and closer-to-real corpus size.
- Ship Tier 1 against the current small corpus, treat it as provisional, and revisit thresholds once
  the corpus grows for other reasons.

Leaning toward the first (a small re-ingest batch, maybe 3-5 more documents, before or alongside
Tier 1) since it directly de-risks the part I'm least confident about (category 1's detection rule),
but this is a real scope/cost tradeoff worth a second opinion on, not something to just decide here.

---

## 4. Strawman WP breakdown (for reaction, not commitment)

- **WP-34.1 — Reject unrepairable fragment quotes in Step D.** Category 3 only. Smallest, safest,
  most mechanical — ships first, same sequencing logic Phase 33 used (smallest/most mechanical
  first).
- **WP-34.2 — Reject citation-list-shaped quotes in Step D.** Category 1. Needs the false-positive
  question above resolved first; may need the corpus-growth step from §3 as a prerequisite or as
  part of this WP's own validation.
- **WP-34.3 (maybe, own phase if it needs one) — Description-grounding/entailment investigation.**
  Explicitly a spike first (mirrors WP-33.3's own discipline), not an implementation WP, given how
  much is still unresolved above. Touches the stop-and-ask list if it lands on a schema/new-LLM-call
  approach — flag for sign-off before any of those get built.

Categories 2/4/5 stay as `docs/TODO_future_improvements.txt` notes, not WPs, per §2 above.

---

## 5. What I'd like a second opinion on specifically

1. Category 1's detection rule (§2) — this is the part most likely to be wrong in a non-obvious way
   (false positives against real dated requirements). Worth having Codex or another model take a
   pass at rule design before we write it, not just review it after.
2. Whether the description-grounding check (§2, Tier 2) is worth investigating now as part of this
   phase, or genuinely deferred further out — it's the highest-value fix but also the least scoped.
3. The corpus-size question in §3 — is a small re-ingest batch worth doing now, or premature.
4. WP sequencing in §4 — split as three WPs (or two + a deferred spike) as drafted, or combine
   differently.

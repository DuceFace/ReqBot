# Phase 34 Brainstorm — Actionability Fix Options

**Status:** Brainstorm / discussion draft — **not** a locked phase doc yet. This intentionally
carries more "why" narrative than a normal phase doc would (see
`~/reqbot-agent-docs/reqbot/references/work-package-workflow.md` for the normal format) — the goal
here is to react to and refine the approach before it gets locked into WP scope, success criteria,
and guardrails.

**Source:** WP-33.3's spike (`docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings, PR #156).

**Revision note (2026-07-29):** the first version of this doc (reviewed by Codex, see §5) assumed
the corpus it was reasoning about was representative. It wasn't — see §2. Re-ingesting via docling
changed the picture enough that this is close to a rewrite, not a patch. Kept for the record: Codex's
review of the first draft was directionally right (Step D as the home for these checks, use
`section_title_path` context, don't rely on citation-list quote-shape alone) even though the specific
scenario it was reasoning about (our corpus) turned out to be an edge case, not the norm.

---

## 1. The problem, briefly

WP-33.3 hand-labeled a random sample of the live corpus and found 37.5% of requirements show some
form of "cannot be trusted/verified as extracted," decomposing into five failure modes (full detail:
`docs/PHASE33_REQUIREMENTS.md`'s WP-33.3 Findings). **Why this matters enough to fix:** ReqBot's
value proposition is verbatim, trustworthy extraction — "ingestion captures verbatim... do not invent
obligations" is a core architecture principle, and at least one of these failure modes (fabricated
`description` content completing a truncated quote) already violates it in production today.

## 2. Correction: the corpus this was all based on was an edge case, not the norm

Both documents in the current corpus (`afpd_17-1.pdf`, `CJCSI 6510.02G.pdf` — the only two re-ingested
since WP-32.1's corpus nuke) turned out to have been ingested via **legacy pymupdf chunking**, not
docling — despite `--layout-mode auto` defaulting to docling when available, and despite docling
being installed and working fine in this environment right now (confirmed live, 2026-07-29). Root
cause is most likely that docling wasn't installed yet at the time of that specific ingest
(2026-07-27); not a reproduced bug.

This matters because legacy chunking has no section-hierarchy metadata at all — every finding in
WP-33.3's spike, and everything Codex's review of this doc's first draft reasoned about, was
implicitly scoped to a corpus that doesn't represent how ReqBot is actually meant to run. So before
going further, both documents were re-ingested via `--layout-mode docling` (`--no-index`, so this
didn't touch Qdrant) to see whether the same failure modes even look the same under real conditions.
They don't, uniformly.

**This also reframes an earlier open question in this doc's first draft** ("is a 2-document corpus
enough to validate a detection rule on") — re-ingesting the existing two documents via docling alone
already surfaced a materially different, better picture. A broader re-ingest is still worth doing
eventually (see §6), but it's no longer a blocker for scoping Tier 1.

## 3. Revised findings, per category (now evidence-based across both documents' docling re-ingests)

### Category 1 (reference-list misextraction) — likely already solved, no new code needed

**Zero occurrences across both documents.** Not because the model got smarter — the References/
Glossary section chunks never reached Step C at all. `stats.json` confirms `skip_sections_applied:
true` for both; `skip_sections` (`['GLOSSARY', 'REFERENCES', 'ACRONYMS', 'DEFINITIONS',
'ABBREVIATIONS', 'TABLE OF CONTENTS']`) already covers this — it's WP-33.2's own shipped feature
working exactly as designed. The riskiest part of this brainstorm's first draft — a citation-shape
detection regex, with real false-positive risk against genuinely dated real requirements — likely
doesn't need to be built at all. **The actual "fix" is: make sure the corpus is ingested via docling.**
Worth validating on 1-2 more documents before fully closing this one out, but the signal from two
documents (afpd_17-1: a dense multi-line reference list; CJCSI: no distinct references section at
all) is a good sign, not a coincidence tied to one document's structure.

### Category 4 (background/definitional prose) — narrow, low-risk config gap

`afpd_17-1.pdf`'s glossary section is headed literally `"Terms"` — not in the configured
`skip_sections` list, so it wasn't dropped, and its prose still got misextracted as a requirement.
CJCSI has no equivalent issue (no comparably-named section). This looks like a heading-vocabulary
gap in `skip_sections`'s matching, not a new mechanism (`_should_skip_section` in
`pipeline/chunk_text.py` already does case-insensitive, prefix-based matching — it just doesn't know
about `"TERMS"` as a synonym for `"DEFINITIONS"`/`"GLOSSARY"`). **Open question:** worth surveying a
few more real documents' actual heading vocabulary before locking in a specific expanded list, rather
than guessing synonyms from one example.

### Categories 2 + 3 (boilerplate meta-statements + fragment quotes) — still real, better evidence now

These are the ones that still need a real Step D structural check. Found 5 concrete cross-document
examples (not the original 2), decomposing into two distinguishable, complementary signatures:

- **Quote echoes its own `section_title_path` heading verbatim.** `afpd_17-1.pdf`'s
  `"COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"` and `"All HAF Functionals, MAJCOMs, DRUs, and
  FOAs will:"` both got extracted as body-content quotes, but both are *exactly* the chunk's own
  `section_title_path[-1]` value — Step C extracted a structural heading as if it were prose. This is
  a strong, precise, cheap signal precisely because it's grounded in docling's own structural ground
  truth, not a fragile text-pattern guess (this generalizes Codex's `section_title_path` suggestion —
  it applies to more than just citation detection).
- **Quote ends in a colon with no obligation content after it.** Didn't recur in CJCSI's fragment
  case from WP-33.3 (`"The MC4EB will:"` — that exact one didn't repeat under docling, most likely
  LLM run-to-run variance, not a structural fix), but two *new* colon-fragments showed up in CJCSI's
  docling re-ingest instead (`"The process will be as follows:"`, `"The KER may be sent either by...
  or by mail to the address listed below:"`) — under `section_title_path: ['UNCLASSIFIED']`, a
  repeated classification-marking artifact, not a real heading, so the heading-echo signal above
  wouldn't have caught these two. The two signals are complementary, not redundant — worth combining
  (OR'd), not picking one.

Recommendation unchanged from the first draft on *where* this lives: Step D
(`pipeline/parse_and_normalize.py`), same shape as the existing `errata_change_entry`/grounding
checks — deterministic, no LLM call, durable failure reason. This is docling-only by nature (needs
`section_title_path`), which is a fine tradeoff given the direction in §6, not something to build a
legacy-chunking fallback for.

### Category 5 (form/questionnaire content) — unchanged, not re-examined this round

Still rare (1/40 in the original sample), still low priority. Didn't specifically re-check it against
the docling re-ingests; not worth chasing further before there's a bigger sample.

## 4. Description-grounding (Tier 2) — now with a real technique to point at, not just a gap

Quick literature pass (not exhaustive) on "does a generated summary/description actually follow from
its source" — this is the established **faithfulness hallucination** detection problem, not something
to design from scratch:

- **NLI (natural language inference) cross-encoder entailment scoring** — `premise=source_quote`,
  `hypothesis=description` — is the standard lightweight technique. Same architectural slot as
  WP-32.1's existing `rapidfuzz` grounding check, just semantic instead of literal. Purpose-built
  compact models exist for this (Vectara's HHEM is specifically tuned for RAG-style groundedness;
  MiniCheck/FactCG are newer lightweight options) — runs locally, no API call, no per-record LLM cost,
  fits the self-hosted/air-gapped angle. This is a **new dependency** — per direct guidance, that's
  fine to bring with a real reason and test results, not a heavy blocker. Worth a small spike
  (analogous to `eval/docling_spike.py`'s "test a candidate library, look at real results" pattern)
  before committing to shipping it.
- **Having Step D.5 self-report whether its own description is grounded** (this doc's original Tier 2
  option (b)) should be deprioritized, not just left as one of several roughly-equal options — the
  literature is fairly clear that a model checking its own output is one of the weakest forms of
  verification (a model that fabricates a claim tends to also validate that same fabrication when
  asked to check it).

Still recommend scoping this as its own investigation (WP-34.3, spike-first, mirroring WP-33.3's own
discipline) rather than bundling it with the Tier 1 structural checks above — it's the highest-value
fix (directly targets the fabricated-description symptom) but the least scoped, and per Codex's
original review, it correctly can't just reuse WP-32.1's verbatim-matching check as-is (a real
paraphrase legitimately fails a literal substring match).

## 5. What changed from Codex's review of the first draft, and why

Codex's review (full text on PR #157) made four substantive points. Revisiting each against the new
evidence:

1. **Category 3 structural check lives in Step D, avoid a bare `endswith(":")` rule** — still agrees;
   now have 5 real examples (not 2) to build the compound rule and test set against, per §3.
2. **Category 1 should use `section_title_path`/chunk context, not date-shape** — correct in
   principle, and the underlying idea (lean on docling's real structure) generalizes well — it just
   turned out the *problem itself* mostly stops existing once you're actually on docling with
   `skip_sections` applied, so there's no citation-detection rule left to design in the first place.
3. **Use existing gold/seeded fixtures instead of requiring new ingest** — **retracted.**
   `eval/gold_eval_chunks*.jsonl` (including `_curated`) is unfinished, abandoned work with an
   estimated ~20% noise rate in `gold_requirements` (confirmed directly by the person who started it) —
   not reliable ground truth without a fresh audit pass. Also moot for category 1 now that no
   citation regex is being built. The Tier 1 checks in §3 can be validated against real fixtures
   pulled directly from the two documents already re-ingested this round.
4. **Description-grounding deserves a spike, not Tier 1** — still agrees; §4 above.

## 6. Open direction, not yet decided: is legacy chunking worth keeping at all?

Raised directly during this planning session, not yet a final call, but worth stating plainly since
it shapes how Tier 1 should be scoped: `pyproject.toml` gates docling out of the base install "purely
for weight" (torch/torchvision) — a real past decision (`archive/PHASE25_REQUIREMENTS.md`). Given
ReqBot's actual deployment context (IT admins standing it up on a real network, not a
storage-constrained device), that tradeoff is being reconsidered. If pymupdf/pdfplumber chunking
isn't earning its keep against docling, the likely direction is dropping to docling-only rather than
maintaining dual-path support indefinitely — which would also retroactively simplify §3's fixes
(no need to reason about a legacy-chunking fallback for the structural checks at all). Not deciding
this here — naming it so Tier 1 doesn't get scoped around supporting a path that may not be sticking
around.

## 7. Revised strawman WP breakdown (smaller than the first draft)

- **WP-34.1 — Reject heading-echoed and unrepairable-fragment quotes in Step D.** Categories 2+3,
  combined (they turned out to share a Step D home and complementary detection signals). Deterministic,
  docling-only, 5 real cross-document fixtures already in hand.
- **WP-34.2 — Expand `skip_sections` heading vocabulary + confirm the corpus is docling-ingested.**
  Category 4 (config change) + closing out category 1 (process: make docling ingestion the norm,
  survey a few more documents' heading vocabulary first). Much smaller than the citation-regex design
  work originally scoped here.
- **WP-34.3 (own phase if it needs one) — Description-grounding spike.** Investigation-only,
  including a small NLI-model try-it-and-look-at-results pass per §4. Unchanged from the first draft.

Categories 5 stays a `docs/TODO_future_improvements.txt` note, not a WP.

## 8. What I'd like a second opinion on now

1. Is "ensure corpus is docling-ingested + rely on existing `skip_sections`" a sufficient answer for
   category 1, or does it still deserve a defensive Step D check for the case where docling isn't
   available/fails and a document falls back to legacy chunking anyway?
2. The `skip_sections` heading-vocabulary survey (§3, category 4) — worth doing against a few more
   documents before writing WP-34.2, or expand the list now and iterate later?
3. Is the NLI-entailment approach (§4) worth spiking now as part of Phase 34, or genuinely deferred
   further out given it's still the least-scoped piece?
4. §6 — is it worth explicitly deciding the legacy-chunking question before or alongside WP-34.1/34.2,
   rather than leaving it as an open direction that could still shift scope later?

# ReqBot Phase 38 — Extraction Precision: Failure Audit & Targeted Fixes

**Status:** Locked (drafted 2026-07-31; source: a separate conversation between Tyler and another
Claude session about extraction precision, shared as "spark notes"; my own review of those notes;
a real pre-doc spot-check of the current corpus, both below)
**Date:** 2026-07-31
**Preceded by:** Phase 37 (Retrieval Quality: Eval Harness & Contextual Chunk Embeddings) — WP-37.1
complete (harness + baseline), WP-37.2 complete as a negative result (contextual embeddings
reverted, `docs/PHASE37_REQUIREMENTS.md`).
**Followed by:** None currently planned.

---

## Status

This table is the live source of truth for Phase 38 WP status — update it here when a WP lands, not
in `CLAUDE.md` or anywhere else.

| WP | Status |
|---|---|
| WP-38.1 — Extraction Precision Failure Audit | Complete |
| WP-38.2 — Deterministic Fragment-Rejection Rule Extensions | Complete |

---

## 1. Phase Framing

Phases 32-36 fixed several distinct extraction-correctness problems (fabricated quotes, heading-echo
and unrepairable fragments, description fabrication, entailment-gate calibration). A separate
conversation between Tyler and another Claude session (2026-07-31, shared as "spark notes") diagnosed
a related but different shape of problem in the same pipeline stage: the 8B extractor doesn't miss
real requirements, but it over-grabs — it flags text *near* a requirement (definitions, background,
examples, headers) as if it were one. Precision, not recall.

**That conversation's proposal, reviewed here first (summarized; full review given to Tyler
separately):** keep the current 8B extractor, add a small, cheap second-stage classifier after it
whose only job is "is this candidate span actually a requirement — yes/no." Standard shape (recall-
first pass, precision-first filter — mirrors this pipeline's own retriever→reranker split one stage
earlier), and it matches this project's own consistent preference for a cheap targeted fix over
retraining the main model. The review flagged three real gaps before treating the proposal as
ready to build against, all addressed by how this phase is scoped:

1. **Possible overlap with already-shipped work.** "Over-grabs definitions, background, examples,
   headers" is close to word-for-word what WP-33.3 (actionability spike) and WP-34.2/34.3
   (heading-echo/fragment rejection, expanded `skip_sections` vocabulary) already targeted and
   shipped in this exact codebase. The other conversation didn't have this project's phase history
   available. Unresolved question: is the diagnosis based on failures that survive *after* those
   fixes, or could it be re-discovering already-covered ground?
2. **Data-sourcing check, done directly rather than assumed — and scoped honestly as a local
   observation, not a repo guarantee (corrected after a local Codex review flagged this, 2026-07-31):
   `raw_pdfs/` is listed in `.gitignore` and holds no tracked files** (`git ls-files raw_pdfs/`
   returns nothing) — its contents are whatever happens to be present on a given machine, not
   something the repository itself provides. On *this* environment specifically, `raw_pdfs/` was
   checked directly and `NIST.SP.800-53r5.pdf`/`NIST.SP.800-53Ar5.pdf` are present (not currently
   ingested into the live corpus, but available locally); no PCI DSS document exists here at all.
   Whoever picks up WP-38.2 needs to independently verify `raw_pdfs/` on their own machine before
   relying on this — if the 800-53/800-53Ar5 PDFs aren't there, they're publicly available from NIST
   directly and would need downloading; using more of ReqBot's own actual target corpus (the DoD/AF
   documents already present) may be a better source of negative examples than an off-theme document
   regardless.
3. **Gold-set caution:** if any future validation reuses `eval/gold_eval_chunks*.jsonl`, that dataset
   is documented (prior-session findings) as an unfinished, abandoned hand-correction pass with ~20%
   known-bad labels — not ground truth without a fresh audit first.

**The other conversation's own notes already named the necessary first step**, before building
anything: *"sort existing extraction failures into 'false positive on real requirement-adjacent
text' vs. any other failure mode, to confirm the precision framing holds across the full failure
set."* This phase's first WP is exactly that — not the classifier itself.

**A real, timestamp-verified spot-check done before writing this doc (not a full audit — that's
WP-38.1's job, but enough to confirm the phenomenon is real in the *current* pipeline, not just
historical):**

- Found genuine, current over-grab-shaped failures in a `NIST.SP.800-125` run timestamped
  2026-07-30T22:03:59Z — after Phase 34 closed (2026-07-30) — e.g. `REQ-f9eae50391e8`
  (`"implement the following recommendations"`) and `REQ-dca74d91cec2`
  (`"enforce security requirements"`): short phrase fragments with no real obligation content of
  their own. Checked directly against the existing rejection logic
  (`pipeline/parse_and_normalize.py`): `_is_unrepairable_fragment()` only fires on quotes ending in a
  bare colon (its deliberately narrow WP-34.2 trigger); neither of these ends in one, and neither
  matches `_is_heading_echo()` either. **A real, confirmed gap in current coverage, not a stale-data
  artifact.**
- Also found two candidates in an older `CJCSI 6510.02G` run timestamped 2026-07-29T02:03:53Z —
  e.g. `REQ-409e58971a57` (`"Distribution: A, B, C"`, a document-metadata stamp) — but that run
  predates when WP-34.2 likely merged; **can't be cited as a current gap without re-ingesting that
  document fresh and re-checking**, which is exactly why WP-38.1's scope requires fresh ingests, not
  just eyeballing whatever is already sitting in the corpus.
- A crude regex sweep for definition/example-style language across the full corpus (1,876 records)
  found only 10 hits, and hand-reading them showed most were false alarms on my own heuristic (real
  requirements that happen to contain the word "means") — confirming a real audit needs a more
  careful methodology than keyword matching, not a quick grep.
- One hypothesis was checked and ruled out before it became a false claim in this doc: three
  identical-text records (`"Participate in cyberspace governance forums."`) initially looked like a
  possible duplicate-extraction bug. Checking their `chunk_id`/`section_title_path` directly showed
  they're three genuinely distinct real directives — the same sentence independently assigned to
  three different responsible offices (AF/A2, A5/8, AFSPC) in the source document. Not a bug — a
  reminder that an apparent pattern needs the same verification as anything else before it goes in a
  Findings section (see `docs/PHASE37_REQUIREMENTS.md`'s WP-37.2 Findings for the last time this
  exact discipline caught a real mistake in this project).

This confirms the diagnosis has real substance in the *current*, post-Phase-34 pipeline — but at a
rate a crude spot-check can't reliably size. That's the whole reason WP-38.1 exists before anyone
commits to building a trained classifier.

**One more open question, flagged but not resolved here:** the same conversation separately
recommended deterministic heading-chain context as *preferred* for embedding input in this domain.
That's in tension with `docs/PHASE37_REQUIREMENTS.md`'s WP-37.2 finding — prepending exactly that
kind of context (document title + section heading + parent_context) measurably *regressed*
retrieval quality on this corpus, root-caused to this corpus's section headings describing
procedural/bureaucratic structure rather than topic. Unclear whether the other conversation's
recommendation was tested against a bare-quote baseline or reasoned untested, and unclear whether it
was about embedding input for search (what WP-37.2 tested) or something else (e.g. extraction-time
context). Not resolved by this phase — noted so it isn't silently forgotten.

## 2. Goals

- Systematically categorize real, *current* extraction-precision failures across the corpus: genuine
  over-grab (non-requirement text — definitions, background, examples, headers, administrative
  boilerplate) vs. fragment/incomplete-extraction (a distinct, partially-already-addressed failure
  mode) vs. anything else the audit surfaces.
- For every genuine failure found, check it against the *existing* `skip_sections`/heading-echo/
  fragment-rejection logic's actual trigger conditions to classify it: already-should-be-caught-
  but-isn't (real bug), not-covered-by-any-current-rule (candidate for a cheap rule extension or the
  proposed classifier), or genuinely ambiguous/judgment-requiring (best classifier candidate).
- Produce a real, committed, hand-verified count and category breakdown — not an assumption — of how
  much of the corpus is actually affected, informing whether a trained classifier is proportionate or
  whether targeted rule extensions close most of the gap more cheaply.
- Only after that: decide, evidenced, whether WP-38.2 (a trained precision-filter classifier, per the
  original proposal) is warranted, and at what scope — or whether it isn't needed at all.

## 3. Non-Goals

- **Not building the classifier yet.** WP-38.2 is explicitly conditional on WP-38.1's findings, not
  pre-committed to any particular shape.
- **Not retraining or replacing the 8B extractor.** Matches the source proposal's own reasoning —
  this is a precision problem, not a recall problem, so a bigger/retrained model isn't the first
  lever to reach for.
- **Not the question-generation quality issue or the contextual-embedding/chunking-strategy
  discussion from the same conversation.** Separate concerns; tracked in
  `docs/TODO_future_improvements.txt` if/when they become independently actionable, not folded into
  this phase.
- **Not re-litigating Phase 37's contextual-embedding finding.** The tension noted above (Phase
  Framing) is flagged as an open question, not something this phase resolves.
- **Not validating anything against `eval/gold_eval_chunks*.jsonl` in its current form.** Documented
  unreliable; would need its own audit first, which is out of scope here.

---

## 4. Work Packages

### WP-38.1 — Extraction Precision Failure Audit

**Source:** The other Claude conversation's own stated "immediate action item"; this doc's Phase
Framing spot-check above.

**Problem:** No systematic, current-pipeline count of extraction-precision failures exists. The
"over-grabs adjacent text" diagnosis is real (confirmed above, against fresh post-Phase-34 data) but
unsized — every downstream decision (build a classifier? extend existing rules? both?) depends on
knowing the real rate and shape, not assuming it.

**Scope:**
- Freshly ingest (or otherwise confirm current, via `run_timestamp`) a representative sample of
  documents through the full current pipeline (Step A→D.6) before auditing anything — this phase's
  own scoping already found that eyeballing the existing corpus mixes fresh and stale (pre-Phase-34)
  data, and stale data doesn't count as evidence of a current problem.
- **Two separate sampling passes, not one (Codex review, PR #179: a single heuristic-narrowed sample
  cannot support both jobs at once).** (1) *Failure discovery* — a heuristic-narrowed candidate pool
  (e.g. short-quote + no-modal-verb heuristics, similar in spirit to WP-35.1's harvester-heuristic-
  then-verify pattern) is fine and efficient for *finding* real examples of each failure shape, since
  naive keyword matching alone produces mostly false alarms (confirmed above). (2) *Prevalence
  estimate* — a genuinely random or explicitly stratified-by-document sample, independent of any
  discovery heuristic, hand-reviewed in full, is required for the "how much of the corpus is actually
  affected" number the Goals ask for. Records that are genuine over-grabs but don't match the
  discovery heuristic (wrong length, happens to contain a modal verb, etc.) would otherwise be
  silently excluded from the denominator too — which could make a real problem look negligible for no
  reason other than the heuristic's own blind spots, exactly the kind of composite-denominator mistake
  already caught once in this project (`docs/PHASE36_REQUIREMENTS.md`'s WP-36.2 Findings).
  **Minimum size, not left open-ended (local Codex review, 2026-07-31):** the unbiased sample must
  cover a real minimum — at least 300 records, drawn from at least 8 of the corpus's 13 documents
  (stratified across document, not concentrated in whichever happens to be largest) — small enough to
  hand-review in full, large enough that a handful of found/not-found examples don't swing the rate
  wildly. Report the real achieved size and coverage plainly if it lands short of this, the same
  scale-honesty WP-35.1/35.2 already apply to their own small hand-labeled sets — don't silently
  round up to "representative" without saying so.
- For every genuine failure found (either pass), check it against `_is_heading_echo()`,
  `_is_unrepairable_fragment()`, and the current `skip_sections` vocabulary to classify: real gap in
  existing coverage, not covered by design (candidate for extension or classifier), or genuinely
  judgment-requiring.
- Produce a committed count from the *unbiased* sample specifically — X failures found / Y records in
  the random/stratified sample — as the real prevalence estimate, broken down by category, with
  example `requirement_id`s and quotes per category pulled from either sampling pass — same rigor as
  WP-35.1's hand-verified gold set, not a summary without receipts.
- End with an explicit, evidenced recommendation: build the classifier (WP-38.2 proposal as
  originally scoped), extend existing deterministic rules instead, some mix, or — if the real rate
  turns out to be negligible post-Phase-34 — that neither is currently warranted.

**Non-goals:**
- Not fixing anything found yet — audit and categorize only. A genuinely trivial, obviously-safe rule
  gap fix can be noted as a candidate but implementing it is a separate WP unless it's small enough
  and Tyler explicitly wants it folded in.
- Not building classifier training data yet, even if the audit concludes one is warranted — that's
  a subsequent WP once scope is actually known.

**Tests/verification:**
- This is fundamentally an investigation/measurement WP, same shape as WP-35.1 — the committed audit
  findings (real counts, categorized examples) are the deliverable, not new production code.
- If a deterministic rule gap is found and a fix is small/safe enough to include without expanding
  this WP's scope, add a regression test for it same as any other pipeline fix; otherwise defer.
- `ruff check .` clean if any code changes are made.

**Gate:** A real, hand-verified categorization of extraction-precision failures exists across a
freshly-verified (not stale) sample of the corpus, with real counts per category and a grounded
recommendation for what — if anything — WP-38.2 should build.

**Findings (2026-07-31):**

*Corpus freshness.* Cross-checked every document's latest processed run against WP-34.2/34.3's
merge times (2026-07-30 13:07/14:12 CDT). 12 of 13 documents already had a run newer than both
fixes. `CJCSI 6510.02G`'s latest run (`20260729_020101`) predated them — the same run this phase's
own Phase Framing spot-check had already flagged as unusable evidence. Re-ingested it fresh
(`CJCSI 6510.02G_20260731_152438`, 87 requirements) before sampling anything, so all 13 documents
now reflect the current pipeline. Corpus total: 1,872 requirements (via
`core.artifact_resolver.resolve_latest_requirement_files()` — the same "latest run, best tier"
resolver `reindex` itself uses, so the audit reads exactly what the live pipeline currently
produces).

*Sampling (both passes specified by Scope above, kept genuinely separate):*
- **Unbiased/stratified sample** (the prevalence denominator): 333 records, stratified
  proportionally by document with a 15-record floor per document, seed `3801`. Script, outputs, and
  a source manifest (per-document file name, record count, and sha256 — the raw 1,872-record
  population itself lives outside the repo in `~/documents/processed` and isn't committed, so the
  manifest is what lets a future reader verify whether their corpus matches the one this audit
  actually drew from) are all committed at `eval/audit_wp38_1/` (Codex review, PR #180). All 13
  documents represented, exceeding the ≥300-record/≥8-document minimum.
- **Discovery pool** (heuristic-narrowed, for finding examples only — never used for the count
  below): 183 records flagged by short-quote / no-terminal-punctuation / all-caps-heading /
  definition-opener signals. 9.8% hit rate on the signals alone, consistent with this phase's
  earlier finding that naive heuristics overselect — most of the value here was in *which*
  examples it surfaced, not its own hit rate.

*Prevalence, from the unbiased sample only (333 records, all hand-read):*

| Category | Count | % of sample (unweighted) | % of corpus (population-weighted) |
|---|---:|---:|---:|
| Real, correctly-extracted requirement | 284 | 85.3% | 85.4% |
| Fragment / incomplete extraction | 25 | 7.5% | 7.3% |
| Genuine over-grab (non-requirement text) | 19 | 5.7% | 5.8% |
| Judgment-requiring / ambiguous | 5 | 1.5% | 1.5% |

(Weighted column via `eval/audit_wp38_1/compute_weighted_prevalence.py`, committed — corrects for
the 15-record floor over-representing 3 smaller documents, see below. The corrections are all
small here, but the weighted column is the one that actually estimates corpus-wide prevalence.)

**The headline rate needs one correction before it's a real corpus estimate.** The 15-record floor
binds for 3 of 13 documents (`DODI 5200.01`, `DODI 8551.01`, `afpd_17-1` — each would have received
fewer than 15 records under pure proportional allocation), so those documents are over-represented
in the raw 333 relative to their true share of the 1,872-record corpus. Reporting the unweighted
44/333 ratio as-is estimates the sample's composition, not the corpus's — the same class of mistake
as `docs/PHASE36_REQUIREMENTS.md`'s WP-36.2 finding (Codex review, PR #180, caught before this
number shipped). Weighting each document's local failure rate by its true population share
(`eval/audit_wp38_1/compute_weighted_prevalence.py`, committed) gives **13.1%**, against 13.2%
unweighted — in this case the correction is small (the over-sampled documents' failure rates
happened to roughly bracket the corpus average), but the estimator was still the wrong one, and the
weighted number is the one that should be treated as authoritative.

**The diagnosis is real and non-trivial: ~13.1% of the current, post-Phase-34 corpus is a clear-cut
precision failure** — an order of magnitude above the Phase Framing spot-check's crude regex sweep
(10/1,876, 0.5%), confirming that spot-check's own conclusion that keyword matching alone
understates the problem. Failures were found in 10 of the 13 documents sampled (not concentrated in
one outlier document); `CJCSI 6510.02G`'s freshly re-ingested sample had zero flagged records, a
small (n=15) but reassuring sign for the just-shipped fix.

*Fragment sub-shapes (25 total):*
- **Orphaned list item** (12) — a real list item's text extracted without the governing sentence
  that gives it meaning, most often numbered/lettered markers: `REQ-c6aeb8df528b` (DODI 5200.01)
  — `"(3) Restrain competition."` — is actually item 3 of a "classification shall not be used
  to:" prohibition list; alone it reads as nonsensical. `REQ-48f549669bb2` (DODI 8410.03) —
  `"Required NM data update rates."` — a bare noun-phrase list item.
- **Dangling/preamble clause** (6) — a subordinate clause with no main clause attached:
  `REQ-4aeeff50f15b` (DODI 5200.01) — `"Under the authority, direction, and control of the Chief
  Management Officer of the Department of Defense, in addition to the responsibilities in section
  11 of this enclosure and in accordance with References (a), (c), and DoDD 5110.04 (Reference
  (af)),"` — a responsibilities-list preamble with no verb, trailing comma.
- **Colon-terminated, too long for the existing rule** (3, code-verified `REAL_GAP` — see below).
- **Malformed/garbled extraction** (4) — table or form content that didn't parse into coherent
  prose: `REQ-17290369ef3b` (afi17-203) — `"If the originator / recipient of the incident report
  (IR) is, 2 = and the Primary Recipient will be."` The discovery pool surfaced two even starker
  examples (not in the prevalence count, but real): `REQ-e6ac0743a77a` (DODI 5200.48) and
  `REQ-e026f6b5506a` (NIST.SP.800-125) both cut off mid-sentence with no closing punctuation at
  all.

*Over-grab sub-shapes (19 total):*
- **Descriptive/definitional/background prose** (13) — sentences that describe or explain rather
  than obligate, heavily concentrated in `NIST.SP.800-125` (a guidance document, not a directive —
  5 of its 26 sampled records): `REQ-189d6285eaa2` — `"Most hypervisor software currently only
  uses passwords for access control; this may be too weak for some organizations' security
  policies..."` — real prose from the source, but description of current practice, not an
  obligation.
- **Reference-only / administrative boilerplate** (4): `REQ-9c62641ac103` (DODI 8410.03) —
  `"This Instruction is effective August 29, 2012."`
- **Explicit "examples of..." text** (1): `REQ-e41d286c83f4` (afi17-203) — `"Examples of
  strategies include modifying network access controls (e.g., firewall)..."` — this is the exact
  same record `docs/PHASE37_REQUIREMENTS.md`'s WP-37.2 cited as its root-cause retrieval example;
  independently flagged here as a probable over-grab, on unrelated grounds.
- **Form/acknowledgment-template text** (1): `REQ-db943fb3ade5` (dafman17-1305) — `"I will obtain
  and maintain the necessary DCWF Foundational and Residential Qualifications..."` — first-person
  signature-block language, the same shape as the AUP-acknowledgment false match WP-37.1's gold
  query set already had to hand-exclude (`REQ-fe7ffa6bad30`).

*Rule-coverage classification (every genuine failure checked against the real code, not just
reasoned about — `eval/audit_wp38_1/verify_against_rules.py`, calling `_is_heading_echo()` and
`_is_unrepairable_fragment()` directly against each record's actual `source_quote` and
`section_title_path`):*
- **3 of 44 are `REAL_GAP`** — genuine bugs in existing coverage, not new territory. All three are
  colon-terminated list-header fragments (`REQ-97e6e5483093`, 41 words; `REQ-a22b2ca5ab90`, 30
  words; `REQ-9266f0704b0e`, 39 words) that `_is_unrepairable_fragment()`'s own logic would
  correctly reject — except its `UNREPAIRABLE_FRAGMENT_MAX_WORDS = 25` cap (chosen in WP-34.2
  specifically to avoid rejecting long-but-complete quotes) is too tight. A colon-ending quote
  carries no content of its own regardless of how many words precede the colon — the length cap's
  original justification doesn't actually hold.
- **A 4th `REAL_GAP`, found via the discovery pool** (not counted in the 44/333, since discovery
  isn't the prevalence sample, but real and code-confirmed): `REQ-955ab005b394` (afi10-2402) —
  `"COMPLIANCE WITH THIS PUBLICATION IS MANDATORY"` — is a verbatim echo of an *ancestor* heading
  (`section_title_path[0]`, two levels up from the chunk's own immediate heading). Confirmed
  directly: `_is_heading_echo(quote, section_title_path)` → `False` (checks only
  `section_title_path[-1]`, the immediate heading), but `_is_heading_echo(quote,
  [section_title_path[0]])` → `True`. The rule was scoped (correctly, per its own docstring) to
  the chunk's own immediate heading only — it was never designed to walk the full ancestor chain,
  so this isn't a coding mistake, but it is a real, reproducible blind spot.
- **41 of 44 are `NOT_COVERED_BY_DESIGN`** — no current rule targets these shapes at all.
  `_is_heading_echo()` and `_is_unrepairable_fragment()` were built narrowly (WP-34.2) against two
  specific fabrication patterns found at the time; orphaned list items, dangling clauses,
  descriptive/definitional prose, reference-only pointers, and acknowledgment-template text are a
  materially different, wider set of shapes that Phase 34 was never scoped to catch.
- **0 of 44 are `SHOULD_BE_CAUGHT_BUT_ISNT`** — no case where an existing rule's trigger condition
  is met but the record slipped through anyway (which would indicate an implementation bug rather
  than a scope gap). Every failure here survived because no rule currently targets its shape, not
  because an existing rule is broken.

**Recommendation:** Evidenced, not assumed — see WP-38.2 below. The fragment shapes (7.3% of
corpus, population-weighted) are mechanically identifiable from `source_quote` text alone
(list-item markers, missing finite verbs, colon-termination) and cheap/low-risk to fix with
deterministic rule extensions, the same shape as the WP-34.2 fix that already shipped
successfully. The over-grab shapes (5.8%) require actual reading comprehension to tell "describes"
from "obligates" — not something a regex can reliably do — and are the better candidate for a
classifier *if* they remain material once the cheap fixes are in and re-measured. Recommendation:
**rule extensions now (WP-38.2, scoped below); defer the classifier question** for the over-grab
shapes as tracked backlog rather than building it against today's unvalidated-post-fix numbers.

---

### WP-38.2 — Deterministic Fragment-Rejection Rule Extensions

**Now properly scoped, per WP-38.1's evidenced recommendation above** (real numbers, not the
original proposal assumed at face value). This WP targets only the **fragment** shapes (7.5% of
the audited sample unweighted, 7.3% population-weighted; 25/333 records) — all four are
mechanically identifiable from `source_quote` text alone, the same shape as the WP-34.2 fix that
already shipped successfully. It deliberately does **not** touch the over-grab shapes (5.7%
unweighted, 5.8% weighted; 19/333) — those require judging "describes" vs. "obligates," not
something a deterministic rule can reliably do; see Non-Goals.

**Scope:**
- **Raise or remove `UNREPAIRABLE_FRAGMENT_MAX_WORDS`** (`pipeline/parse_and_normalize.py`,
  currently 25). WP-38.1 found 3 real colon-terminated list-header fragments (30–41 words) that the
  cap lets through. The cap's original justification — avoiding rejection of a "genuinely complete,
  longer quote that just happens to end mid-punctuation" — has no confirmed real example in this
  audit; a colon-ending quote inherently promises content it doesn't contain, regardless of length.
  Calibrate the exact behavior (raise vs. remove) against WP-38.1's own fixture (below), not assumed
  here.
- **New rule: orphaned list item.** A quote starting with a list-item marker (`(1)`, `(a)`, `- d.`,
  etc.) or a short, verb-less noun phrase, with no governing clause attached, carries no independent
  obligation content (12 of the 25 fragment examples were this shape — the largest single fragment
  sub-pattern). Exact detection (marker regex, finite-verb check, or both) is an implementation
  decision, calibrated against the fixture below rather than fixed in this scoping doc.
- **New rule: dangling/preamble clause.** A quote that is a subordinate clause with no main clause
  (opens with "under," "in addition to," "consistent with," etc., or ends in a trailing comma with
  nothing following) is not a self-contained requirement (6 of 25 fragment examples). Same
  calibrate-against-fixture approach as above.
- **Extend `_is_heading_echo()` to check the full `section_title_path`, not just `section_title_path[-1]`.**
  WP-38.1's discovery pool found a code-verified case (`REQ-955ab005b394`) where a quote exactly
  echoes an *ancestor* heading two levels up — the immediate-heading-only check the function was
  scoped to in WP-34.2 structurally cannot catch this. Match against every entry in the path, not
  just the last one.
- **Malformed/garbled extraction (4 of 25 fragment examples) is explicitly not a rule-extension
  target here** — these look like Docling table/form-parsing artifacts, not a `source_quote`-level
  text pattern a deterministic rule could reasonably key on. Note as a carry-forward for a future
  WP if it recurs at a rate worth addressing; not scoped further here.

**Non-Goals:**
- **Not touching the over-grab shapes** (descriptive/definitional prose, reference-only pointers,
  explicit "examples of..." text, acknowledgment-template text) — WP-38.1 found these require actual
  reading comprehension, not a text pattern. Tracked as backlog below, not folded into this WP.
- **Not building a classifier.** Revisit only if the over-grab rate is re-measured after this WP
  ships and still looks material — not committed to now, per the Guardrails' "cheapest fix wins."
- **Not touching `skip_sections`** — WP-38.1 found no failures attributable to a `skip_sections` gap
  (0 of 44 genuine failures had a heading in the existing vocabulary that should have excluded them).
- **`eval/eval_harness.py` still cannot verify this as-is** (Codex review, PR #179, verified directly
  against the code) — it scores `*_extracted_requirements.jsonl`, the raw Step C output, before Step
  D's rejection logic (old or new) ever runs. Not extending it is fine for this WP specifically,
  since verification uses WP-38.1's own fixture instead (below) — but any future WP that wants an
  automated precision/recall regression check across the full pipeline still needs to fix this first.

**Tests/verification:**
- **WP-38.1's own audit fixture is the regression test, already built and committed**
  (`eval/audit_wp38_1/unbiased_sample.jsonl` + `labeled_failures.jsonl`, 333 hand-labeled records:
  284 confirmed-real, 25 fragment, 19 over-grab, 5 judgment-requiring). `labeled_failures.jsonl`
  carries a `subtype` field per record (`orphaned_list_item`, `dangling_clause`, `colon_too_long`,
  `malformed_garbled` for fragments; a separate set for over-grab/judgment), not just the broad
  category (Codex review, PR #180 — the gate below needs the specific sub-shape each rule targets,
  not just "fragment" in general, to be mechanically checkable rather than eyeballed). After the
  new rules ship, re-run them against all 333 and confirm: (1) none of the 284 real records get
  rejected (no regression — the single most important check), (2) filtering `labeled_failures.jsonl`
  by `subtype` for each rule's specific target (e.g. `orphaned_list_item` for the list-item rule)
  shows those records now rejected, (3) the `malformed_garbled` subtype and all `over_grab`/
  `judgment` records are correctly left untouched (confirms scope discipline — this WP explicitly
  doesn't target malformed/garbled fragments either, see Scope above). This reuses a genuinely
  independent, already-hand-verified fixture rather than validating a rule against the same
  reasoning that produced it.
- Standard unit tests for each new/changed rule function, following `tests/unit/test_normalize.py`'s
  existing fixture style (same file WP-34.2's own tests live in).
- `ruff check .` clean.

**Gate:** The new/changed rules reject WP-38.1's 25 hand-labeled fragment examples (or the specific
subset each rule targets) without rejecting any of the 284 hand-labeled real records, and full
`pytest` + `ruff check .` are clean.

**Findings (2026-07-31):**

*What shipped, in `pipeline/parse_and_normalize.py`:*
- `UNREPAIRABLE_FRAGMENT_MAX_WORDS` **removed entirely** (not raised) — `_is_unrepairable_fragment()`
  now rejects any colon-terminated quote regardless of length. The cap's original justification (a
  long quote might legitimately end mid-punctuation) had no confirmed real example in either
  WP-34.2's original spike or WP-38.1's 333-record audit.
- `_is_heading_echo()` now checks every entry in `section_title_path`, not just the immediate
  heading (`[-1]`) — catches the ancestor-heading-echo shape WP-38.1's discovery pool found
  (`REQ-955ab005b394`).
- Two new rules: `_is_orphaned_list_item()` (a list-marker-prefixed or "as defined in"-citation-only
  quote with no governing clause) and `_is_dangling_clause()` (a bare-copula-first-word quote
  missing its subject).

*Calibration against WP-38.1's fixture caught real problems before they shipped — worth recording
because this is exactly the process working as intended, not a footnote.* The first version of
`_is_dangling_clause()` used three signals (lowercase-first-letter, bare-modal-first-word, trailing
bare comma) that all seemed reasonable from the fragment examples alone. Running the new rules
against all 333 hand-labeled records (not just the 6 targeted dangling-clause examples) surfaced 15
real regressions against genuinely correct requirements and 4 scope violations against
over-grab/judgment/malformed-garbled records that must stay untouched — all three broader signals
turned out to be unsafe:
- **Lowercase-first-letter**: this corpus's real DoD/AF-style responsibility lists commonly extract
  individual list items starting mid-sentence on a shared "will:" governing clause — a real,
  correctly-kept requirement (`REQ-474f99ed3b50`, `"establish, direct, and administer all aspects of
  their respective organization's SCI security programs"`) starts lowercase exactly like a genuine
  fragment does.
- **Bare-modal-first-word** (shall/will/must/should/may): a real, correctly-kept requirement
  (`REQ-580c9ef77b37`, `"must have a lawful governmental purpose for such access"`) has the identical
  shape to the targeted fragment `"shall be coordinated with the customer"` — not safely
  distinguishable by this signal alone.
- **Trailing bare comma**: a real, correctly-kept requirement (`REQ-abf7f0a2a776`, ending
  `"...in accordance with Paragraph 3.5.a(4),"`) ends in a comma that's a punctuation artifact of a
  longer source list, not a sign of incomplete content.

`_is_dangling_clause()` was narrowed to only the bare-copula-first-word signal (`Is`/`Are`/`Was`/`Were`
as literally the quote's first word), the one signal that produced zero false positives when checked
against the fixture. This dropped its own targeted catch rate from an originally-hoped-for higher
number down to 1 of 6 — an honest tradeoff, not a shortfall to paper over: a narrow, safe rule that
catches less is strictly better than a broad one that silently discards real requirements.

*Real, code-verified results (`eval/verify_wp38_2_rules.py`, checking the actual rule functions
against all 333 records in `eval/audit_wp38_1/unbiased_sample.jsonl`, committed):*

| Check | Result |
|---|---|
| Real-record regressions (must be 0) | **0 / 284** |
| Scope violations — over_grab/judgment/malformed_garbled caught (must be 0) | **0 / 28** |
| `colon_too_long` fragments caught | **3 / 3** |
| `orphaned_list_item` fragments caught | **3 / 12** |
| `dangling_clause` fragments caught | **1 / 6** |
| `malformed_garbled` fragments correctly left untouched | **4 / 4** |

The `orphaned_list_item` and `colon_too_long` shapes were fully or mostly mechanically identifiable
as scoped. `dangling_clause` was the shape where WP-38.2's own Scope text turned out optimistic —
"three narrow, safe signals" became one after calibration, because most of that sub-pattern's real
examples aren't syntactically distinguishable from genuine short requirements without actual
grammatical analysis, which a regex can't safely do. This mirrors the same "cheapest fix wins, don't
force it" discipline that reverted WP-37.2 rather than shipping a regression.

*Broader sanity check beyond the fixture:* ran all four rules against the full current live corpus
(1,872 records, not just the 333-record sample) — 17 records (0.9%) would be newly rejected on a
re-ingest, all spot-checked and genuinely correct (more instances of the same real shapes: e.g.
`"is responsible for"`, two more `"<term>, as defined in <citation>"` cross-references not in the
original 12-example set). No new false positives found outside the fixture either. A small, surgical
correction, not a broad sweep — consistent with the 7.3% weighted fragment prevalence WP-38.1 found
(this WP doesn't close that whole gap; it closes the mechanically-safe portion of it).

*Gemini + Codex review (PR #181) caught real bugs on top of the calibration above — worth recording
in full, not glossed over:*
- **[High, both reviewers independently, two rounds] `_DEFINED_IN_CITATION_RE` only anchored the
  start of the quote**, so a real requirement opening with a definitional qualifier but continuing
  with a real governing clause (e.g. `"Cybersecurity incidents, as defined in CNSSI 4009, shall be
  reported immediately to the ISSO."`) matched the citation-opener prefix and was discarded whole.
  Fixing this wasn't a simple end-of-string anchor — real citations legitimately contain internal
  commas/periods (document numbers, titles), so the two real target examples (`REQ-4523443092b8`,
  `REQ-e0471aa64a63`) would have broken under a naive `$`-anchored fix too (verified directly — the
  reviewer's own suggested regex failed both).
  **Round 1 fix (wrong in a way the same review round didn't catch):** checked whether anything after
  "as defined in" contained an obligation verb from a small local list
  (`shall`/`must`/`will`/`should`/`may`/etc.). **Round 2 (Gemini, re-reviewing the fix commit):**
  this was backwards-fragile — *any* real obligation verb missing from the list (Gemini's example:
  `"...as defined in Executive Order 13556, requires safeguarding controls."`, using "requires,"
  not in the list) still found nothing, which made the function return `True` (citation-only) and
  silently discard the real requirement. A verb whitelist can never be exhaustive enough to make that
  failure direction safe, no matter how many verbs get added to it — the actual bug was the whole
  approach, not the specific list. **Final fix:** replaced the verb-whitelist check with a structural
  one — does the remainder after "as defined in" consist *only* of citation-shaped tokens (Title Case
  document titles, ALL-CAPS/mixed acronyms, numeric document IDs, a small closed set of connector
  words) with no ordinary lowercase prose word at all? Real citation reference text in this corpus is
  consistently shaped that way; a real continuing obligation clause is ordinary lowercase prose. This
  doesn't need to recognize every possible obligation verb, only what an ordinary English sentence
  fragment looks like — a much smaller, more robust thing to get right, and verified against every
  false positive found across both review rounds plus two more live-corpus citation examples not in
  the original label set.
- **[High, Codex] `ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS = 6` let real, self-contained short
  directives through**, both a hypothetical (`"(a) Encrypt all stored CUI."`) and a real live-corpus
  record (`REQ-63cdc8363326`, `"(1) Identify individual responsibilities for protecting CUI."`) that
  reads as fully complete and actionable on its own. Lowered to 3 words, which also means
  `"(7) Communicate PPS securely across the DODIN."` (WP-38.1's own original fragment label,
  6-word remainder) no longer gets caught — re-reading it during this fix, it's arguably closer to
  the self-contained shape than the context-dependent one anyway (unlike `"(3) Restrain
  competition."`, whose meaning actually inverts without its "shall not be used to:" governing
  clause). `orphaned_list_item` coverage dropped from 4/12 to 3/12 as a direct result — an accepted,
  correct trade, not a regression.
- **[High, Gemini] `_is_heading_echo()` crashed on `section_title_path=None`** — WP-38.2's ancestry
  loop dropped the original `if not section_title_path: return False` guard, and `for heading in
  None:` raises `TypeError`. Restored the guard.
- **[Medium, Gemini] `_is_dangling_clause()`'s first-word split missed non-space whitespace and
  quote-wrapped copulas** — `split(" ", 1)` only splits on a literal space, and `.strip(".,;:")`
  didn't include quote/bracket characters. Fixed to `split(maxsplit=1)` plus a broader strip set.
- **[Medium, Codex] `eval/verify_wp38_2_rules.py` only failed on false positives**, not on a targeted
  subtype's catch count silently dropping (or a rule being broken/deleted entirely) — added a
  committed per-subtype minimum-catch baseline that now fails the script if coverage regresses.
- **[Medium, Codex] `eval/audit_wp38_1/verify_against_rules.py` pinned the wrong thing** — an earlier
  fix (this same PR) pinned the historical 25-word *constant* but still called the live (now-uncapped)
  `_is_unrepairable_fragment()`, which silently reclassified the 3 original `REAL_GAP` records as
  `SHOULD_BE_CAUGHT_BUT_ISNT` if the script were ever re-run. Fixed by reimplementing the pre-WP-38.2
  predicate locally instead of importing the live function — confirmed the script now reproduces the
  original `{NOT_COVERED_BY_DESIGN: 46, REAL_GAP: 3}` split exactly.

*Round 6 (Gemini, re-reviewing the round-5 fix commit) — four more findings, three real bugs and
one hygiene issue:*
- **[High] ALL-CAPS quotes broke the citation structural check** — `_looks_like_citation_reference()`
  tells a citation token from real prose by checking whether a word's first letter is lowercase;
  meaningless when the whole quote is ALL CAPS (every word "looks like" a citation token regardless
  of what it actually is), so a real ALL-CAPS requirement continuing past its citation
  (`"...SHALL BE REPORTED IMMEDIATELY TO THE ISSO."`) would've been discarded. Fixed by bailing out
  (not citation-only) whenever the remainder is itself all-uppercase — this corpus has no known
  ALL-CAPS body-text requirements today, but the fix costs nothing and closes a real structural gap.
- **[High] The marker+remainder-length tension, raised a third time** — three new hypothetical
  short, complete, marker-prefixed directives (`"(1) Encrypt stored CUI."`, `"(2) Restrict root
  access."`, `"(3) Conduct annual audits."`), all exactly at the 3-word threshold. Weighed explicitly
  against removing the signal outright: two independent full-corpus sweeps (before and after this
  round's fix) found zero actual false positives from this branch, only the one real, verified catch
  (`"(3) Restrain competition."`, 2-word remainder) — a repeatedly-raised but so-far-unconfirmed
  theoretical risk against a signal with a real catch is grounds to narrow further, not necessarily
  remove; a real demonstrated false positive would be grounds to remove it outright. Narrowed
  `ORPHANED_LIST_ITEM_MAX_REMAINDER_WORDS` from 3 to 2 — excludes all three new hypotheticals while
  still catching the one real target. Full reasoning recorded in the constant's own comment so a
  future session doesn't have to re-derive it.
- **[Low] `eval/audit_wp38_1/verify_against_rules.py` still imported the live (WP-38.2-updated)
  `_is_heading_echo()`** — the same class of gap as the earlier `_is_unrepairable_fragment` fix
  (Codex, this same PR), just not caught for the second predicate at the time. Reimplemented the
  pre-WP-38.2 heading-echo predicate locally too — confirmed the script still reproduces the original
  `{NOT_COVERED_BY_DESIGN: 46, REAL_GAP: 3}` split.
- **[Medium, hygiene] Missing `encoding="utf-8"` and bare (non-context-manager) `open()` calls**
  across `eval/verify_wp38_2_rules.py` and the WP-38.1 audit scripts — real risk on a platform whose
  default encoding isn't UTF-8. Fixed every instance found across all four WP-38 eval scripts in one
  pass (grepped for the pattern, not just the one file flagged), not just the file Gemini's finding
  named.

All fixes re-verified against both the fixture (`eval/verify_wp38_2_rules.py`, still 0 regressions /
0 scope violations / 0 coverage regressions) and a fresh full-live-corpus sweep before considering
this WP done — the numbers throughout this Findings section are the post-fix, final ones.

*Not done, by design:* the corpus was not re-ingested and Qdrant was not reindexed as part of this
WP — these rules only affect *future* Step D runs. Existing indexed data is unaffected until the
next re-ingest. Re-ingesting the corpus to apply these rules retroactively is a separate decision,
not assumed here (matches this WP's Non-Goals: not touching indexed data).

---

## 5. Backlog — Over-Grab Precision (deferred, not WP-38.2)

WP-38.1 found genuine over-grab failures (descriptive/definitional prose, reference-only pointers,
explicit "examples of..." text, acknowledgment-template text) at 5.7% of the audited sample
unweighted (5.8% population-weighted; 19/333 records) — real, but requiring actual reading
comprehension to distinguish from real requirements,
not a text pattern a deterministic rule can key on. Per the Guardrails below and this project's
established preference for the cheapest fix that actually works: **not building a classifier now.**
Revisit after WP-38.2 ships, re-measuring the over-grab rate on the post-fix corpus (WP-38.2's rule
extensions don't touch this category, so the rate itself won't move — but re-measuring confirms it's
still real before committing to a bigger build). If still material, the original proposal's shape
(a small second-stage classifier, trained on this project's own documents — DoD/AF corpus preferred
over off-theme sourcing like NIST 800-53/800-53A per the Phase Framing note above, validated on
precision *and* recall against a freshly hand-verified set, not `eval/gold_eval_chunks*.jsonl`
as-is) is still the right shape if and when it's scoped.

---

## 6. Success Gate

- [x] WP-38.1's audit is complete: real counts, real categories, real examples, a grounded
      recommendation — not assumed from the original diagnosis alone. (333-record hand-labeled
      unbiased sample + 183-record discovery pool, both committed at `eval/audit_wp38_1/`.)
- [x] The recommendation is acted on: either a properly-scoped WP-38.2 (classifier or rule extension,
      per what the evidence actually supports), **or**, if WP-38.1's evidence supports it, a documented
      conclusion that no further action is warranted — that's an equally valid, equally evidenced
      outcome of this phase, not a failure to close it (corrected after Codex review, PR #179: the
      original wording here could never be satisfied by the "negligible rate, no action needed"
      conclusion the Goals and WP-38.1 Scope both explicitly allow for). (WP-38.2 properly scoped as
      a rule-extension WP above; over-grab classifier question explicitly deferred to backlog with a
      documented re-measurement trigger, not silently dropped. WP-38.2 itself shipped, not just
      scoped — see its own Findings above.)
- [x] Full `pytest` suite and `ruff check .` clean throughout. (775 tests passed, including 13 new
      for WP-38.2's rule functions; `ruff check .` clean.)

## 7. Guardrails

- No classifier gets built on the assumption that the "precision problem" diagnosis is correct at an
  unknown scale — WP-38.1's real numbers decide that, not the spark notes alone.
- Every audit finding gets checked against a freshly re-ingested or at least timestamp-verified-current
  copy of the source document — stale pre-Phase-34 data doesn't count as evidence of a current
  problem (found and corrected during this phase's own scoping, see Phase Framing).
- Don't validate anything against `eval/gold_eval_chunks*.jsonl` without first auditing it.
- Cheapest fix wins: if WP-38.1 shows most failures are catchable by extending the existing
  deterministic rules, don't build a trained classifier just because it was the original proposal —
  follow the evidence, the same discipline that reverted WP-37.2 rather than shipping a regression.

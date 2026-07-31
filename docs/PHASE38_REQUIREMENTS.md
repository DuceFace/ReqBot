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
| WP-38.1 — Extraction Precision Failure Audit | Not started |
| WP-38.2 — Precision Filter or Targeted Rule Extensions (brainstorm only, scope TBD) | Not started |

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
2. **Data-sourcing check, done directly rather than assumed:** the proposal named NIST 800-53,
   800-53A, and PCI DSS as label-data sources. Checked `raw_pdfs/` directly — `NIST.SP.800-53r5.pdf`
   and `NIST.SP.800-53Ar5.pdf` already exist there (not currently ingested into the live corpus, but
   available). No PCI DSS document exists anywhere in this project; it would need external sourcing,
   and using more of ReqBot's own actual target corpus may be a better source of negative examples
   than an off-theme document.
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

---

### WP-38.2 — Precision Filter or Targeted Rule Extensions (brainstorm only — not locked)

**Deliberately not fully scoped.** Writing a hard Scope/Gate for a classifier before knowing the real
failure rate and shape would repeat the exact mistake Phase 37's WP-37.2 exists as a lesson against —
a plausible-sounding technique that, tested for real, didn't hold up. This section is a sketch of the
two shapes this WP could take, to be finalized once WP-38.1 reports in.

- **If WP-38.1 finds a meaningful, non-trivial rate of genuine over-grab/fragment failures not
  already coverable by cheap rule extensions:** build a small second-stage classifier, matching the
  original proposal's shape (recall-oriented 8B extractor stays as-is; a cheap, precision-oriented
  classifier filters its output). Training data: a labeled yes/real-requirement vs. no/near-miss set
  built from this project's own documents — NIST 800-53/800-53A are available as uningested raw PDFs
  (`raw_pdfs/`); PCI DSS would need external sourcing if still wanted, though more of ReqBot's own
  actual target corpus (the DoD/AF documents already present) may be a better negative-example source
  than an off-theme document. Validate on both precision *and* recall (the documented failure mode:
  an overly aggressive filter starts discarding true positives too) against a freshly hand-verified
  label set — explicitly not `eval/gold_eval_chunks*.jsonl` as-is.
- **If WP-38.1 finds the failures are mostly already coverable by extending existing deterministic
  rules** (e.g., relaxing `_is_unrepairable_fragment()`'s colon-only trigger to also catch short,
  no-modal-verb phrase fragments; extending `skip_sections`) — scope a much smaller, cheaper
  rule-extension WP instead. No classifier, no training data, no new dependency.
- **Either way: `eval/eval_harness.py` cannot be used to verify this as-is (Codex review, PR #179,
  verified directly against the code) — it loads each document's `*_extracted_requirements.jsonl`,
  the raw Step C output, before `_is_unrepairable_fragment()`/`_is_heading_echo()` even run in Step D
  and before any post-extraction classifier WP-38.2 might add. Scoring that file would show zero
  change regardless of whether the filter helps, hurts, or does nothing — it isn't measuring the
  artifact the filter touches.** Whichever WP-38.2 shape gets built, either extend
  `eval/eval_harness.py` to score the correct later-stage artifact (post-Step-D for a rule extension,
  post-filter for a classifier) or build an equivalent harness pointed at it — decide which as part of
  scoping WP-38.2 itself, not assumed here. Re-verify precision *and* recall against that corrected
  target (and, separately, `eval/gold_eval_chunks*.jsonl`'s own ground-truth concerns still apply if
  reused) before calling this phase done — same "measure before declaring victory" discipline as every
  other phase in this project.

---

## 5. Success Gate

- [ ] WP-38.1's audit is complete: real counts, real categories, real examples, a grounded
      recommendation — not assumed from the original diagnosis alone.
- [ ] The recommendation is acted on: either a properly-scoped WP-38.2 (classifier or rule extension,
      per what the evidence actually supports), **or**, if WP-38.1's evidence supports it, a documented
      conclusion that no further action is warranted — that's an equally valid, equally evidenced
      outcome of this phase, not a failure to close it (corrected after Codex review, PR #179: the
      original wording here could never be satisfied by the "negligible rate, no action needed"
      conclusion the Goals and WP-38.1 Scope both explicitly allow for).
- [ ] Full `pytest` suite and `ruff check .` clean throughout.

## 6. Guardrails

- No classifier gets built on the assumption that the "precision problem" diagnosis is correct at an
  unknown scale — WP-38.1's real numbers decide that, not the spark notes alone.
- Every audit finding gets checked against a freshly re-ingested or at least timestamp-verified-current
  copy of the source document — stale pre-Phase-34 data doesn't count as evidence of a current
  problem (found and corrected during this phase's own scoping, see Phase Framing).
- Don't validate anything against `eval/gold_eval_chunks*.jsonl` without first auditing it.
- Cheapest fix wins: if WP-38.1 shows most failures are catchable by extending the existing
  deterministic rules, don't build a trained classifier just because it was the original proposal —
  follow the evidence, the same discipline that reverted WP-37.2 rather than shipping a regression.

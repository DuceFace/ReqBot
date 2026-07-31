#!/usr/bin/env python3
"""WP-39.1: hand-classified loss-category for each of the 18 known FRAGMENT examples,
from reading trace_examples.py's output (chunk raw_text, ancestry, Step C output) by
hand -- same discipline as eval/audit_wp38_1/verify_against_rules.py's own LABELS dict.

Categories (see docs/PHASE39_REQUIREMENTS.md's WP-39.1 Findings for the full writeup):
  SAME_CHUNK_STEM_EXTRACTED   -- the stem/main clause is a separate Step C record in the
                                 same chunk; cheapest fix (proximity reconstruction against
                                 already-extracted Step C records, no LLM/chunking change).
  STEM_NEVER_EXTRACTED        -- the needed text is present in the chunk's raw_text but
                                 Step C never extracted it as any record at all (truncated
                                 mid-sentence or skipped) -- needs either a Step C prompt
                                 fix or reconstruction directly from raw chunk text.
  CROSS_CHUNK_SPLIT           -- the stem is in a *different* (preceding) chunk --
                                 confirmed by checking the adjacent chunk directly.
  HEADING_IS_SUBJECT          -- the missing "stem" is really the section heading itself
                                 (parent_header_text) -- already computed, already flows
                                 through every chunk record today, zero new engineering
                                 needed to access it.
  GARBLED_TABLE               -- chunk text is mangled/flattened tabular content, not a
                                 clean stem sentence -- no simple parent_stem field fixes
                                 this; would need table-structure-aware handling.
  AMBIGUOUS_MAY_NOT_BE_REQ    -- bare noun-phrase topic-list item; unclear a parent_stem
                                 even makes this an actionable requirement (closer to
                                 descriptive/topic content).
  CITATION_ONLY_NOT_A_TARGET  -- a "<term>, as defined in <citation>" pointer -- correctly
                                 non-actionable already (WP-38.2's own rule), not a
                                 reconstruction candidate at all.
"""
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LABELS = {
    "REQ-4aeeff50f15b": ("STEM_NEVER_EXTRACTED", "Step C truncated the sentence before its main clause; the continuation ('the Director...develops implementing guidance...') is present verbatim in chunk raw_text but was never extracted as any record."),
    "REQ-c62e41aaf181": ("SAME_CHUNK_STEM_EXTRACTED", "Main clause ('establish, direct, and administer...') is R-14-0, same chunk."),
    "REQ-8105d9acb410": ("STEM_NEVER_EXTRACTED", "The real subject+verb clause ('...the Director, Defense Counterintelligence and Security Agency:') was never extracted as its own record, though present in raw_text."),
    "REQ-1cc75ab1ae84": ("STEM_NEVER_EXTRACTED", "The 'if:' stem ('CUI not controlled as NOFORN may be released...if:') is present in raw_text but not extracted as its own Step C record."),
    "REQ-1b1071c8d317": ("HEADING_IS_SUBJECT", "parent_header_text is '2.2. Directorate of Security, Special Access Program Oversight and Information Protection (SAF/AAZ).' -- the office name is the implicit subject; no separate stem sentence exists in the source document at all."),
    "REQ-9700722b04cd": ("SAME_CHUNK_STEM_EXTRACTED", "Main clause ('Denies/terminates DISN LHC requests...') is R-25-0, same chunk. Retrieval check: +0.264 similarity with a realistic query -- the largest gain of the 3 tested, consistent with the bare quote being nearly content-free alone."),
    "REQ-626b98fef9aa": ("SAME_CHUNK_STEM_EXTRACTED", "Stem ('Information will not be classified...in order to:') is R-2-3, same chunk."),
    "REQ-c6aeb8df528b": ("SAME_CHUNK_STEM_EXTRACTED", "Same stem as REQ-626b98fef9aa (R-2-3), same chunk. Retrieval check: +0.037 similarity with a realistic query."),
    "REQ-3097aa5d306c": ("SAME_CHUNK_STEM_EXTRACTED", "Stem ('NM SLAs shall at a minimum address the following areas...') is R-31-1, same chunk."),
    "REQ-c6d23854cd0b": ("SAME_CHUNK_STEM_EXTRACTED", "Stem ('NM SLAs and other agreements shall establish baseline...') is R-34-3, same chunk."),
    "REQ-48f549669bb2": ("CROSS_CHUNK_SPLIT", "Confirmed directly (Codex review, PR #183: the original note only established the stem was absent from chunk 33, not that it was present one hop back -- checked chunk 32 explicitly): stem is '(5) How NM service levels will be monitored and reported...This section will define for all parties:' followed by '(a) The characteristics of the NM information to be exchanged...', in chunk_id=32; this item, '(b) Required NM data update rates.', continues the same (a)/(b)/(c)... sub-enumeration in chunk_id=33 -- confirmed one hop back, same as REQ-cf527f39c8d7."),
    "REQ-7464da5820b8": ("SAME_CHUNK_STEM_EXTRACTED", "Same stem as REQ-c6d23854cd0b (R-34-3), same chunk."),
    "REQ-cf527f39c8d7": ("CROSS_CHUNK_SPLIT", "Confirmed directly: stem ('b. Oversee their respective Component's PPSM program to:') is in chunk_id=12; this item ('(7) Communicate PPS securely...') is in chunk_id=13 -- a different chunk entirely."),
    "REQ-4523443092b8": ("CITATION_ONLY_NOT_A_TARGET", "'<term>, as defined in <citation>' pointer -- WP-38.2's _is_definitional_citation_only() already correctly rejects this; not a fragment needing reconstruction."),
    "REQ-364e0be72ebb": ("AMBIGUOUS_MAY_NOT_BE_REQ", "Bare noun-phrase item ('Overview of programmatic and policy updates or changes.') under a training-program topic list -- unclear this is an obligation at all, closer to descriptive/topic content than a requirement missing context."),
    "REQ-e0471aa64a63": ("CITATION_ONLY_NOT_A_TARGET", "Same shape as REQ-4523443092b8."),
    "REQ-5c349cdc3656": ("GARBLED_TABLE", "Chunk raw_text is mangled/flattened tabular content (a table's rows and columns collapsed into run-on prose) -- no clean stem sentence exists to recover."),
    "REQ-68e7c7d2ba86": ("GARBLED_TABLE", "Same garbled chunk as REQ-5c349cdc3656."),
}


def summarize():
    from collections import Counter
    counts = Counter(cat for cat, _ in LABELS.values())
    print(f"Total classified: {len(LABELS)}\n")
    for cat, n in counts.most_common():
        print(f"  {cat:28s} {n}")
    print()
    for rid, (cat, note) in LABELS.items():
        print(f"{rid}  [{cat}]")
        print(f"  {note}")
    return counts


def retrieval_check():
    """Real embedding-similarity check via Ollama nomic-embed-text -- not simulated.

    Uses the project's own config loader (core.config.load(), the same
    ~/.config/reqbot/config.json + REQBOT_OLLAMA_URL/REQBOT_EMBEDDING_MODEL resolution
    every other reqbot command uses) instead of a hardcoded host -- a hardcoded
    192.168.90.100 IP only works on this specific environment and breaks portability
    (Gemini review, PR #183).
    """
    import ollama

    from core import config as reqbot_config

    cfg = reqbot_config.load()
    client = ollama.Client(host=cfg.ollama_url)

    def embed(text: str) -> list[float]:
        return client.embed(model=cfg.embedding_model, input=text).embeddings[0]

    def cos(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    cases = [
        {
            "name": "REQ-c6aeb8df528b (SAME_CHUNK_STEM_EXTRACTED, list item)",
            "bare": "(3) Restrain competition.",
            "with_stem": (
                "Information will not be classified, continue to be maintained as "
                "classified, or fail to be declassified, or be designated CUI under "
                "any circumstances in order to: (3) Restrain competition."
            ),
            "query": "Can classification be used to restrain competition or limit competitive bidding?",
        },
        {
            "name": "REQ-1b1071c8d317 (HEADING_IS_SUBJECT)",
            "bare": (
                "Is designated Computer Network Defense Service Provider (CNDSP) "
                "Certification Authority (CA) for Special Access Program (SAP) "
                "networks and is responsible for coordinating and directing SAP "
                "enclave-wide CNDSP activities."
            ),
            "with_stem": (
                "Directorate of Security, Special Access Program Oversight and "
                "Information Protection (SAF/AAZ): Is designated Computer Network "
                "Defense Service Provider (CNDSP) Certification Authority (CA) for "
                "Special Access Program (SAP) networks and is responsible for "
                "coordinating and directing SAP enclave-wide CNDSP activities."
            ),
            "query": "Who is the CNDSP certification authority for Special Access Program networks?",
        },
        {
            "name": "REQ-9700722b04cd (SAME_CHUNK_STEM_EXTRACTED, sentence continuation)",
            "bare": "shall be coordinated with the customer",
            "with_stem": (
                "Denies/terminates DISN LHC requests when it is in the best "
                "interest of the AF. This activity will not be accomplished "
                "indiscriminately and shall be coordinated with the customer."
            ),
            "query": "What is required before denying or terminating a DISN long haul communications request?",
        },
    ]

    print("\n--- Retrieval check (real nomic-embed-text embeddings, not simulated) ---\n")
    for c in cases:
        q = embed(c["query"])
        bare = embed(c["bare"])
        stem = embed(c["with_stem"])
        bare_sim, stem_sim = cos(q, bare), cos(q, stem)
        print(c["name"])
        print(f"  bare quote similarity:       {bare_sim:.4f}")
        print(f"  with parent-stem similarity: {stem_sim:.4f}")
        print(f"  delta: {stem_sim - bare_sim:+.4f}")
        print()


if __name__ == "__main__":
    summarize()
    try:
        retrieval_check()
    except Exception as e:
        print(f"\nRetrieval check skipped (Ollama unreachable?): {e}")

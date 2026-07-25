#!/usr/bin/env python3
"""Query GRC requirements using natural language via Qdrant vector search.

Usage:
    python ask.py "What are the access control requirements?"
    python ask.py "audit log retention" --domain-tag audit-and-logging
    python ask.py "encryption requirements" --synthesize --model qwen2.5:14b

Default mode is retrieve-only (shows matching requirements).
Use --synthesize to get an LLM-generated answer with citations.
"""

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

# Ensure repo root is on sys.path when run as a standalone script from core/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import ollama
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

COLLECTION_NAME = "grc_requirements"
CONTEXT_COLLECTION_NAME = "grc_context"
EMBEDDING_MODEL = "nomic-embed-text"
SPARSE_MODEL = "Qdrant/bm25"
DEFAULT_SYNTHESIS_MODEL = "qwen2.5:14b"
DEFAULT_REWRITE_MODEL = "llama3.1:8b-instruct-q4_K_M"

from core import constants as _const
CONTEXT_UUID_NAMESPACE = _const.CONTEXT_UUID_NS

# Query rewrite prompt — forces JSON output via Ollama's format="json" mode.
# Temperature 0 keeps output deterministic. {valid_tags} is injected at call time
# from VALID_DOMAIN_TAGS so the prompt never drifts from the actual tag set.
QUERY_REWRITE_PROMPT = """You are a GRC (Governance, Risk, Compliance) search assistant. Analyze the question and return ONLY a JSON object with these fields:

- "expanded_query": A single, keyword-dense search phrase that expands acronyms and adds precise technical terminology. No full sentences — just tightly packed relevant terms.
- "control_ids": List of specific control IDs explicitly mentioned or strongly implied (e.g. ["AC-3", "IA-5(1)", "AU-9"]). Empty list if none.
- "domain_tags": List of relevant tags from ONLY this set: {valid_tags}. Empty list if unclear.

Return ONLY valid JSON. No explanation, no markdown, no other text.

QUESTION: {question}"""

# Valid filter values (must match parse_and_normalize.py)
VALID_DOMAIN_TAGS = {
    "access-control", "authentication-and-identity", "audit-and-logging",
    "configuration-management", "contingency-and-recovery",
    "data-protection-and-encryption", "incident-response", "maintenance",
    "media-protection", "network-security", "personnel-security",
    "physical-security", "privacy", "risk-management", "security-assessment",
    "supply-chain-security", "system-integrity", "training-and-awareness",
}

VALID_REQUIREMENT_TYPES = {
    "policy", "technical-control", "procedural-control", "assessment", "guidance",
}

# HyDE prompt — generates a single hypothetical requirement statement in corpus register.
# Explicitly prohibits control IDs and numeric thresholds to avoid introducing fabricated
# identifiers (e.g. "IA-5(1)", "15 characters") that can distort retrieval relevance.
HYDE_PROMPT = """Given this compliance question, write a single regulatory requirement statement that would answer it. Use formal language matching DoD/NIST style. Do NOT include specific control IDs, section numbers, or numeric thresholds. Describe only the semantic intent of the requirement.

Question: {question}

Requirement:"""

SYNTHESIS_PROMPT = """You are a GRC (Governance, Risk, Compliance) analyst. Answer the user's question using ONLY the evidence provided below. Follow these rules strictly:

1. Every claim must cite the evidence by number: [N]
2. Include the source reference and page numbers in citations: [N] (source_ref, pages X-Y)
3. If the evidence does not directly support a claim, say "not supported by retrieved sources"
4. If the evidence is insufficient to answer the question fully, say so explicitly
5. Do not infer or add information beyond what the evidence states
6. Organize your answer clearly with bullet points or numbered items

EVIDENCE:
{evidence}

QUESTION: {question}

ANSWER:"""


def normalize_filter_value(value: str) -> str:
    """Normalize a filter value to canonical form (lowercase, hyphens)."""
    return value.strip().lower().replace(" ", "-").replace("_", "-")


def build_query_filter(
    domain_tags: list[str] | None,
    requirement_types: list[str] | None,
    document_ids: list[str] | None,
) -> models.Filter | None:
    """Build a Qdrant filter from CLI arguments."""
    conditions = []

    if domain_tags:
        normalized = [normalize_filter_value(t) for t in domain_tags]
        for tag in normalized:
            if tag not in VALID_DOMAIN_TAGS:
                log.warning("Unknown domain tag '%s' — will filter anyway", tag)
        conditions.append(
            models.FieldCondition(
                key="domain_tags",
                match=models.MatchAny(any=normalized),
            )
        )

    if requirement_types:
        normalized = [normalize_filter_value(t) for t in requirement_types]
        for rt in normalized:
            if rt not in VALID_REQUIREMENT_TYPES:
                log.warning("Unknown requirement type '%s' — will filter anyway", rt)
        conditions.append(
            models.FieldCondition(
                key="requirement_type",
                match=models.MatchAny(any=normalized),
            )
        )

    if document_ids:
        conditions.append(
            models.FieldCondition(
                key="source_pdf",
                match=models.MatchAny(any=document_ids),
            )
        )

    if not conditions:
        return None

    return models.Filter(must=conditions)


def resolve_document_ids(
    client: QdrantClient, document_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Resolve caller-supplied document_ids (doc_key or source_pdf form) against
    what's actually indexed in the grc_requirements collection.

    Validates against the live collection, not the processed_dir JSONL directory
    (Codex review, PR #119) — a document ingested via `reqbot ingest --output-dir`
    or indexed via `reqbot index <arbitrary.jsonl>` can be fully searchable while
    living outside the configured processed_dir, and conversely a JSONL sitting in
    processed_dir may never have been indexed. The Qdrant collection is the only
    thing that reflects what a query can actually match, so it's the only correct
    source of truth for this check.

    A value is accepted only if `client.count()` confirms a point exists with
    that *exact* source_pdf value — either the value as given, or (only if that
    exact check fails) `value + ".pdf"` or `value + ".PDF"` when value doesn't
    already end in .pdf/.PDF. Both extension-case candidates are tried because
    `compute_document_identity()` preserves the original filename verbatim
    (`pipeline/parse_and_normalize.py`) and `reqbot batch` explicitly globs
    both `*.pdf` and `*.PDF` (`cli/reqbot.py`'s `cmd_batch`) -- a document
    ingested from an uppercase-extension file has a literal `.PDF` source_pdf,
    and appending only a lowercase `.pdf` candidate would never match it,
    wrongly rejecting a real bare doc_key as unknown (Codex review, PR #121).
    Each candidate is checked and confirmed individually before being used as
    the resolved value (Codex review, PR #119) — checking multiple forms in
    one combined query and then blindly resolving to a specific suffixed form
    regardless of which one actually matched would silently rewrite the filter
    to a value that doesn't exist in Qdrant whenever a document's real
    source_pdf doesn't have that exact suffix, producing the exact
    silent-empty-result bug this validation exists to eliminate. Never
    fabricated for an unrecognized value. Uses an exact count (not the faster
    approximate mode) because this is a validation gate: a false "not found"
    here would wrongly reject a real, searchable document.

    Returns (resolved_source_pdfs, unknown_values).
    """
    resolved: list[str] = []
    unknown: list[str] = []
    for value in document_ids:
        candidates = [value]
        if not value.lower().endswith(".pdf"):
            candidates.append(f"{value}.pdf")
            candidates.append(f"{value}.PDF")

        matched: str | None = None
        for candidate in candidates:
            count = client.count(
                collection_name=COLLECTION_NAME,
                count_filter=models.Filter(
                    must=[models.FieldCondition(key="source_pdf", match=models.MatchValue(value=candidate))]
                ),
                exact=True,
            ).count
            if count > 0:
                matched = candidate
                break

        if matched is not None:
            resolved.append(matched)
        else:
            unknown.append(value)
    return resolved, unknown


def retrieve_context_chunks(
    results: list,
    client: QdrantClient,
    context_collection: str = CONTEXT_COLLECTION_NAME,
) -> dict[str, dict]:
    """Retrieve raw context chunks for a set of requirement hits.

    For each hit, computes the deterministic point ID from (document_id, chunk_id)
    and batch-retrieves those exact points from grc_context. This is a direct
    lookup — no embedding or search needed at query time.

    Returns a dict mapping point_id -> chunk payload. Points not found in
    grc_context are silently skipped (collection may not be built yet).
    """
    seen_ids: set[str] = set()
    point_ids: list[str] = []
    for hit in results:
        doc_id = hit.payload.get("document_id", "")
        chunk_id = hit.payload.get("chunk_id")
        if doc_id and chunk_id is not None:
            pid = str(uuid.uuid5(CONTEXT_UUID_NAMESPACE, f"{doc_id}:{chunk_id}"))
            if pid not in seen_ids:
                seen_ids.add(pid)
                point_ids.append(pid)

    if not point_ids:
        return {}

    retrieved = client.retrieve(
        collection_name=context_collection,
        ids=point_ids,
        with_payload=True,
    )
    return {point.id: point.payload for point in retrieved}


def _context_text_for_hit(hit, context_map: dict | None, window: int = 300) -> str | None:
    """Look up the raw chunk text for a hit and extract a window around the source_quote.

    Locates the source_quote inside the raw chunk text and returns up to `window`
    characters before and after it, so the LLM sees the sentence that contains the
    obligation rather than unrelated introductory text from the top of the chunk.

    Falls back to the first 2*window characters if the quote is not found in the chunk
    (e.g. quote was truncated during extraction).
    """
    if not context_map:
        return None
    doc_id = hit.payload.get("document_id", "")
    chunk_id = hit.payload.get("chunk_id")
    if not doc_id or chunk_id is None:
        return None
    pid = str(uuid.uuid5(CONTEXT_UUID_NAMESPACE, f"{doc_id}:{chunk_id}"))
    payload = context_map.get(pid)
    if not payload:
        return None
    ctx = payload.get("text", "")
    if not ctx:
        return None

    # Try to center the window on the exact source_quote
    quote = hit.payload.get("source_quote", "")
    if quote and quote in ctx:
        idx = ctx.find(quote)
        start = max(0, idx - window)
        end = min(len(ctx), idx + len(quote) + window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(ctx) else ""
        return prefix + ctx[start:end] + suffix

    # Fallback: top of chunk when quote is absent or truncated
    if len(ctx) > window * 2:
        return ctx[:window * 2] + "..."
    return ctx


def format_evidence(results: list[dict]) -> str:
    """Format result dicts as numbered evidence for the LLM.

    Expects dicts from retrieve() — each dict has score + payload fields,
    and optionally context_text if context=True was passed to retrieve().
    """
    lines = []
    for i, hit in enumerate(results, 1):
        page_info = ""
        if hit.get("page_start") and hit.get("page_end"):
            if hit["page_start"] == hit["page_end"]:
                page_info = f"p.{hit['page_start']}"
            else:
                page_info = f"pp.{hit['page_start']}-{hit['page_end']}"

        ref = hit.get("source_ref", "")
        source = hit.get("source_pdf", "")
        cite_parts = [x for x in [source, ref, page_info] if x]
        cite = ", ".join(cite_parts)

        primary = hit.get("description") or hit.get("source_quote", "")
        entry = (
            f"[{i}] ({cite})\n"
            f"    Type: {hit.get('requirement_type', 'unknown')}\n"
            f"    Tags: {', '.join(hit.get('domain_tags', []))}\n"
            f"    Requirement: {primary}\n"
            f"    Quote: {hit.get('source_quote', '')}"
        )
        ctx = hit.get("context_text")
        if ctx:
            entry += f"\n    Context: {ctx}"
        lines.append(entry)
    return "\n\n".join(lines)


def print_results_table(results: list[dict]) -> None:
    """Print search results as a readable table.

    Expects dicts from retrieve() — each dict has score + payload fields,
    and optionally context_text if context=True was passed to retrieve().
    """
    print(f"\n{'='*80}")
    print(f"Retrieved {len(results)} requirements (ranked by relevance)")
    print(f"{'='*80}\n")

    for i, hit in enumerate(results, 1):
        score = hit.get("score", 0)

        page_info = ""
        if hit.get("page_start") and hit.get("page_end"):
            if hit["page_start"] == hit["page_end"]:
                page_info = f"p.{hit['page_start']}"
            else:
                page_info = f"pp.{hit['page_start']}-{hit['page_end']}"

        ref = hit.get("source_ref", "")
        source = hit.get("source_pdf", "")

        print(f"[{i}] Score: {score:.4f} | {hit.get('requirement_id', '?')}")
        if source or ref or page_info:
            cite_parts = [x for x in [source, ref, page_info] if x]
            print(f"    Source: {', '.join(cite_parts)}")
        print(f"    Type: {hit.get('requirement_type', 'unknown')} | Tags: {', '.join(hit.get('domain_tags', []))}")
        primary = hit.get("description") or hit.get("source_quote", "")
        print(f"    {primary}")
        if hit.get("source_quote") and hit.get("description"):
            quote = hit["source_quote"]
            if len(quote) > 120:
                quote = quote[:120] + "..."
            print(f"    Quote: \"{quote}\"")
        ctx = hit.get("context_text")
        if ctx:
            print(f"    Context: {ctx}")
        print()


def rewrite_query(question: str, model: str, client: ollama.Client) -> dict:
    """Use a fast LLM to expand the query and extract structured filters.

    Returns a dict with:
      expanded_query  - clean keyword-dense phrase for dense (semantic) embedding
      control_ids     - list of control IDs to append for BM25 boosting only
      domain_tags     - auto-detected domain tags (logged only; never applied as a
                        filter — user-supplied --domain-tag flags are the filter path)

    Falls back to the original question on any failure — never raises.
    """
    fallback = {"expanded_query": question, "control_ids": [], "domain_tags": []}
    try:
        prompt = QUERY_REWRITE_PROMPT.format(
            question=question,
            valid_tags=", ".join(sorted(VALID_DOMAIN_TAGS)),
        )
        response = client.generate(
            model=model,
            prompt=prompt,
            format="json",
            options={"temperature": 0.0, "num_predict": 256},
        )
        raw = response.response.strip()
        # Strip markdown fences that some models emit despite format="json"
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
        expanded = result.get("expanded_query", "").strip()
        if not expanded:
            return fallback
        control_ids = [str(c).strip() for c in result.get("control_ids", []) if c]
        domain_tags = [t for t in result.get("domain_tags", []) if t in VALID_DOMAIN_TAGS]
        return {"expanded_query": expanded, "control_ids": control_ids, "domain_tags": domain_tags}
    except Exception as e:
        log.warning("Query rewrite failed (%s) — falling back to original query", e)
        return fallback


def generate_hyde_hypothesis(
    question: str,
    model: str,
    client: ollama.Client,
    log_file: str = "hyde_hypotheses.jsonl",
    enabled: bool = False,
) -> str | None:
    """Generate a hypothetical requirement statement for HyDE dense retrieval.

    Embeds the hypothesis instead of (or in addition to) the raw query so the
    dense vector aligns with answer-shaped corpus text rather than question-shaped
    query text.

    HyDE is now default-on retrieval augmentation, so hypothesis logging to
    log_file is opt-in via `enabled` (wired from --hyde-debug-log on core/ask.py's
    standalone CLI) — normal default-on usage must not write to disk on every
    query. Empty responses and generation failures are never logged regardless
    of `enabled`; caller receives None and falls back to baseline retrieval.
    """
    import time
    try:
        response = client.generate(
            model=model,
            prompt=HYDE_PROMPT.format(question=question),
            options={"temperature": 0.3, "num_predict": 150},
        )
        hypothesis = response.response.strip()
        if not hypothesis:
            log.warning("HyDE: model returned empty hypothesis — skipping HyDE leg")
            return None
        log.debug("HyDE hypothesis: %s", hypothesis[:120] + ("..." if len(hypothesis) > 120 else ""))
        if enabled:
            try:
                with open(log_file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "query": question,
                        "hypothesis": hypothesis,
                        "model": model,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }, ensure_ascii=False) + "\n")
            except Exception as log_err:
                log.warning("HyDE: failed to write hypothesis log (%s)", log_err)
        return hypothesis
    except Exception as e:
        log.warning("HyDE: hypothesis generation failed (%s) — skipping HyDE leg", e)
        return None


def synthesize_answer(
    question: str,
    evidence: str,
    model: str,
    client: ollama.Client,
    *,
    backend: str = "local",
    provider: str = "anthropic",
    api_key: str = "",
    ollama_url: str = "",
) -> str:
    """Send evidence to LLM for synthesis with grounding safeguards.

    Routes to synthesis.py for pluggable local/remote backend support.
    Falls back to direct Ollama call if synthesis module is unavailable.
    """
    try:
        from core import synthesis as _syn
        return _syn.synthesize(
            question=question,
            evidence=evidence,
            backend=backend,
            model=model,
            ollama_url=ollama_url or str(client._client.base_url).rstrip("/"),
            provider=provider,
            api_key=api_key,
        )
    except ImportError:
        # Fallback: direct Ollama call (synthesis.py not present)
        log.info("Synthesizing answer with model: %s", model)
        prompt = SYNTHESIS_PROMPT.format(evidence=evidence, question=question)
        response = client.generate(
            model=model,
            prompt=prompt,
            options={"temperature": 0.2, "num_predict": 2048},
        )
        return response.response


def _embedding_mismatch_warnings(result_dicts: list[dict], configured_embedding_model: str) -> list[str]:
    """Compare each result's indexed embedding_model against the configured one.

    Points indexed before WP-25.6c carry no embedding_model payload field at
    all — those are treated as "nomic-embed-text" (the universal default at
    the time), so an unchanged default config correctly produces no warning
    for a legacy/mixed corpus. Only a real mismatch (config points at a
    different model than what actually indexed a result) triggers a warning.
    Never blocks the query — a partially reindexed corpus is a valid, common
    state, not an error condition (WP-25.6c).
    """
    mismatched_models: set[str] = set()
    mismatched_count = 0
    for d in result_dicts:
        indexed_model = d.get("embedding_model") or "nomic-embed-text"
        if indexed_model != configured_embedding_model:
            mismatched_count += 1
            mismatched_models.add(indexed_model)
    if not mismatched_count:
        return []
    models_str = ", ".join(sorted(mismatched_models))
    return [
        f"{mismatched_count} of {len(result_dicts)} results were indexed with a "
        f"different embedding model ({models_str}) than your current config "
        f"({configured_embedding_model}) and may be unreliable; run 'reqbot reindex' "
        "to refresh them."
    ]


def retrieve(
    question: str,
    *,
    top_k: int = 20,
    min_score: float = 0.02,
    synthesize: bool = False,
    model: str = "",
    synthesis_model: str = DEFAULT_SYNTHESIS_MODEL,
    remote_model: str = "",
    domain_tags: list[str] | None = None,
    requirement_types: list[str] | None = None,
    document_ids: list[str] | None = None,
    no_rewrite: bool = False,
    rewrite_model: str = DEFAULT_REWRITE_MODEL,
    embedding_model: str = EMBEDDING_MODEL,
    qdrant_url: str = "http://localhost:6333",
    ollama_url: str = "http://localhost:11434",
    context: bool = False,
    context_collection: str = CONTEXT_COLLECTION_NAME,
    hyde: bool = True,
    hyde_debug_log: bool = False,
    synthesis_backend: str = "local",
    synthesis_provider: str = "anthropic",
    synthesis_api_key: str = "",
) -> dict:
    """Retrieve matching requirements and optionally synthesize an answer.

    Selects synthesis_model or remote_model internally based on synthesis_backend
    (Phase 27, WP-27.4) -- callers pass both unconditionally rather than picking
    one themselves, mirroring evidence_service.build() (WP-27.2). model is an
    explicit caller override (e.g. --model / AskRequest.model) and always wins
    when set; when unset, falls back to remote_model if synthesis_backend ==
    "remote" and remote_model is non-empty, else synthesis_model. Previously
    run() and ask_service.ask() each pre-resolved a single "model" string using
    only synthesis_model, so a remote-configured backend silently got the local
    Ollama model name.

    Pure data path — no console output. Called by both run() (CLI render layer)
    and ask_service.ask() (API/service layer). All retrieval logic lives here;
    display and rendering stay in the callers.

    Returns a dict:
        results:        list[dict]  score + payload fields; context_text included when context=True
        synthesis_text: str         empty string if synthesize=False or synthesis failed
        expanded_query: str         rewritten query; equals question when no_rewrite=True
        total:          int         number of results after min_score filtering and top_k trim
        retrieval_ms:   int         wall-clock ms from entry to just before synthesis (pure retrieval)
        warnings:       list[str]   e.g. embedding-model mismatch between config and indexed results

    Raises ValueError if document_ids contains a value not indexed in the
    grc_requirements collection (Phase 27, WP-27.1) — a stale or typo'd document
    filter is invalid input, not a weak-search condition, so it errors instead of
    silently returning an empty/reduced result set.
    """
    import time as _time
    _t0 = _time.monotonic()

    qdrant_client = QdrantClient(url=qdrant_url)

    if document_ids:
        resolved_document_ids, unknown_document_ids = resolve_document_ids(
            qdrant_client, document_ids
        )
        if unknown_document_ids:
            raise ValueError(
                "Unknown document_ids (no matching indexed document): "
                + ", ".join(sorted(unknown_document_ids))
            )
        document_ids = resolved_document_ids

    ollama_client = ollama.Client(host=ollama_url)

    # Query rewriting: expand acronyms, extract control IDs and domain hints.
    # dense_query  → clean natural language / keyword phrase for semantic embedding
    # sparse_query → dense_query + control IDs appended for exact BM25 term matching
    dense_query = question
    sparse_query = question
    effective_domain_tags = list(domain_tags) if domain_tags else []
    if not no_rewrite:
        log.info("Rewriting query with model: %s", rewrite_model)
        rewrite = rewrite_query(question, rewrite_model, ollama_client)
        dense_query = rewrite["expanded_query"]
        # Append control IDs only to the sparse (BM25) input — keeps dense embedding clean
        if rewrite["control_ids"]:
            log.info("Detected control IDs: %s", ", ".join(rewrite["control_ids"]))
            sparse_query = dense_query + " " + " ".join(rewrite["control_ids"])
        else:
            sparse_query = dense_query
        if rewrite["domain_tags"] and not effective_domain_tags:
            log.info("Auto-detected domain tags (not applied as filter): %s",
                     ", ".join(rewrite["domain_tags"]))
        if dense_query != question:
            log.info("Expanded query: %s", dense_query)

    # Dense embed — clean semantic phrase only (no keyword stuffing)
    log.info("Embedding question: %s", question)
    dense_result = ollama_client.embed(model=embedding_model, input=dense_query)
    dense_vector = dense_result.embeddings[0]

    # HyDE — generate a hypothetical requirement and embed it as a second dense leg.
    # The hypothesis is intentionally answer-shaped so its embedding aligns more closely
    # with indexed corpus text than the question-shaped query embedding does.
    # BM25 stays on the raw/expanded query — it already handles exact term matching well.
    hyde_vector = None
    if hyde:
        # Use rewrite_model (always a local Ollama model) — not the synthesis model,
        # which may be a remote backend name (e.g. claude-sonnet-4-6) incompatible
        # with a direct ollama.generate() call.
        log.info("HyDE: generating hypothesis with model: %s", rewrite_model)
        hypothesis = generate_hyde_hypothesis(
            question, rewrite_model, ollama_client, enabled=hyde_debug_log,
        )
        if hypothesis:
            try:
                hyde_result = ollama_client.embed(model=embedding_model, input=hypothesis)
                hyde_vector = hyde_result.embeddings[0]
                log.info("HyDE: hypothesis embedded successfully")
            except Exception as e:
                log.warning("HyDE: hypothesis embedding failed (%s) — falling back to baseline", e)
        else:
            log.info("HyDE: no hypothesis — proceeding with baseline retrieval only")

    # Sparse embed — keyword-stuffed string (expanded + control IDs) for BM25
    log.info("Loading sparse embedding model...")
    sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL)
    sparse_emb = next(iter(sparse_model.embed([sparse_query])))
    sparse_vector = models.SparseVector(
        indices=sparse_emb.indices.tolist(),
        values=sparse_emb.values.tolist(),
    )

    # Build filter
    query_filter = build_query_filter(
        effective_domain_tags or None, requirement_types, document_ids,
    )
    if query_filter:
        log.info("Applying filters: %s", query_filter)

    # Hybrid query: dense semantic + sparse BM25 (+ optional HyDE dense leg), fused via RRF.
    # Prefetch a deep pool (at least 100) so RRF sees enough candidates from all legs
    # before fusing — shallow prefetch starves RRF of good matches.
    # Fetch more fused results than top_k so min_score filtering has overflow candidates
    # to draw from — otherwise low-score hits can consume top_k slots before filtering.
    prefetch_limit = max(100, top_k * 5)
    fusion_limit = max(top_k * 3, 50) if min_score > 0 else top_k
    # qdrant_client already created above (needed early for document_ids validation)

    prefetch_legs = [
        models.Prefetch(
            query=dense_vector,
            using="dense",
            filter=query_filter,
            limit=prefetch_limit,
        ),
        models.Prefetch(
            query=sparse_vector,
            using="sparse",
            filter=query_filter,
            limit=prefetch_limit,
        ),
    ]
    if hyde_vector is not None:
        prefetch_legs.append(
            models.Prefetch(
                query=hyde_vector,
                using="dense",
                filter=query_filter,
                limit=prefetch_limit,
            )
        )
        log.info("HyDE: using 3-leg RRF (baseline dense + BM25 + HyDE dense)")

    hits = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=prefetch_legs,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=fusion_limit,
        with_payload=True,
    ).points

    # Score threshold — drop results below min_score, then trim to top_k.
    # Filtering after fusion (not before) ensures the threshold acts on final RRF scores.
    if min_score > 0:
        before = len(hits)
        hits = [r for r in hits if r.score >= min_score]
        dropped = before - len(hits)
        if dropped:
            log.info("Dropped %d result(s) below min_score=%.3f", dropped, min_score)
    hits = hits[:top_k]

    if not hits:
        return {
            "results": [],
            "synthesis_text": "",
            "expanded_query": dense_query,
            "total": 0,
            "retrieval_ms": int((_time.monotonic() - _t0) * 1000),
            "warnings": [],
        }

    # Context retrieval (uses Qdrant hit objects — happens before dict conversion)
    context_map: dict | None = None
    if context:
        log.info("Retrieving context chunks from: %s", context_collection)
        try:
            context_map = retrieve_context_chunks(hits, qdrant_client, context_collection)
            log.info("Retrieved %d context chunk(s)", len(context_map))
            if not context_map:
                log.warning(
                    "No context chunks found — run 'reqbot index-context' to build grc_context"
                )
        except Exception as e:
            log.warning("Context retrieval failed (%s) — proceeding without context", e)

    # Convert hits to dicts, embedding context_text in each result when available
    result_dicts: list[dict] = []
    for hit in hits:
        d: dict = {"score": hit.score, **hit.payload}
        if context_map:
            ctx = _context_text_for_hit(hit, context_map, window=300)
            if ctx:
                d["context_text"] = ctx
        result_dicts.append(d)

    # Checkpoint: everything above this line is pure retrieval.
    _retrieval_ms = int((_time.monotonic() - _t0) * 1000)

    # Synthesis
    synthesis_text = ""
    if synthesize:
        effective_model = model or (
            remote_model if synthesis_backend == "remote" and remote_model else synthesis_model
        )
        evidence = format_evidence(result_dicts)
        synthesis_text = synthesize_answer(
            question, evidence, effective_model, ollama_client,
            backend=synthesis_backend,
            provider=synthesis_provider,
            api_key=synthesis_api_key,
            ollama_url=ollama_url,
        )

    return {
        "results": result_dicts,
        "synthesis_text": synthesis_text,
        "expanded_query": dense_query,
        "total": len(result_dicts),
        "retrieval_ms": _retrieval_ms,
        "warnings": _embedding_mismatch_warnings(result_dicts, embedding_model),
    }


def run(
    question: str,
    *,
    top_k: int = 20,
    min_score: float = 0.02,
    synthesize: bool = False,
    model: str = "",
    domain_tags: list[str] | None = None,
    requirement_types: list[str] | None = None,
    document_ids: list[str] | None = None,
    no_rewrite: bool = False,
    rewrite_model: str = DEFAULT_REWRITE_MODEL,
    embedding_model: str = EMBEDDING_MODEL,
    qdrant_url: str = "http://localhost:6333",
    ollama_url: str = "http://localhost:11434",
    json_output: bool = False,
    context: bool = False,
    context_collection: str = CONTEXT_COLLECTION_NAME,
    hyde: bool = True,
    hyde_debug_log: bool = False,
) -> list[dict]:
    """Query GRC requirements and print results to stdout.

    Thin render wrapper over retrieve(). Loads synthesis config from disk
    and delegates all retrieval + synthesis logic to retrieve().

    model is an explicit caller override (e.g. --model); leave empty to let
    retrieve() select synthesis_model or remote_model based on
    synthesis_backend (Phase 27, WP-27.4).

    Callable by reqbot.py (cmd_ask) and standalone via main() / __main__.
    Returns list of result dicts — identical to what retrieve() returns in
    its "results" key — for any caller that needs the raw data.
    """
    # Load synthesis config from disk when synthesis is requested
    syn_backend = "local"
    syn_provider = "anthropic"
    syn_api_key = ""
    syn_synthesis_model = DEFAULT_SYNTHESIS_MODEL
    syn_remote_model = ""
    if synthesize:
        try:
            from core import config as _cfg_mod
            _cfg_syn = _cfg_mod.load()
            syn_backend = _cfg_syn.synthesis_backend
            syn_provider = _cfg_syn.remote_provider
            syn_synthesis_model = _cfg_syn.synthesis_model
            syn_remote_model = _cfg_syn.remote_model
            if syn_backend == "remote":
                import os as _os
                syn_api_key = _os.environ.get(_cfg_syn.api_key_env, "")
                if not syn_api_key:
                    print(
                        f"[!] Remote synthesis configured but {_cfg_syn.api_key_env} "
                        "is not set — falling back to local",
                        file=sys.stderr,
                    )
                    syn_backend = "local"
            elif syn_backend == "none":
                print(
                    "[!] Synthesis is disabled for this setup (retrieval-only). "
                    "Run 'reqbot init' to enable it.",
                    file=sys.stderr,
                )
                synthesize = False
        except Exception:
            pass  # config unavailable — use local defaults

    data = retrieve(
        question,
        top_k=top_k,
        min_score=min_score,
        synthesize=synthesize,
        model=model,
        synthesis_model=syn_synthesis_model,
        remote_model=syn_remote_model,
        domain_tags=domain_tags,
        requirement_types=requirement_types,
        document_ids=document_ids,
        no_rewrite=no_rewrite,
        rewrite_model=rewrite_model,
        embedding_model=embedding_model,
        qdrant_url=qdrant_url,
        ollama_url=ollama_url,
        context=context,
        context_collection=context_collection,
        hyde=hyde,
        hyde_debug_log=hyde_debug_log,
        synthesis_backend=syn_backend,
        synthesis_provider=syn_provider,
        synthesis_api_key=syn_api_key,
    )

    if not data["results"]:
        print("No results met the minimum relevance threshold.")
        print(f"Try lowering --min-score (current: {min_score:.3f}) or broadening your query.")
        return []

    if json_output:
        print(json.dumps(data["results"], indent=2, ensure_ascii=False))
        return data["results"]

    print_results_table(data["results"])

    for warning in data.get("warnings", []):
        print(f"[!] {warning}")

    if data["synthesis_text"]:
        print(f"{'='*80}")
        print("SYNTHESIZED ANSWER")
        print(f"{'='*80}\n")
        print(data["synthesis_text"])
        print()

    return data["results"]


def _positive_int(value: str) -> int:
    """Argparse type: integer that must be > 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: '{value}'")
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return iv


def _non_negative_float(value: str) -> float:
    """Argparse type: float that must be >= 0."""
    try:
        fv = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid float value: '{value}'")
    if fv < 0:
        raise argparse.ArgumentTypeError("must be a non-negative number")
    return fv


def main() -> None:
    # Load config for defaults — falls back to hardcoded values if config unavailable.
    # Keeps standalone `python3 ask.py` consistent with `reqbot ask` defaults.
    try:
        from core import config as _config
        _cfg = _config.load()
        _default_top_k = _cfg.top_k
        _default_min_score = _cfg.min_score
        _default_qdrant_url = _cfg.qdrant_url
        _default_ollama_url = _cfg.ollama_url
        _default_embedding_model = _cfg.embedding_model
    except Exception as e:
        log.warning("Could not load config defaults (%s) — using hardcoded defaults", e)
        _default_top_k = 20
        _default_min_score = 0.02
        _default_qdrant_url = "http://localhost:6333"
        _default_ollama_url = "http://localhost:11434"
        _default_embedding_model = EMBEDDING_MODEL

    parser = argparse.ArgumentParser(
        description="Query GRC requirements via Qdrant vector search"
    )
    parser.add_argument(
        "question",
        type=str,
        help="Natural language question about requirements",
    )
    parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=_default_top_k,
        help=f"Number of results to retrieve (default: {_default_top_k})",
    )
    parser.add_argument(
        "--min-score",
        type=_non_negative_float,
        default=_default_min_score,
        dest="min_score",
        help=f"Minimum RRF score threshold — results below this are dropped (default: {_default_min_score}; 0 disables)",
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Generate an LLM answer with citations (default: retrieve-only)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="",
        help="LLM model for synthesis (default: configured synthesis_model, or "
             "remote_model when synthesis_backend=remote)",
    )
    parser.add_argument(
        "--domain-tag",
        type=str,
        action="append",
        dest="domain_tags",
        help="Filter by domain tag (can be repeated)",
    )
    parser.add_argument(
        "--requirement-type",
        type=str,
        action="append",
        dest="requirement_types",
        help="Filter by requirement type (can be repeated)",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        action="append",
        dest="document_ids",
        help="Filter by document_id (can be repeated)",
    )
    parser.add_argument(
        "--no-rewrite",
        action="store_true",
        help="Skip query rewriting (faster, use for simple keyword queries)",
    )
    parser.add_argument(
        "--rewrite-model",
        type=str,
        default=DEFAULT_REWRITE_MODEL,
        help=f"LLM model for query rewriting (default: {DEFAULT_REWRITE_MODEL})",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=_default_embedding_model,
        help=f"Ollama embedding model (default: {_default_embedding_model}) — must match "
             "whatever model actually indexed the collection you're querying",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=_default_qdrant_url,
        help=f"Qdrant HTTP API URL (default: {_default_qdrant_url})",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default=_default_ollama_url,
        help=f"Ollama API base URL (default: {_default_ollama_url})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON instead of formatted text",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Enrich results with surrounding raw chunk text from grc_context collection",
    )
    parser.add_argument(
        "--context-collection",
        type=str,
        default=CONTEXT_COLLECTION_NAME,
        help=f"Qdrant context collection name (default: {CONTEXT_COLLECTION_NAME})",
    )
    parser.add_argument(
        "--hyde",
        action="store_true",
        help=argparse.SUPPRESS,  # HyDE is default-on now; kept as an inert compatibility no-op
    )
    parser.add_argument(
        "--no-hyde",
        action="store_true",
        dest="no_hyde",
        help=(
            "Disable HyDE (Hypothetical Document Embedding) augmentation — falls back to "
            "baseline dense + BM25 RRF only. HyDE is on by default (Phase 15 evaluation gate "
            "passed: >=3 queries improved, none degraded, no hallucinated IDs)."
        ),
    )
    parser.add_argument(
        "--hyde-debug-log",
        action="store_true",
        dest="hyde_debug_log",
        help="Log HyDE hypotheses to hyde_hypotheses.jsonl in the CWD for batch review (debug/eval only; off by default)",
    )
    args = parser.parse_args()

    run(
        args.question,
        top_k=args.top_k,
        min_score=args.min_score,
        synthesize=args.synthesize,
        model=args.model,
        domain_tags=args.domain_tags,
        requirement_types=args.requirement_types,
        document_ids=args.document_ids,
        no_rewrite=args.no_rewrite,
        rewrite_model=args.rewrite_model,
        embedding_model=args.embedding_model,
        qdrant_url=args.qdrant_url,
        ollama_url=args.ollama_url,
        json_output=args.json_output,
        context=args.context,
        context_collection=args.context_collection,
        hyde=not args.no_hyde,
        hyde_debug_log=args.hyde_debug_log,
    )


if __name__ == "__main__":
    main()

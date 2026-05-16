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

# Must match CONTEXT_UUID_NAMESPACE in embed_context_index.py — never change.
CONTEXT_UUID_NAMESPACE = uuid.UUID("b5f2e8d1-3a7c-4e9f-b8a2-6d4f1c7e3b5a")

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
                key="document_id",
                match=models.MatchAny(any=document_ids),
            )
        )

    if not conditions:
        return None

    return models.Filter(must=conditions)


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


def format_evidence(results: list, context_map: dict | None = None) -> str:
    """Format Qdrant search results as numbered evidence for the LLM."""
    lines = []
    for i, hit in enumerate(results, 1):
        p = hit.payload
        page_info = ""
        if p.get("page_start") and p.get("page_end"):
            if p["page_start"] == p["page_end"]:
                page_info = f"p.{p['page_start']}"
            else:
                page_info = f"pp.{p['page_start']}-{p['page_end']}"

        ref = p.get("source_ref", "")
        source = p.get("source_pdf", "")
        cite_parts = [x for x in [source, ref, page_info] if x]
        cite = ", ".join(cite_parts)

        primary = p.get("description") or p.get("source_quote", "")
        entry = (
            f"[{i}] ({cite})\n"
            f"    Type: {p.get('requirement_type', 'unknown')}\n"
            f"    Tags: {', '.join(p.get('domain_tags', []))}\n"
            f"    Requirement: {primary}\n"
            f"    Quote: {p.get('source_quote', '')}"
        )
        ctx = _context_text_for_hit(hit, context_map, window=300)
        if ctx:
            entry += f"\n    Context: {ctx}"
        lines.append(entry)
    return "\n\n".join(lines)


def print_results_table(results: list, context_map: dict | None = None) -> None:
    """Print search results as a readable table."""
    print(f"\n{'='*80}")
    print(f"Retrieved {len(results)} requirements (ranked by relevance)")
    print(f"{'='*80}\n")

    for i, hit in enumerate(results, 1):
        p = hit.payload
        score = hit.score

        page_info = ""
        if p.get("page_start") and p.get("page_end"):
            if p["page_start"] == p["page_end"]:
                page_info = f"p.{p['page_start']}"
            else:
                page_info = f"pp.{p['page_start']}-{p['page_end']}"

        ref = p.get("source_ref", "")
        source = p.get("source_pdf", "")

        print(f"[{i}] Score: {score:.4f} | {p.get('requirement_id', '?')}")
        if source or ref or page_info:
            cite_parts = [x for x in [source, ref, page_info] if x]
            print(f"    Source: {', '.join(cite_parts)}")
        print(f"    Type: {p.get('requirement_type', 'unknown')} | Tags: {', '.join(p.get('domain_tags', []))}")
        primary = p.get("description") or p.get("source_quote", "")
        print(f"    {primary}")
        if p.get("source_quote") and p.get("description"):
            quote = p["source_quote"]
            if len(quote) > 120:
                quote = quote[:120] + "..."
            print(f"    Quote: \"{quote}\"")
        ctx = _context_text_for_hit(hit, context_map, window=150)
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
) -> str | None:
    """Generate a hypothetical requirement statement for HyDE dense retrieval.

    Embeds the hypothesis instead of (or in addition to) the raw query so the
    dense vector aligns with answer-shaped corpus text rather than question-shaped
    query text.

    Logs successful hypotheses to log_file for batch review — inspect in aggregate
    after an evaluation run, not inline. Empty responses and generation failures
    are not logged; caller receives None and falls back to baseline retrieval.
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
        import synthesis as _syn
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


def run(
    question: str,
    *,
    top_k: int = 20,
    min_score: float = 0.02,
    synthesize: bool = False,
    model: str = DEFAULT_SYNTHESIS_MODEL,
    domain_tags: list[str] | None = None,
    requirement_types: list[str] | None = None,
    document_ids: list[str] | None = None,
    no_rewrite: bool = False,
    rewrite_model: str = DEFAULT_REWRITE_MODEL,
    qdrant_url: str = "http://localhost:6333",
    ollama_url: str = "http://localhost:11434",
    json_output: bool = False,
    context: bool = False,
    context_collection: str = CONTEXT_COLLECTION_NAME,
    hyde: bool = False,
) -> list[dict]:
    """Query GRC requirements and print results to stdout.

    Callable interface for in-process use by reqbot.py.
    Standalone CLI usage is unchanged via main() / __main__.

    Returns:
        List of result payload dicts (score + payload fields).
    """
    # Connect to Ollama
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
    dense_result = ollama_client.embed(model=EMBEDDING_MODEL, input=dense_query)
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
        hypothesis = generate_hyde_hypothesis(question, rewrite_model, ollama_client)
        if hypothesis:
            try:
                hyde_result = ollama_client.embed(model=EMBEDDING_MODEL, input=hypothesis)
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
    qdrant_client = QdrantClient(url=qdrant_url)

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

    results = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=prefetch_legs,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=fusion_limit,
        with_payload=True,
    ).points

    # Score threshold — drop results below min_score, then trim to top_k.
    # Filtering after fusion (not before) ensures the threshold acts on final RRF scores.
    if min_score > 0:
        before = len(results)
        results = [r for r in results if r.score >= min_score]
        dropped = before - len(results)
        if dropped:
            log.info("Dropped %d result(s) below min_score=%.3f", dropped, min_score)
    results = results[:top_k]

    if not results:
        print("No results met the minimum relevance threshold.")
        print(f"Try lowering --min-score (current: {min_score:.3f}) or broadening your query.")
        return []

    # Retrieve surrounding context chunks from grc_context (P4 dual index)
    context_map: dict | None = None
    if context:
        log.info("Retrieving context chunks from: %s", context_collection)
        try:
            context_map = retrieve_context_chunks(results, qdrant_client, context_collection)
            log.info("Retrieved %d context chunk(s)", len(context_map))
            if not context_map:
                log.warning(
                    "No context chunks found — run 'reqbot index-context' to build grc_context"
                )
        except Exception as e:
            log.warning("Context retrieval failed (%s) — proceeding without context", e)
            context_map = None

    # JSON output mode
    if json_output:
        output = []
        for hit in results:
            output.append({
                "score": hit.score,
                **hit.payload,
            })
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return output

    # Print results table
    print_results_table(results, context_map)

    # Synthesize if requested
    if synthesize:
        evidence = format_evidence(results, context_map)
        # Load synthesis config (synthesis_backend, provider, api_key_env)
        _syn_backend = "local"
        _syn_provider = "anthropic"
        _syn_api_key = ""
        try:
            import config as _cfg_mod
            _cfg_syn = _cfg_mod.load()
            _syn_backend = _cfg_syn.synthesis_backend
            _syn_provider = _cfg_syn.remote_provider
            if _syn_backend == "remote":
                import os as _os
                _syn_api_key = _os.environ.get(_cfg_syn.api_key_env, "")
                if not _syn_api_key:
                    print(
                        f"[!] Remote synthesis configured but {_cfg_syn.api_key_env} "
                        "is not set — falling back to local"
                    )
                    _syn_backend = "local"
        except Exception:
            pass  # config unavailable — use local defaults

        answer = synthesize_answer(
            question, evidence, model, ollama_client,
            backend=_syn_backend,
            provider=_syn_provider,
            api_key=_syn_api_key,
            ollama_url=ollama_url,
        )
        print(f"{'='*80}")
        print("SYNTHESIZED ANSWER")
        print(f"{'='*80}\n")
        print(answer)
        print()

    return [{"score": hit.score, **hit.payload} for hit in results]


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
        import config as _config
        _cfg = _config.load()
        _default_top_k = _cfg.top_k
        _default_min_score = _cfg.min_score
        _default_qdrant_url = _cfg.qdrant_url
        _default_ollama_url = _cfg.ollama_url
    except Exception as e:
        log.warning("Could not load config defaults (%s) — using hardcoded defaults", e)
        _default_top_k = 20
        _default_min_score = 0.02
        _default_qdrant_url = "http://localhost:6333"
        _default_ollama_url = "http://localhost:11434"

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
        default=DEFAULT_SYNTHESIS_MODEL,
        help=f"LLM model for synthesis (default: {DEFAULT_SYNTHESIS_MODEL})",
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
        help=(
            "Enable HyDE (Hypothetical Document Embedding) augmentation — generates a "
            "hypothetical requirement statement and adds its embedding as a second dense "
            "RRF leg. Spike evaluation flag; logs hypotheses to hyde_hypotheses.jsonl."
        ),
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
        qdrant_url=args.qdrant_url,
        ollama_url=args.ollama_url,
        json_output=args.json_output,
        context=args.context,
        context_collection=args.context_collection,
        hyde=args.hyde,
    )


if __name__ == "__main__":
    main()

"""Evidence service — hybrid search, grouping, context retrieval, and LLM synthesis
for compliance evidence packs.

Returns structured data; all rendering (markdown/JSON) stays in cli/reqbot.py.
"""
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

from core import constants as _const

_EVIDENCE_AUDITOR_PROMPT = """You are a strict compliance auditor reviewing evidence for a System Security Plan (SSP).
You have been given a set of retrieved compliance requirements grouped by control ID.
Your task is to produce a concise Executive Summary for the evidence pack.

Rules you MUST follow:
1. Identify the dominant control families present in the evidence (e.g., AC, IA, AU).
2. Summarize what the evidence collectively requires — in plain, precise language an auditor would use.
3. Flag any gaps: controls that appear in only one framework, or controls with conflicting language across frameworks.
4. Do NOT invent requirements not present in the evidence.
5. Do NOT provide implementation guidance — only describe what the evidence says.
6. Keep the summary under 250 words. Use bullet points for clarity.

QUERY: {query}

EVIDENCE GROUPS ({group_count} control groups, {source_count} sources):
{evidence_summary}

Write the Executive Summary now:"""


def _embedding_warnings(payloads: list[dict], configured_embedding_model: str) -> list[str]:
    """Compare each result's indexed embedding_model against the configured one.

    Same logic as core/ask.py's _embedding_mismatch_warnings — points indexed
    before WP-25.6c carry no embedding_model field and are treated as
    "nomic-embed-text" (the universal default at the time). Never blocks the
    query.
    """
    mismatched_models: set[str] = set()
    mismatched_count = 0
    for p in payloads:
        indexed_model = p.get("embedding_model") or "nomic-embed-text"
        if indexed_model != configured_embedding_model:
            mismatched_count += 1
            mismatched_models.add(indexed_model)
    if not mismatched_count:
        return []
    models_str = ", ".join(sorted(mismatched_models))
    return [
        f"{mismatched_count} of {len(payloads)} results were indexed with a "
        f"different embedding model ({models_str}) than your current config "
        f"({configured_embedding_model}) and may be unreliable; run 'reqbot reindex' "
        "to refresh them."
    ]


def build(
    query: str,
    qdrant_url: str,
    ollama_url: str,
    top_k: int = 10,
    show_context: bool = False,
    document_ids: list | None = None,
    domain_tags: list | None = None,
    requirement_types: list | None = None,
    synthesize: bool = True,
    synthesis_backend: str = "local",
    synthesis_model: str = "",
    remote_model: str = "",
    provider: str = "",
    api_key: str = "",
    embedding_model: str = "nomic-embed-text",
) -> dict:
    """Search, group, optionally retrieve context, and synthesize an evidence pack.

    Selects synthesis_model or remote_model internally based on synthesis_backend
    (Phase 27, WP-27.2) -- callers pass both unconditionally rather than picking
    one themselves, so CLI/API/MCP can't drift on this choice again the way they
    previously did (always sending synthesis_model, the local Ollama model, even
    when synthesis_backend == "remote"). Falls back to synthesis_model if
    synthesis_backend == "remote" but remote_model is empty (Gemini review,
    PR #120) -- an empty model string reaching synthesize() is worse than using
    the local model's name against a remote provider (still fails, but at least
    isn't silently a no-op empty request).

    Returns a dict with keys:
      query: str
      timestamp: str (ISO 8601 UTC)
      groups: dict[source_ref, {source_ref, representative, sources, context_text}]
      group_order: list[str]
      total_sources: int
      synthesis_text: str  (empty string if synthesis failed or was skipped)

    Raises:
      ValueError  — no results found
      RuntimeError — connection or embedding failure
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client import models as _qm
    except ImportError as e:
        raise RuntimeError(
            "qdrant-client is not installed — run: "
            "pip3 install --break-system-packages qdrant-client"
        ) from e

    document_ids = document_ids or []
    domain_tags = domain_tags or []
    requirement_types = requirement_types or []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        client = QdrantClient(url=qdrant_url, timeout=10)
    except Exception as e:
        raise RuntimeError(f"Could not connect to Qdrant: {e}") from e

    # --- Dense embedding ---
    try:
        import ollama as _ollama
        dense_vector = _ollama.Client(host=ollama_url).embed(
            model=embedding_model, input=query
        ).embeddings[0]
    except Exception as e:
        raise RuntimeError(f"Dense embedding failed: {e}") from e

    # --- Sparse embedding ---
    try:
        from fastembed import SparseTextEmbedding as _STE
        sparse_emb = next(iter(_STE(model_name="Qdrant/bm25").embed([query])))
        sparse_vector = _qm.SparseVector(
            indices=sparse_emb.indices.tolist(),
            values=sparse_emb.values.tolist(),
        )
    except Exception as e:
        raise RuntimeError(f"Sparse embedding failed: {e}") from e

    # --- Build filter ---
    filter_conditions: list = []
    if document_ids:
        filter_conditions.append(
            _qm.FieldCondition(key="document_id", match=_qm.MatchAny(any=document_ids))
        )
    if domain_tags:
        filter_conditions.append(
            _qm.FieldCondition(key="domain_tags", match=_qm.MatchAny(any=domain_tags))
        )
    if requirement_types:
        filter_conditions.append(
            _qm.FieldCondition(key="requirement_type", match=_qm.MatchAny(any=requirement_types))
        )
    filter_obj = _qm.Filter(must=filter_conditions) if filter_conditions else None

    prefetch_limit = max(100, top_k * 5)

    try:
        hits = client.query_points(
            collection_name="grc_requirements",
            prefetch=[
                _qm.Prefetch(
                    query=dense_vector, using="dense",
                    filter=filter_obj, limit=prefetch_limit,
                ),
                _qm.Prefetch(
                    query=sparse_vector, using="sparse",
                    filter=filter_obj, limit=prefetch_limit,
                ),
            ],
            query=_qm.FusionQuery(fusion=_qm.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        ).points
    except Exception as e:
        raise RuntimeError(f"Search failed: {e}") from e

    if not hits:
        raise ValueError(f"No results found for: {query}")

    # --- Group by source_ref ---
    # Every result in a group becomes a "source" row in the evidence table.
    # The representative (canonical description) is the highest-confidence result per group.
    groups: dict[str, dict] = {}
    group_order: list[str] = []
    for hit in hits:
        p = hit.payload or {}
        ref = p.get("source_ref") or "(no ref)"
        if ref not in groups:
            groups[ref] = {
                "source_ref": ref,
                "representative": p,
                "sources": [],
                "context_text": None,
            }
            group_order.append(ref)
        groups[ref]["sources"].append(p)
        if (p.get("confidence") or 0) > (groups[ref]["representative"].get("confidence") or 0):
            groups[ref]["representative"] = p

    # --- Context retrieval — batch fetch for all group representatives ---
    if show_context:
        pid_to_ref: dict[str, str] = {}
        pids: list[str] = []
        for ref in group_order:
            rep = groups[ref]["representative"]
            doc_id = rep.get("document_id", "")
            chunk_id = rep.get("chunk_id")
            if doc_id and chunk_id is not None:
                pid = str(uuid.uuid5(_const.CONTEXT_UUID_NS, f"{doc_id}:{chunk_id}"))
                pids.append(pid)
                pid_to_ref[pid] = ref
        if pids:
            try:
                ctx_hits = client.retrieve(
                    collection_name="grc_context",
                    ids=pids,
                    with_payload=True,
                )
                for point in ctx_hits:
                    ref = pid_to_ref.get(str(point.id))
                    if not ref:
                        continue
                    ctx = (point.payload or {}).get("text", "")
                    if not ctx:
                        continue
                    rep = groups[ref]["representative"]
                    quote = rep.get("source_quote", "")
                    window = 300
                    if quote and quote in ctx:
                        idx = ctx.find(quote)
                        start = max(0, idx - window)
                        end = min(len(ctx), idx + len(quote) + window)
                        prefix = "..." if start > 0 else ""
                        suffix = "..." if end < len(ctx) else ""
                        groups[ref]["context_text"] = prefix + ctx[start:end] + suffix
                    else:
                        groups[ref]["context_text"] = (
                            ctx[:window * 2] + ("..." if len(ctx) > window * 2 else "")
                        )
            except Exception as e:
                log.warning("Context batch retrieval failed: %s", e)

    total_sources = sum(len(g["sources"]) for g in groups.values())

    # --- LLM synthesis — Compliance Auditor Executive Summary ---
    synthesis_text: str = ""
    if synthesize:
        evidence_lines: list[str] = []
        for i, ref in enumerate(group_order, 1):
            g = groups[ref]
            rep = g["representative"]
            # description first: for LLM synthesis, an interpretive description yields a
            # more coherent auditor summary than a raw verbatim quote. source_quote remains
            # the canonical asset in all other contexts (trace, evidence table rows).
            primary = rep.get("description") or rep.get("source_quote") or "(no text)"
            evidence_lines.append(
                f"[{i}] Control: {ref}  |  Sources: {len(g['sources'])}\n"
                f"    {primary}"
            )

        auditor_prompt = _EVIDENCE_AUDITOR_PROMPT.format(
            query=query,
            group_count=len(groups),
            source_count=total_sources,
            evidence_summary="\n\n".join(evidence_lines),
        )

        try:
            from core import synthesis as _syn
            model = remote_model if synthesis_backend == "remote" and remote_model else synthesis_model
            synthesis_text = _syn.synthesize(
                question="",
                evidence="",
                backend=synthesis_backend,
                model=model,
                ollama_url=ollama_url,
                provider=provider,
                api_key=api_key,
                raw_prompt=auditor_prompt,
            )
        except Exception as e:
            log.warning("Evidence synthesis failed (%s) — producing evidence pack without summary", e)

    all_payloads = [hit.payload or {} for hit in hits]
    return {
        "query": query,
        "timestamp": timestamp,
        "groups": groups,
        "group_order": group_order,
        "total_sources": total_sources,
        "synthesis_text": synthesis_text,
        "warnings": _embedding_warnings(all_payloads, embedding_model),
    }

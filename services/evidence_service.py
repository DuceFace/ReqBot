"""Evidence service — hybrid search, grouping, context retrieval, and LLM synthesis
for compliance evidence packs.

Returns structured data; all rendering (markdown/JSON) stays in cli/reqbot.py.
"""
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

from core import constants as _const
from core.profiles import load_profile as _load_profile

_EVIDENCE_AUDITOR_PROMPT = """You are a strict compliance auditor reviewing evidence for a System Security Plan (SSP).
You have been given a set of retrieved compliance requirements grouped by control ID.
Your task is to produce a concise Executive Summary for the evidence pack.

Rules you MUST follow:
1. {category_rule}
2. Summarize what the evidence collectively requires — in plain, precise language an auditor would use.
3. Flag any gaps: controls that appear in only one framework, or controls with conflicting language across frameworks.
4. Do NOT invent requirements not present in the evidence.
5. Do NOT provide implementation guidance — only describe what the evidence says.
6. Keep the summary under 250 words. Use bullet points for clarity.

QUERY: {query}

EVIDENCE GROUPS ({group_count} control groups, {source_count} sources):
{evidence_summary}

Write the Executive Summary now:"""

# Original hardcoded rule -- NIST/RMF control-family abbreviations that mean nothing
# outside cybersecurity. Kept as the fallback for mixed-profile results (WP-32.7):
# a wrong-but-old failure mode is better than guessing which profile's vocabulary
# should win, or merging tag vocabularies from unrelated domains together.
_DEFAULT_CATEGORY_RULE = "Identify the dominant control families present in the evidence (e.g., AC, IA, AU)."


def _category_rule(domain_tags: list[str] | None) -> str:
    """Build rule #1's text from the active profile's own domain_tags, so the
    auditor prompt's vocabulary is meaningful regardless of which profile is
    active (WP-32.7). domain_tags is None when results span more than one
    profile, or that profile's file failed to load -- _resolve_synthesis_domain_tags
    already logged why; the caller just gets the safe fallback here.
    """
    if not domain_tags:
        return _DEFAULT_CATEGORY_RULE
    sample = ", ".join(domain_tags[:3])
    return (
        "Identify the dominant categories present in the evidence, using this domain's own "
        f"vocabulary (e.g., {sample})."
    )


def _resolve_synthesis_domain_tags(hits: list) -> list[str] | None:
    """Return the shared domain_tags for a set of Qdrant search hits, or None if
    they don't share exactly one profile (WP-32.7).

    Every indexed requirement carries a domain_profile field -- defaulted to
    "cybersecurity" for pre-WP-25.x records, the same fallback idiom already used
    by trace_service.py/checklist_service.py/docs_service.py. The Evidence API
    filters by document/domain-tag/requirement-type, not by profile, so results
    spanning more than one profile aren't structurally prevented even though
    today's corpus is cybersecurity-only end to end (docs/TODO_future_improvements.txt
    Decisions and Guardrails #8). Handled simply per this WP's scope: agree on one
    profile or fall back, never guess or merge vocabularies.
    """
    profile_names = {(hit.payload or {}).get("domain_profile") or "cybersecurity" for hit in hits}
    if len(profile_names) != 1:
        return None
    try:
        profile = _load_profile(next(iter(profile_names)))
    except (FileNotFoundError, ValueError) as e:
        log.warning(
            "Could not load profile '%s' for evidence synthesis vocabulary (%s) — "
            "using generic prompt", next(iter(profile_names)), e
        )
        return None
    return profile["domain_tags"]


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


# A source_ref that's just a bare sub-item fragment ("(f)", "(a)", "(12)") with no
# parent control ID attached -- as opposed to a full ref like "IA-05(01)(b)", which
# already carries its own control ID and needs no disambiguation.
_BARE_FRAGMENT_RE = re.compile(r"^\(\w{1,4}\)$")


def _group_key_and_label(p: dict) -> tuple[str, str]:
    """Return (dict_key, display_label) for grouping one search hit (WP-32.3).

    A real, full source_ref (e.g. "IA-05(01)(b)") groups as before -- the same
    ref can legitimately span multiple documents (several DoD instructions
    citing the same NIST control), and that's the point of grouping. Left
    untouched here, per this WP's Non-Goals.

    An empty source_ref, or a bare sub-item fragment with no hierarchy
    metadata available to disambiguate it, has no real shared identity across
    records -- grouping those under one shared literal key ("(no ref)", "(f)")
    was silently merging unrelated documents. Singleton-key those by
    requirement_id instead; the dict_key just needs to be unique, so the
    display label stays the plain "(no ref)"/bare-fragment text.

    A bare fragment WITH section_ref_path or parent_section_ref available (the
    common case in practice: section_ref_path covers ~13x more records than
    parent_section_ref alone, per WP-32.3's corpus check) gets a fuller,
    disambiguating label built from the closest available ancestor -- e.g.
    "3.4" + "(a)" -> "3.4(a)" -- which both groups and displays as that
    combined ref.
    """
    ref = (p.get("source_ref") or "").strip()
    # A missing/None/empty requirement_id must still get a unique key -- otherwise
    # multiple such records collapse back into one shared key, defeating the whole
    # point of this function (Gemini review, PR #146).
    req_id = p.get("requirement_id") or uuid.uuid4().hex

    if not ref:
        return f"__no_ref__{req_id}", "(no ref)"

    if _BARE_FRAGMENT_RE.match(ref):
        raw_path = p.get("section_ref_path")
        path = raw_path if isinstance(raw_path, list) else []
        # path[-1] can itself be falsy (an empty string); don't let that mask a
        # real parent_section_ref (Gemini review, PR #146).
        ancestor = (path[-1] if path else None) or p.get("parent_section_ref")
        if ancestor:
            label = f"{ancestor}{ref}"
            return label, label
        return f"__bare_fragment__{req_id}", ref

    return ref, ref


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
      ValueError  — no results found, or document_ids contains a value not
        indexed in the grc_requirements collection (Phase 27, WP-27.3)
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

    # document_ids resolved/validated against Qdrant's source_pdf field, not the
    # internal document_id hash (Phase 27, WP-27.3) -- reuses core.ask's Qdrant-
    # backed resolver (WP-27.1) rather than docs_service/processed_dir, since
    # processed_dir isn't equivalent to what's actually indexed and searchable.
    if document_ids:
        from core.ask import resolve_document_ids as _resolve_document_ids
        resolved_document_ids, unknown_document_ids = _resolve_document_ids(
            client, document_ids
        )
        if unknown_document_ids:
            raise ValueError(
                "Unknown document_ids (no matching indexed document): "
                + ", ".join(sorted(unknown_document_ids))
            )
        document_ids = resolved_document_ids

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
            _qm.FieldCondition(key="source_pdf", match=_qm.MatchAny(any=document_ids))
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

    # --- Group by source_ref (WP-32.3: see _group_key_and_label for the empty/
    #     bare-fragment fallback that used to silently merge unrelated documents) ---
    # Every result in a group becomes a "source" row in the evidence table.
    # The representative (canonical description) is the highest-confidence result per group.
    groups: dict[str, dict] = {}
    group_order: list[str] = []
    for hit in hits:
        p = hit.payload or {}
        key, label = _group_key_and_label(p)
        if key not in groups:
            groups[key] = {
                "source_ref": label,
                "representative": p,
                "sources": [],
                "context_text": None,
            }
            group_order.append(key)
        groups[key]["sources"].append(p)
        if (p.get("confidence") or 0) > (groups[key]["representative"].get("confidence") or 0):
            groups[key]["representative"] = p

    # --- Context retrieval — batch fetch for all group representatives ---
    if show_context:
        # One pid (document_id:chunk_id) can now back multiple groups -- WP-32.3's
        # singleton keys mean two different empty-ref/bare-fragment requirements can
        # legitimately share the same source chunk. Map pid -> every group key that
        # needs it, not just the last one seen, or all but one silently lose their
        # context_text (Codex review, PR #146).
        pid_to_refs: dict[str, list[str]] = {}
        pids: list[str] = []
        for ref in group_order:
            rep = groups[ref]["representative"]
            doc_id = rep.get("document_id", "")
            chunk_id = rep.get("chunk_id")
            if doc_id and chunk_id is not None:
                pid = str(uuid.uuid5(_const.CONTEXT_UUID_NS, f"{doc_id}:{chunk_id}"))
                if pid not in pid_to_refs:
                    pids.append(pid)
                pid_to_refs.setdefault(pid, []).append(ref)
        if pids:
            try:
                ctx_hits = client.retrieve(
                    collection_name="grc_context",
                    ids=pids,
                    with_payload=True,
                )
                for point in ctx_hits:
                    refs = pid_to_refs.get(str(point.id))
                    if not refs:
                        continue
                    ctx = (point.payload or {}).get("text", "")
                    if not ctx:
                        continue
                    for ref in refs:
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
                # g["source_ref"] is the display label (e.g. "(no ref)", "3.4(a)") -- ref
                # itself is groups' internal dict key, which for the empty/bare-fragment
                # fallback (WP-32.3) is an unlabeled-looking singleton like
                # "__no_ref__REQ-xxxx" and must never reach the LLM prompt.
                f"[{i}] Control: {g['source_ref']}  |  Sources: {len(g['sources'])}\n"
                f"    {primary}"
            )

        auditor_prompt = _EVIDENCE_AUDITOR_PROMPT.format(
            category_rule=_category_rule(_resolve_synthesis_domain_tags(hits)),
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

"""Unit tests for services/evidence_service.py's synthesis model selection
(Phase 27, WP-27.2) and document_ids filter (Phase 27, WP-27.3).

build() must select cfg.remote_model when synthesis_backend == "remote" and
cfg.synthesis_model when "local" -- previously it always used synthesis_model
even for the remote backend, silently sending a local Ollama model name to
Anthropic/OpenAI and swallowing the resulting failure into an empty
synthesis_text.

build()'s document_ids filter must resolve caller-facing doc_key/source_pdf
values against the indexed corpus and filter on the source_pdf field --
previously it filtered on the internal document_id hash, which no normal
caller can know.

All external dependencies (Qdrant, Ollama, fastembed) are mocked at their
import boundary since evidence_service.build() imports them locally.
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _fake_hit(
    source_ref="AC-2",
    score=0.9,
    requirement_id="REQ-fake",
    document_id="doc1",
    section_ref_path=None,
    parent_section_ref=None,
):
    hit = MagicMock()
    hit.payload = {
        "requirement_id": requirement_id,
        "document_id": document_id,
        "source_ref": source_ref,
        "source_quote": "The organization shall enforce access control.",
        "description": "Access control requirement.",
        "confidence": 0.9,
        "section_ref_path": section_ref_path or [],
        "parent_section_ref": parent_section_ref,
    }
    hit.score = score
    return hit


def _run_build(document_id_counts: dict[str, int] | None = None, hits=None, **overrides):
    from services import evidence_service

    fake_qdrant_client = MagicMock()
    fake_qdrant_client.query_points.return_value.points = hits or [_fake_hit()]

    counts = document_id_counts or {}

    def _count(collection_name, count_filter, exact):
        match_value = count_filter.must[0].match.value
        result = MagicMock()
        result.count = counts.get(match_value, 0)
        return result

    fake_qdrant_client.count.side_effect = _count

    fake_ollama_client = MagicMock()
    fake_ollama_client.embed.return_value.embeddings = [[0.1, 0.2, 0.3]]

    fake_sparse_emb = MagicMock()
    fake_sparse_emb.indices = np.array([0, 1])
    fake_sparse_emb.values = np.array([0.5, 0.5])
    fake_sparse_model = MagicMock()
    fake_sparse_model.embed.return_value = iter([fake_sparse_emb])

    kwargs = dict(
        query="access control",
        qdrant_url="http://qdrant:6333",
        ollama_url="http://ollama:11434",
        synthesize=True,
        synthesis_backend="local",
        synthesis_model="local-model",
        remote_model="remote-model",
        provider="anthropic",
        api_key="",
    )
    kwargs.update(overrides)

    with (
        patch("qdrant_client.QdrantClient", return_value=fake_qdrant_client),
        patch("ollama.Client", return_value=fake_ollama_client),
        patch("fastembed.SparseTextEmbedding", return_value=fake_sparse_model),
        patch("core.synthesis.synthesize", return_value="synthesized summary") as mock_synthesize,
    ):
        result = evidence_service.build(**kwargs)

    return result, mock_synthesize, fake_qdrant_client


def test_remote_backend_uses_remote_model():
    _, mock_synthesize, _ = _run_build(synthesis_backend="remote", api_key="sk-fake")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "remote-model"


def test_local_backend_uses_synthesis_model():
    _, mock_synthesize, _ = _run_build(synthesis_backend="local")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


def test_synthesize_false_never_calls_synthesize():
    _, mock_synthesize, _ = _run_build(synthesize=False)
    mock_synthesize.assert_not_called()


def test_remote_backend_with_empty_remote_model_falls_back_to_synthesis_model():
    """Gemini review, PR #120: remote_model="" (or omitted) must not reach
    synthesize() as an empty model string -- fall back to synthesis_model
    rather than sending a doomed empty request."""
    _, mock_synthesize, _ = _run_build(synthesis_backend="remote", remote_model="")
    _, kwargs = mock_synthesize.call_args
    assert kwargs["model"] == "local-model"


# ---------------------------------------------------------------------------
# document_ids filter (Phase 27, WP-27.3)
#
# resolve_document_ids() itself (candidate resolution, .pdf-suffix handling)
# is exhaustively covered in tests/unit/test_ask_document_ids_validation.py --
# these tests only confirm build() wires document_ids through that same
# resolver and filters on the caller-facing source_pdf field, not the
# internal document_id hash.
# ---------------------------------------------------------------------------

def test_document_ids_resolved_and_filtered_on_source_pdf_not_hash():
    """A bare doc_key resolves to its real source_pdf form and the Qdrant
    filter is built on the source_pdf field -- not the internal document_id
    hash the pre-WP-27.3 filter used."""
    _, _, fake_client = _run_build(
        document_id_counts={"afi17-101.pdf": 3}, document_ids=["afi17-101"]
    )
    _, kwargs = fake_client.query_points.call_args
    filter_obj = kwargs["prefetch"][0].filter
    condition = filter_obj.must[0]
    assert condition.key == "source_pdf"
    assert condition.match.any == ["afi17-101.pdf"]


def test_document_ids_accepts_full_source_pdf_form():
    _, _, fake_client = _run_build(
        document_id_counts={"afi17-101.pdf": 3}, document_ids=["afi17-101.pdf"]
    )
    _, kwargs = fake_client.query_points.call_args
    condition = kwargs["prefetch"][0].filter.must[0]
    assert condition.match.any == ["afi17-101.pdf"]


def test_unknown_document_ids_raises_value_error_not_empty_result():
    """A stale/typo'd document_ids value must error, not silently produce an
    empty/reduced evidence pack (same hard-error rule as WP-27.1)."""
    with pytest.raises(ValueError, match="nonexistent-doc"):
        _run_build(document_id_counts={}, document_ids=["nonexistent-doc"])


def test_no_document_ids_applies_no_filter():
    _, _, fake_client = _run_build(document_ids=None)
    _, kwargs = fake_client.query_points.call_args
    assert kwargs["prefetch"][0].filter is None


# ---------------------------------------------------------------------------
# Grouping fallback fix (Phase 32, WP-32.3)
#
# _group_key_and_label() unit tests exercise the pure logic directly; the
# build()-level tests below confirm it's actually wired into the grouping
# loop and that unrelated documents no longer collapse into one group.
# ---------------------------------------------------------------------------

def test_group_key_full_ref_groups_and_labels_as_itself():
    from services.evidence_service import _group_key_and_label

    p = {"source_ref": "IA-05(01)(b)", "requirement_id": "REQ-a"}
    key, label = _group_key_and_label(p)
    assert key == "IA-05(01)(b)"
    assert label == "IA-05(01)(b)"


def test_group_key_empty_ref_is_singleton_per_requirement():
    from services.evidence_service import _group_key_and_label

    key_a, label_a = _group_key_and_label({"source_ref": "", "requirement_id": "REQ-a"})
    key_b, label_b = _group_key_and_label({"source_ref": None, "requirement_id": "REQ-b"})
    assert key_a != key_b
    assert label_a == "(no ref)"
    assert label_b == "(no ref)"


def test_group_key_bare_fragment_uses_section_ref_path_last_element():
    from services.evidence_service import _group_key_and_label

    p = {
        "source_ref": "(a)",
        "requirement_id": "REQ-a",
        "section_ref_path": ["SECTION-3", "3.4"],
        "parent_section_ref": "SECTION-3",
    }
    key, label = _group_key_and_label(p)
    # the closer ancestor (path[-1]) wins over the coarser parent_section_ref
    assert key == "3.4(a)"
    assert label == "3.4(a)"


def test_group_key_bare_fragment_falls_back_to_parent_section_ref():
    from services.evidence_service import _group_key_and_label

    p = {
        "source_ref": "(b)",
        "requirement_id": "REQ-a",
        "section_ref_path": [],
        "parent_section_ref": "SECTION-5",
    }
    key, label = _group_key_and_label(p)
    assert key == "SECTION-5(b)"
    assert label == "SECTION-5(b)"


def test_group_key_bare_fragment_with_no_hierarchy_is_singleton():
    from services.evidence_service import _group_key_and_label

    key_a, label_a = _group_key_and_label({"source_ref": "(f)", "requirement_id": "REQ-a"})
    key_b, label_b = _group_key_and_label({"source_ref": "(f)", "requirement_id": "REQ-b"})
    assert key_a != key_b
    assert label_a == "(f)"
    assert label_b == "(f)"


def test_build_does_not_merge_unrelated_documents_under_empty_ref():
    """The original bug: 14 requirements from ~10 unrelated documents all
    fell into one literal "(no ref)" bucket. Two hits with an empty
    source_ref from different documents must land in separate groups."""
    hits = [
        _fake_hit(source_ref="", requirement_id="REQ-a", document_id="docA"),
        _fake_hit(source_ref="", requirement_id="REQ-b", document_id="docB"),
    ]
    result, _, _ = _run_build(hits=hits, synthesize=False)
    assert len(result["groups"]) == 2
    assert all(g["source_ref"] == "(no ref)" for g in result["groups"].values())


def test_build_does_not_merge_unrelated_documents_under_bare_fragment_no_hierarchy():
    hits = [
        _fake_hit(source_ref="(f)", requirement_id="REQ-a", document_id="docA"),
        _fake_hit(source_ref="(f)", requirement_id="REQ-b", document_id="docB"),
    ]
    result, _, _ = _run_build(hits=hits, synthesize=False)
    assert len(result["groups"]) == 2


def test_build_still_merges_same_full_ref_across_documents():
    """Non-goal, confirmed as a regression guard: a real, full source_ref
    shared across documents (e.g. multiple DoD instructions citing the same
    NIST control) keeps grouping together -- only the empty/bare-fragment
    fallback paths changed."""
    hits = [
        _fake_hit(source_ref="IA-05(01)(b)", requirement_id="REQ-a", document_id="docA"),
        _fake_hit(source_ref="IA-05(01)(b)", requirement_id="REQ-b", document_id="docB"),
    ]
    result, _, _ = _run_build(hits=hits, synthesize=False)
    assert len(result["groups"]) == 1
    assert result["groups"]["IA-05(01)(b)"]["sources"] == [h.payload for h in hits]


def test_build_synthesis_prompt_uses_display_label_not_internal_key():
    """The synthesis evidence_lines must never leak an internal singleton key
    like "__no_ref__REQ-a" into the LLM prompt."""
    hits = [_fake_hit(source_ref="", requirement_id="REQ-a", document_id="docA")]
    _, mock_synthesize, _ = _run_build(hits=hits, synthesize=True)
    _, kwargs = mock_synthesize.call_args
    prompt = kwargs["raw_prompt"]
    assert "__no_ref__" not in prompt
    assert "(no ref)" in prompt

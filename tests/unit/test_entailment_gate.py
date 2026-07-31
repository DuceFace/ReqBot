"""Unit tests for pipeline/entailment_gate.py's Step D.6 orchestration (WP-35.4).

Covers run(): MiniCheck-unavailable graceful skip, entailment rejection,
modality rejection, both firing together, empty-description pass-through,
and the "requirement is never dropped" invariant. MiniCheck itself is always
mocked via monkeypatch — an optional dependency (pyproject.toml's
`grounding-check` extra) that these tests must not require being installed.

is_fabricated_obligation()'s own fixture-level behavior is covered by
tests/unit/test_modality_fabrication_check.py; this file only exercises it
through run()'s orchestration.
"""
import json
from pathlib import Path

from pipeline import entailment_gate


class _FakeScorer:
    """Stand-in for minicheck.minicheck.MiniCheck. Returns a fixed support_prob
    per call position (or the same value for every pair if a single float)."""

    def __init__(self, probs):
        self._probs = probs
        self.calls = []

    def score(self, docs, claims):
        self.calls.append((docs, claims))
        n = len(docs)
        probs = list(self._probs[:n]) if isinstance(self._probs, list) else [self._probs] * n
        pred_label = [1 if p >= 0.5 else 0 for p in probs]
        return pred_label, probs, None, None


class _BrokenScorer:
    """Simulates a MiniCheck instance that loaded but fails during scoring
    (missing NLTK resource, OOM, transient model error)."""

    def score(self, docs, claims):
        raise RuntimeError("simulated scoring failure")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


FAITHFUL_REQ = {
    "requirement_id": "REQ-1",
    "chunk_id": "c1",
    "source_quote": "DoD Components will use only NSA-approved cryptographic products.",
    "description": "DoD Components must use only NSA-approved cryptographic products.",
}

MODALITY_FABRICATED_REQ = {
    "requirement_id": "REQ-2",
    "chunk_id": "c2",
    "source_quote": "Insider Threat, as defined in DoDD 5205.16.",
    "description": "Implement Insider Threat Program as defined in DoDD 5205.16.",
}

EMPTY_DESC_REQ = {
    "requirement_id": "REQ-3",
    "chunk_id": "c3",
    "source_quote": "Some self-explanatory quote.",
    "description": "",
}


def test_skips_entailment_when_minicheck_unavailable_but_modality_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: None)
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ, MODALITY_FABRICATED_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    by_id = {r["requirement_id"]: r for r in records}
    assert by_id["REQ-1"]["description"] == FAITHFUL_REQ["description"]
    assert by_id["REQ-2"]["description"] == ""

    failures = _read_jsonl(tmp_path / "doc_description_gate_failures.jsonl")
    assert len(failures) == 1
    assert failures[0]["requirement_id"] == "REQ-2"
    assert failures[0]["error"] == ["description_fabricated_obligation"]
    assert "support_prob" not in failures[0]


def test_rejects_low_entailment_score(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _FakeScorer(0.2))
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    assert records[0]["description"] == ""
    failures = _read_jsonl(tmp_path / "doc_description_gate_failures.jsonl")
    assert failures[0]["error"] == ["description_not_grounded"]
    assert failures[0]["support_prob"] == 0.2


def test_scoring_failure_degrades_to_entailment_skipped_not_a_crash(tmp_path, monkeypatch):
    # Codex review, PR #169: a MiniCheck scoring failure (missing NLTK
    # resource, OOM, transient error) must not propagate out of run() --
    # run_pipeline.py's caller catches any exception from run() by falling
    # back to the completely ungated file, which would silently lose the
    # dependency-free modality check too, not just entailment scoring.
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _BrokenScorer())
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ, MODALITY_FABRICATED_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    by_id = {r["requirement_id"]: r for r in records}
    # Entailment skipped -- faithful record passes through untouched.
    assert by_id["REQ-1"]["description"] == FAITHFUL_REQ["description"]
    # Modality check still ran and caught the fabrication.
    assert by_id["REQ-2"]["description"] == ""
    failures = _read_jsonl(tmp_path / "doc_description_gate_failures.jsonl")
    assert failures[0]["error"] == ["description_fabricated_obligation"]
    assert "support_prob" not in failures[0]


def test_keeps_faithful_description_when_score_above_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _FakeScorer(0.95))
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    assert records[0]["description"] == FAITHFUL_REQ["description"]
    failures = _read_jsonl(tmp_path / "doc_description_gate_failures.jsonl")
    assert failures == []


def test_records_both_reasons_when_both_checks_fire(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _FakeScorer(0.1))
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [MODALITY_FABRICATED_REQ])

    entailment_gate.run(str(in_path), str(tmp_path))

    failures = _read_jsonl(tmp_path / "doc_description_gate_failures.jsonl")
    assert failures[0]["error"] == ["description_not_grounded", "description_fabricated_obligation"]


def test_empty_description_is_never_checked_or_flagged(tmp_path, monkeypatch):
    scorer = _FakeScorer(0.1)  # would reject everything if called
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: scorer)
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [EMPTY_DESC_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    assert records[0]["description"] == ""
    assert scorer.calls == []  # never sent to the scorer at all
    failures = _read_jsonl(tmp_path / "doc_description_gate_failures.jsonl")
    assert failures == []


def test_requirement_is_never_dropped_even_when_everything_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _FakeScorer(0.0))
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ, MODALITY_FABRICATED_REQ, EMPTY_DESC_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    assert len(records) == 3
    assert {r["requirement_id"] for r in records} == {"REQ-1", "REQ-2", "REQ-3"}
    # source_quote and other fields survive even when description is cleared.
    assert records[0]["source_quote"] == FAITHFUL_REQ["source_quote"]


def test_other_fields_pass_through_unchanged_on_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _FakeScorer(0.0))
    req = dict(MODALITY_FABRICATED_REQ, domain_tags=["access-control"], requirement_type="technical-control")
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [req])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    assert records[0]["domain_tags"] == ["access-control"]
    assert records[0]["requirement_type"] == "technical-control"
    assert records[0]["description"] == ""


def test_derives_gated_filename_from_enriched_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: None)
    in_path = tmp_path / "AFI17-101_requirements_enriched.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))

    assert gated_path.name == "AFI17-101_requirements_gated.jsonl"


def test_derives_gated_filename_from_normalized_suffix(tmp_path, monkeypatch):
    # Step D.5 skipped/failed -- input is the normalized file, not enriched.
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: None)
    in_path = tmp_path / "AFI17-101_requirements_normalized.jsonl"
    _write_jsonl(in_path, [FAITHFUL_REQ])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))

    assert gated_path.name == "AFI17-101_requirements_gated.jsonl"


def test_score_entailment_skips_scorer_call_for_empty_pairs():
    scorer = _FakeScorer(0.1)
    result = entailment_gate._score_entailment(scorer, [])
    assert result == []
    assert scorer.calls == []


def test_missing_source_quote_does_not_crash(tmp_path, monkeypatch):
    # Gemini review, PR #169: a record missing source_quote entirely
    # (malformed/hand-edited input, not something the normal pipeline path
    # produces -- Step D's own empty_source_quote check already guarantees
    # this for anything that reaches Step D.6 normally) previously raised a
    # raw KeyError instead of being handled gracefully.
    monkeypatch.setattr(entailment_gate, "_load_minicheck_scorer", lambda: _FakeScorer(0.1))
    req = {"requirement_id": "REQ-1", "chunk_id": "c1", "description": "Implement X."}
    in_path = tmp_path / "doc_requirements_enriched.jsonl"
    _write_jsonl(in_path, [req])

    gated_path = Path(entailment_gate.run(str(in_path), str(tmp_path)))
    records = _read_jsonl(gated_path)

    assert len(records) == 1
    assert records[0]["description"] == ""

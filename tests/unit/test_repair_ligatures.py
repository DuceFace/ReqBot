"""Unit tests for WP-32.2's ligature repair tool (pipeline/repair_ligatures.py)."""
import json

from pipeline.repair_ligatures import (
    KNOWN_LIGATURE_REPAIRS,
    repair_record,
    repair_text,
    run,
)

_TI = "\ue000"
_TT = "\ue001"
_FT = "\ue002"
_TT2 = "\ue003"
_TF = "\ue004"


def test_repair_text_replaces_known_codepoint():
    assert repair_text(f"authen{_TI}ca{_TI}on") == "authentication"


def test_repair_text_replaces_multiple_distinct_ligatures():
    assert repair_text(f"a{_TT}ributes a{_FT}er") == "attributes after"


def test_repair_text_no_op_on_clean_text():
    clean = "no ligature corruption here"
    assert repair_text(clean) == clean


def test_all_five_known_codepoints_covered():
    assert len(KNOWN_LIGATURE_REPAIRS) == 5


def test_repair_text_resolves_every_known_codepoint():
    corrupted = f"{_TI} {_TT} {_FT} {_TT2} {_TF}"
    assert repair_text(corrupted) == "ti tt ft tt tf"


def test_repair_record_fixes_text_and_raw_text_fields():
    record = {
        "chunk_id": 1,
        "text": f"organiza{_TI}onal",
        "raw_text": f"organiza{_TI}onal",
        "page_start": 1,
    }
    repaired, replaced = repair_record(record)
    assert repaired["text"] == "organizational"
    assert repaired["raw_text"] == "organizational"
    assert repaired["page_start"] == 1
    assert replaced == 2


def test_repair_record_fixes_list_of_string_fields():
    record = {"section_title_path": [f"password composi{_TI}on policy"]}
    repaired, replaced = repair_record(record)
    assert repaired["section_title_path"] == ["password composition policy"]
    assert replaced == 1


def test_repair_record_fixes_strings_in_mixed_type_list():
    record = {"section_title_path": [f"composi{_TI}on", None, "clean"]}
    repaired, replaced = repair_record(record)
    assert repaired["section_title_path"] == ["composition", None, "clean"]
    assert replaced == 1


def test_repair_record_untouched_when_no_corruption():
    record = {"chunk_id": 5, "text": "clean text", "page_start": 3}
    repaired, replaced = repair_record(record)
    assert repaired == record
    assert replaced == 0


def test_repair_record_preserves_non_string_fields():
    record = {"chunk_id": 7, "page_start": 10, "page_end": 12, "text": "clean"}
    repaired, _ = repair_record(record)
    assert repaired["page_start"] == 10
    assert repaired["page_end"] == 12


def test_run_repairs_file_in_place(tmp_path):
    chunks_path = tmp_path / "doc_chunks.jsonl"
    records = [
        {"chunk_id": 0, "text": f"authen{_TI}ca{_TI}on", "raw_text": "unused"},
        {"chunk_id": 1, "text": "already clean"},
    ]
    with open(chunks_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    result_path = run(str(chunks_path))
    assert result_path == str(chunks_path.resolve())

    with open(chunks_path, encoding="utf-8") as f:
        repaired = [json.loads(line) for line in f]
    assert repaired[0]["text"] == "authentication"
    assert repaired[1]["text"] == "already clean"


def test_run_writes_to_separate_output_path_when_given(tmp_path):
    chunks_path = tmp_path / "doc_chunks.jsonl"
    out_path = tmp_path / "doc_chunks_repaired.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_id": 0, "text": f"a{_FT}er"}) + "\n")

    run(str(chunks_path), str(out_path))

    with open(out_path, encoding="utf-8") as f:
        repaired = [json.loads(line) for line in f]
    assert repaired[0]["text"] == "after"
    with open(chunks_path, encoding="utf-8") as f:
        original = [json.loads(line) for line in f]
    assert original[0]["text"] == f"a{_FT}er"


def test_run_creates_missing_output_parent_directory(tmp_path):
    chunks_path = tmp_path / "doc_chunks.jsonl"
    out_path = tmp_path / "nested" / "does" / "not" / "exist" / "out.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_id": 0, "text": f"a{_FT}er"}) + "\n")

    run(str(chunks_path), str(out_path))

    with open(out_path, encoding="utf-8") as f:
        repaired = [json.loads(line) for line in f]
    assert repaired[0]["text"] == "after"

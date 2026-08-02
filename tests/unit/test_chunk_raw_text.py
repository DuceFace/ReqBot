"""Unit tests for WP-42: table-structure-aware serialization in _chunk_raw_text().

TableItem has neither a `.text` attribute nor `export_to_text()` (confirmed directly
against the installed docling_core, docs/PHASE42_REQUIREMENTS.md). Before this fix,
that meant a table-only chunk fell through to chunk.text -- HybridChunker's own
default table serializer, which flattens each cell into a "Header = Value" triplet
restating the table's full caption per cell (real corpus example: afi17-203
chunk_id=55, a >2000-char wall of repeated caption text). These tests use a real,
minimally-constructed TableItem (not a bare mock) so isinstance(item, TableItem)
inside _chunk_raw_text is genuinely exercised, not silently bypassed.
"""
from docling_core.types.doc import DocItemLabel, TableCell, TableData, TableItem

from pipeline.chunk_text import _TABLE_MARKDOWN_WARN_CHARS, _chunk_raw_text


class _MockTextItem:
    def __init__(self, text):
        self.text = text


class _Meta:
    def __init__(self, items):
        self.doc_items = items


class _MockChunk:
    def __init__(self, items, text=""):
        self.meta = _Meta(items)
        self.text = text


def _table_item(cells=None):
    cells = cells or [
        TableCell(text="Col A", start_row_offset_idx=0, end_row_offset_idx=1,
                   start_col_offset_idx=0, end_col_offset_idx=1,
                   column_header=True, row_header=False, row_section=False),
        TableCell(text="Col B", start_row_offset_idx=0, end_row_offset_idx=1,
                   start_col_offset_idx=1, end_col_offset_idx=2,
                   column_header=True, row_header=False, row_section=False),
        TableCell(text="val1", start_row_offset_idx=1, end_row_offset_idx=2,
                   start_col_offset_idx=0, end_col_offset_idx=1,
                   column_header=False, row_header=False, row_section=False),
        TableCell(text="val2", start_row_offset_idx=1, end_row_offset_idx=2,
                   start_col_offset_idx=1, end_col_offset_idx=2,
                   column_header=False, row_header=False, row_section=False),
    ]
    data = TableData(table_cells=cells, num_rows=2, num_cols=2)
    return TableItem(self_ref="#/tables/0", label=DocItemLabel.TABLE, data=data)


def test_table_item_serialized_as_markdown_grid():
    chunk = _MockChunk([_table_item()])
    result = _chunk_raw_text(chunk, None)
    assert "| Col A" in result
    assert "| val1" in result
    assert "---" in result  # markdown header separator


def test_table_item_does_not_fall_back_to_chunk_text_triplet_garble():
    # Regression guard: before the fix, a table-only chunk fell through to
    # chunk.text (HybridChunker's own flattened "Header = Value" serializer).
    garbled_chunk_text = "Col A = val1. Col A = val1. Col A = val1."
    chunk = _MockChunk([_table_item()], text=garbled_chunk_text)
    result = _chunk_raw_text(chunk, None)
    assert result != garbled_chunk_text
    assert "| Col A" in result


def test_table_item_export_failure_falls_back_gracefully():
    # A table whose export_to_markdown() raises must not crash chunking --
    # it should fall through the same getattr/export_to_text path a normal
    # item would, ending in "" (contributes nothing), not an exception.
    class _BrokenTable(TableItem):
        def export_to_markdown(self, *args, **kwargs):
            raise RuntimeError("boom")

    broken = _BrokenTable(self_ref="#/tables/1", label=DocItemLabel.TABLE,
                           data=TableData(table_cells=[], num_rows=0, num_cols=0))
    chunk = _MockChunk([broken], text="fallback chunk text")
    result = _chunk_raw_text(chunk, None)
    assert result == "fallback chunk text"


def test_non_table_item_unaffected():
    chunk = _MockChunk([_MockTextItem("A plain paragraph of body text.")])
    result = _chunk_raw_text(chunk, None)
    assert result == "A plain paragraph of body text."


def test_table_and_text_items_mixed():
    chunk = _MockChunk([_MockTextItem("Intro sentence."), _table_item()])
    result = _chunk_raw_text(chunk, None)
    assert "Intro sentence." in result
    assert "| Col A" in result


def test_doc_passed_through_to_export_to_markdown():
    calls = []

    class _RecordingTable(TableItem):
        def export_to_markdown(self, doc=None, *args, **kwargs):
            calls.append(doc)
            return "| recorded |"

    table = _RecordingTable(self_ref="#/tables/2", label=DocItemLabel.TABLE,
                             data=TableData(table_cells=[], num_rows=0, num_cols=0))
    sentinel_doc = object()
    chunk = _MockChunk([table])
    _chunk_raw_text(chunk, sentinel_doc)
    assert calls == [sentinel_doc]


def test_same_table_across_chunks_emitted_once_not_duplicated():
    # Codex review, PR #189: HybridChunker splits an oversized table across
    # N chunks, all referencing the *same* TableItem (confirmed empirically
    # against all 4 WP-42 documents). The full table must reach Step C
    # exactly once, not once per split chunk.
    table = _table_item()
    seen: set = set()
    chunk_a = _MockChunk([table])
    chunk_b = _MockChunk([table])  # same self_ref, simulating the second split chunk
    result_a = _chunk_raw_text(chunk_a, None, seen_table_refs=seen)
    result_b = _chunk_raw_text(chunk_b, None, seen_table_refs=seen)
    assert "| Col A" in result_a
    assert result_b == ""


def test_duplicate_table_chunk_does_not_fall_back_to_chunk_text():
    # A chunk whose only content is an already-emitted table must end up
    # truly empty (so the caller's empty-chunk filter drops it) -- not
    # resurrect the old per-chunk garbled chunk.text duplicate.
    table = _table_item()
    seen: set = {table.self_ref}
    chunk = _MockChunk([table], text="old garbled duplicate should not reappear")
    result = _chunk_raw_text(chunk, None, seen_table_refs=seen)
    assert result == ""


def test_different_tables_each_emitted_independently():
    seen: set = set()
    table_1 = _table_item()
    table_2 = _table_item()
    table_2.self_ref = "#/tables/1"
    result_1 = _chunk_raw_text(_MockChunk([table_1]), None, seen_table_refs=seen)
    result_2 = _chunk_raw_text(_MockChunk([table_2]), None, seen_table_refs=seen)
    assert "| Col A" in result_1
    assert "| Col A" in result_2
    assert seen == {"#/tables/0", "#/tables/1"}


def test_no_seen_table_refs_arg_still_works_without_dedup():
    # seen_table_refs is optional -- callers that don't pass it (or unit
    # tests exercising the function directly) get the pre-dedup behavior.
    table = _table_item()
    result_a = _chunk_raw_text(_MockChunk([table]), None)
    result_b = _chunk_raw_text(_MockChunk([table]), None)
    assert "| Col A" in result_a
    assert "| Col A" in result_b


def test_doc_resolution_failure_falls_back_to_markdown_without_doc():
    # Gemini review, PR #189: a caption/cross-reference resolution failure
    # specific to one table (raised only when `doc` is passed) must not
    # sacrifice the whole grid -- retry without `doc` before giving up.
    class _FlakyWithDocTable(TableItem):
        def export_to_markdown(self, doc=None, *args, **kwargs):
            if doc is not None:
                raise RuntimeError("caption resolution boom")
            return "| Col A   | Col B   |\n|---------|---------|\n| val1    | val2    |"

    table = _FlakyWithDocTable(self_ref="#/tables/3", label=DocItemLabel.TABLE,
                                data=TableData(table_cells=[], num_rows=0, num_cols=0))
    chunk = _MockChunk([table], text="fallback chunk text should not be used")
    result = _chunk_raw_text(chunk, object())
    assert "| Col A" in result
    assert result != "fallback chunk text should not be used"


def test_table_export_failure_does_not_suppress_later_chunks_own_content():
    # Codex review, PR #189: seen_table_refs must only be marked after a
    # successful export. Previously it was marked unconditionally, so a
    # table whose export genuinely fails would wrongly suppress every later
    # chunk referencing the same table too -- discarding their own
    # chunk.text fallback for content that was never actually emitted
    # anywhere.
    class _AlwaysBrokenTable(TableItem):
        def export_to_markdown(self, *args, **kwargs):
            raise RuntimeError("boom")

    table = _AlwaysBrokenTable(self_ref="#/tables/4", label=DocItemLabel.TABLE,
                                data=TableData(table_cells=[], num_rows=0, num_cols=0))
    seen: set = set()
    chunk_a = _MockChunk([table], text="first slice fallback")
    chunk_b = _MockChunk([table], text="second slice fallback")
    result_a = _chunk_raw_text(chunk_a, None, seen_table_refs=seen)
    result_b = _chunk_raw_text(chunk_b, None, seen_table_refs=seen)
    assert result_a == "first slice fallback"
    assert result_b == "second slice fallback"
    assert seen == set()


def test_oversized_table_markdown_logs_warning(caplog):
    # Codex review, PR #189: a table's full markdown is now emitted in a
    # single chunk rather than bounded by HybridChunker's own splitting.
    # Not a real risk yet (docs/PHASE42_REQUIREMENTS.md: the corpus's
    # largest known table uses ~43% of Step C's context budget), but nothing
    # bounds it either -- a future oversized table should at least be
    # visible in logs, not silently degrade extraction.
    big_row = "| " + "x" * 200 + " |"
    huge_markdown = "| Col A |\n|---|\n" + "\n".join([big_row] * 150)
    assert len(huge_markdown) > _TABLE_MARKDOWN_WARN_CHARS

    class _HugeTable(TableItem):
        def export_to_markdown(self, *args, **kwargs):
            return huge_markdown

    table = _HugeTable(self_ref="#/tables/5", label=DocItemLabel.TABLE,
                        data=TableData(table_cells=[], num_rows=0, num_cols=0))
    with caplog.at_level("WARNING"):
        result = _chunk_raw_text(_MockChunk([table]), None)
    assert result == huge_markdown
    assert any("approaching" in rec.message for rec in caplog.records)

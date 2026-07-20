"""Unit tests for the reqbot checklist CLI command (WP-21.5 / WP-23.2).

Tests call cmd_checklist() directly with a constructed argparse.Namespace,
patching the service and export layers so no filesystem or LLM access is needed.
"""
import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cli.reqbot import cmd_checklist

# Minimal checklist envelope returned by the mocked service
MOCK_CHECKLIST = {
    "format": "reqbot-checklist",
    "format_version": "1.0",
    "generated_at": "2026-07-19T12:00:00+00:00",
    "generator": {"tool": "reqbot", "command": "reqbot checklist --doc test-doc --profile cybersecurity"},
    "document": {"document_id": "abc123", "source_pdf": "test-doc.pdf"},
    "profile": "cybersecurity",
    "summary": {"total_items": 1, "items_requiring_review": 0},
    "items": [
        {
            "checklist_item_id": "CHK-abcdef1234567890",
            "requirement_ids": ["REQ-abc123"],
            "source_quote": "The system shall enforce MFA.",
            "audit_question": "",
            "requires_human_review": False,
            "review_reasons": [],
        }
    ],
}


def _args(
    doc: str = "test-doc",
    fmt: str = "csv",
    output: str | None = None,
    profile: str = "cybersecurity",
) -> argparse.Namespace:
    return argparse.Namespace(doc=doc, format=fmt, output=output, profile=profile)


# ---------------------------------------------------------------------------
# Format routing
# ---------------------------------------------------------------------------

def test_format_csv_calls_to_csv(tmp_path, capsys):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv", return_value="csv-output\n") as mock_csv, \
         patch("pipeline.checklist_export.to_json") as mock_json, \
         patch("pipeline.checklist_export.to_markdown") as mock_md:
        rc = cmd_checklist(_args(fmt="csv"))

    assert rc == 0
    mock_csv.assert_called_once_with(MOCK_CHECKLIST)
    mock_json.assert_not_called()
    mock_md.assert_not_called()
    assert "csv-output" in capsys.readouterr().out


def test_format_json_calls_to_json(tmp_path, capsys):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv") as mock_csv, \
         patch("pipeline.checklist_export.to_json", return_value='{"format": "reqbot-checklist"}') as mock_json, \
         patch("pipeline.checklist_export.to_markdown") as mock_md:
        rc = cmd_checklist(_args(fmt="json"))

    assert rc == 0
    mock_json.assert_called_once_with(MOCK_CHECKLIST)
    mock_csv.assert_not_called()
    mock_md.assert_not_called()
    assert '"format"' in capsys.readouterr().out


def test_format_md_calls_to_markdown(tmp_path, capsys):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv") as mock_csv, \
         patch("pipeline.checklist_export.to_json") as mock_json, \
         patch("pipeline.checklist_export.to_markdown", return_value="# Checklist\n") as mock_md:
        rc = cmd_checklist(_args(fmt="md"))

    assert rc == 0
    mock_md.assert_called_once_with(MOCK_CHECKLIST)
    mock_csv.assert_not_called()
    mock_json.assert_not_called()
    assert "# Checklist" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Profile and service argument pass-through
# ---------------------------------------------------------------------------

def test_profile_passed_to_service(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST) as mock_gen, \
         patch("pipeline.checklist_export.to_csv", return_value=""):
        cmd_checklist(_args(profile="test-domain"))

    mock_gen.assert_called_once_with(tmp_path, "test-doc", "test-domain")


def test_doc_key_passed_to_service(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST) as mock_gen, \
         patch("pipeline.checklist_export.to_csv", return_value=""):
        cmd_checklist(_args(doc="afi17-101"))

    mock_gen.assert_called_once_with(tmp_path, "afi17-101", "cybersecurity")


def test_processed_dir_passed_to_service(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST) as mock_gen, \
         patch("pipeline.checklist_export.to_csv", return_value=""):
        cmd_checklist(_args())

    args_passed = mock_gen.call_args[0]
    assert args_passed[0] == tmp_path


# ---------------------------------------------------------------------------
# --output file writing
# ---------------------------------------------------------------------------

def test_output_file_written(tmp_path, capsys):
    out_file = tmp_path / "checklist.csv"
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv", return_value="header\nrow\n"):
        rc = cmd_checklist(_args(output=str(out_file)))

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "header\nrow\n"
    assert str(out_file) in capsys.readouterr().out


def test_output_file_does_not_print_content(tmp_path, capsys):
    out_file = tmp_path / "checklist.csv"
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv", return_value="header\nrow\n"):
        cmd_checklist(_args(output=str(out_file)))

    stdout = capsys.readouterr().out
    assert "header" not in stdout


def test_stdout_when_no_output_arg(tmp_path, capsys):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv", return_value="csv-content\n"):
        rc = cmd_checklist(_args(output=None))

    assert rc == 0
    assert "csv-content" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_missing_processed_dir_returns_1(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = nonexistent

    with patch("cli.reqbot._cfg", mock_cfg):
        rc = cmd_checklist(_args())

    assert rc == 1


def test_unknown_doc_key_returns_1(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", side_effect=ValueError("No requirements JSONL found for doc_key 'unknown'")):
        rc = cmd_checklist(_args(doc="unknown"))

    assert rc == 1


def test_invalid_profile_returns_1(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", side_effect=FileNotFoundError("Profile not found: bad-profile")):
        rc = cmd_checklist(_args(profile="bad-profile"))

    assert rc == 1


def test_output_file_write_error_returns_1(tmp_path, capsys):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path
    unwritable = "/root/no_permission/checklist.csv"

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv", return_value="data\n"):
        rc = cmd_checklist(_args(output=unwritable))

    assert rc == 1


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------

def test_returns_0_on_success(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_csv", return_value=""):
        rc = cmd_checklist(_args())

    assert rc == 0


# ---------------------------------------------------------------------------
# XLSX format (WP-23.2)
# ---------------------------------------------------------------------------

def test_format_xlsx_without_output_returns_1(tmp_path, capsys):
    """xlsx to stdout is not supported; --output is required."""
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST):
        rc = cmd_checklist(_args(fmt="xlsx", output=None))

    assert rc == 1


def test_format_xlsx_calls_to_xlsx_and_writes_bytes(tmp_path, capsys):
    out_file = tmp_path / "checklist.xlsx"
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path
    fake_bytes = b"PK\x03\x04fakexlsx"

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_xlsx", return_value=fake_bytes) as mock_xlsx:
        rc = cmd_checklist(_args(fmt="xlsx", output=str(out_file)))

    assert rc == 0
    mock_xlsx.assert_called_once_with(MOCK_CHECKLIST)
    assert out_file.read_bytes() == fake_bytes
    assert str(out_file) in capsys.readouterr().out


def test_format_xlsx_write_error_returns_1(tmp_path):
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path
    unwritable = "/root/no_permission/checklist.xlsx"

    with patch("cli.reqbot._cfg", mock_cfg), \
         patch("services.checklist_service.generate", return_value=MOCK_CHECKLIST), \
         patch("pipeline.checklist_export.to_xlsx", return_value=b"fake"):
        rc = cmd_checklist(_args(fmt="xlsx", output=unwritable))

    assert rc == 1

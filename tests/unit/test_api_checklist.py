"""Unit tests for api/routes/checklist.py (WP-22.3).

Covers: GET /api/profiles, POST /api/checklist, POST /api/checklist/export.
All service and export calls are mocked — no filesystem or LLM access.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.app import app

client = TestClient(app)

# Minimal checklist envelope returned by the mocked service.
MOCK_CHECKLIST = {
    "format": "reqbot-checklist",
    "format_version": "1.0",
    "generated_at": "2026-07-20T00:00:00+00:00",
    "generator": {"tool": "reqbot", "command": ""},
    "document": {"document_id": "abc123", "source_pdf": "afi17-101.pdf"},
    "profile": "cybersecurity",
    "summary": {"total_items": 1, "items_requiring_review": 0},
    "items": [
        {
            "checklist_item_id": "CHK-abcdef1234567890",
            "requirement_ids": ["REQ-abc123"],
            "source_quote": "The system shall enforce MFA.",
            "source_ref": "Section 3.1",
            "section_title_path": ["Access Control"],
            "page_refs": [12],
            "domain_tags": ["access-control"],
            "confidence": 0.95,
            "audit_question": "",
            "status": "not-started",
            "assessor_notes": "",
            "requires_human_review": False,
            "review_reasons": [],
        }
    ],
}

_GENERATE_PATH = "api.routes.checklist.checklist_service.generate"
_PROFILES_PATH = "api.routes.checklist.list_profiles"


# ---------------------------------------------------------------------------
# GET /api/profiles
# ---------------------------------------------------------------------------


def test_get_profiles_returns_list():
    with patch(_PROFILES_PATH, return_value=["cybersecurity", "test-domain"]):
        resp = client.get("/api/profiles")
    assert resp.status_code == 200
    body = resp.json()
    assert "profiles" in body
    assert body["profiles"] == ["cybersecurity", "test-domain"]


def test_get_profiles_live_contains_cybersecurity():
    """Integration smoke: the real profiles/ directory has at least cybersecurity."""
    resp = client.get("/api/profiles")
    assert resp.status_code == 200
    assert "cybersecurity" in resp.json()["profiles"]


# ---------------------------------------------------------------------------
# POST /api/checklist — happy path
# ---------------------------------------------------------------------------


def test_post_checklist_happy_path():
    with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST):
        resp = client.post(
            "/api/checklist",
            json={"doc_key": "afi17-101", "profile": "cybersecurity"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "reqbot-checklist"
    assert body["profile"] == "cybersecurity"
    assert len(body["items"]) == 1


def test_post_checklist_default_profile():
    """profile field defaults to 'cybersecurity' if omitted."""
    with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST) as mock_gen:
        resp = client.post("/api/checklist", json={"doc_key": "afi17-101"})
    assert resp.status_code == 200
    assert mock_gen.call_args.args[2] == "cybersecurity"


def test_post_checklist_passes_resolved_path_to_service(tmp_path):
    """cfg.processed_dir_path() is called as a method and its return value reaches generate()."""
    mock_cfg = MagicMock()
    mock_cfg.processed_dir_path.return_value = tmp_path
    with patch("api.routes.checklist._config.load", return_value=mock_cfg):
        with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST) as mock_gen:
            resp = client.post(
                "/api/checklist",
                json={"doc_key": "afi17-101", "profile": "cybersecurity"},
            )
    assert resp.status_code == 200
    assert mock_gen.call_args.args[0] == tmp_path


# ---------------------------------------------------------------------------
# POST /api/checklist — error paths
# ---------------------------------------------------------------------------


def test_post_checklist_unknown_doc_key_returns_404():
    with patch(_GENERATE_PATH, side_effect=ValueError("No requirements JSONL found for doc_key 'bad-doc'")):
        resp = client.post(
            "/api/checklist",
            json={"doc_key": "bad-doc", "profile": "cybersecurity"},
        )
    assert resp.status_code == 404
    assert "bad-doc" in resp.json()["detail"]


def test_post_checklist_invalid_profile_returns_400():
    with patch(_GENERATE_PATH, side_effect=FileNotFoundError("Profile not found: profiles/bad.json")):
        resp = client.post(
            "/api/checklist",
            json={"doc_key": "afi17-101", "profile": "bad"},
        )
    assert resp.status_code == 400
    assert "Profile not found" in resp.json()["detail"]


def test_post_checklist_missing_processed_dir_returns_503():
    with patch(_GENERATE_PATH, side_effect=FileNotFoundError("processed_dir not found: /missing")):
        resp = client.post(
            "/api/checklist",
            json={"doc_key": "afi17-101", "profile": "cybersecurity"},
        )
    assert resp.status_code == 503


def test_post_checklist_generic_fnfe_returns_503():
    """Any FileNotFoundError that is not profile-related is a server-side failure (503)."""
    with patch(_GENERATE_PATH, side_effect=FileNotFoundError("Intermediate file missing")):
        resp = client.post(
            "/api/checklist",
            json={"doc_key": "afi17-101", "profile": "cybersecurity"},
        )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/checklist/export — format routing
# ---------------------------------------------------------------------------


def test_export_csv_returns_attachment():
    with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST):
        resp = client.post(
            "/api/checklist/export",
            json={"doc_key": "afi17-101", "profile": "cybersecurity", "format": "csv"},
        )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    assert "afi17-101_cybersecurity.csv" in resp.headers["content-disposition"]
    # CSV has a header row
    assert "source_ref" in resp.text


def test_export_json_returns_attachment():
    with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST):
        resp = client.post(
            "/api/checklist/export",
            json={"doc_key": "afi17-101", "profile": "cybersecurity", "format": "json"},
        )
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    assert "afi17-101_cybersecurity.json" in resp.headers["content-disposition"]
    body = resp.json()
    assert body["format"] == "reqbot-checklist"


def test_export_markdown_returns_attachment():
    with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST):
        resp = client.post(
            "/api/checklist/export",
            json={"doc_key": "afi17-101", "profile": "cybersecurity", "format": "markdown"},
        )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    assert "afi17-101_cybersecurity.md" in resp.headers["content-disposition"]
    assert "# Checklist" in resp.text


def test_export_xlsx_returns_attachment():
    with patch(_GENERATE_PATH, return_value=MOCK_CHECKLIST):
        resp = client.post(
            "/api/checklist/export",
            json={"doc_key": "afi17-101", "profile": "cybersecurity", "format": "xlsx"},
        )
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    assert "afi17-101_cybersecurity.xlsx" in resp.headers["content-disposition"]
    assert len(resp.content) > 0


def test_export_unsupported_format_returns_400():
    resp = client.post(
        "/api/checklist/export",
        json={"doc_key": "afi17-101", "profile": "cybersecurity", "format": "pdf"},
    )
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/checklist/export — error paths (same as /checklist)
# ---------------------------------------------------------------------------


def test_export_unknown_doc_key_returns_404():
    with patch(_GENERATE_PATH, side_effect=ValueError("No requirements JSONL found for doc_key 'bad-doc'")):
        resp = client.post(
            "/api/checklist/export",
            json={"doc_key": "bad-doc", "profile": "cybersecurity", "format": "csv"},
        )
    assert resp.status_code == 404


def test_export_invalid_profile_returns_400():
    with patch(_GENERATE_PATH, side_effect=FileNotFoundError("Profile not found: profiles/bad.json")):
        resp = client.post(
            "/api/checklist/export",
            json={"doc_key": "afi17-101", "profile": "bad", "format": "csv"},
        )
    assert resp.status_code == 400

"""Status service — checks Ollama and Qdrant connectivity.

Returns structured data; all display logic stays in cli/reqbot.py.
"""
import logging
import sys
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)


def check(
    ollama_url: str,
    qdrant_url: str,
    processed_dir: Path,
    configured_models: dict | None = None,
) -> dict:
    """Check system status and return structured results.

    Returns a dict with keys:
      ollama_url: str
      qdrant_url: str
      ollama: {reachable: bool, models: list[{name, size_gb}]}
      qdrant: {reachable: bool, collections: list[{name, points}]}
      processed_documents: list[{path: str, count: int}]
      configured_models: dict — which model ReqBot is actually configured to use per
        role (extraction/enrichment/rewrite/synthesis), distinct from `ollama.models`
        above which is what's merely installed/available on the server (WP-25.6b).
    """
    result: dict = {
        "ollama_url": ollama_url,
        "qdrant_url": qdrant_url,
        "ollama": {"reachable": False, "models": []},
        "qdrant": {"reachable": False, "collections": []},
        "processed_documents": [],
        "configured_models": configured_models or {},
    }

    # --- Ollama ---
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        result["ollama"] = {
            "reachable": True,
            "models": [
                {"name": m["name"], "size_gb": m.get("size", 0) / (1024 ** 3)}
                for m in models
            ],
        }
    except requests.RequestException:
        pass

    # --- Qdrant ---
    try:
        resp = requests.get(f"{qdrant_url}/collections", timeout=5)
        resp.raise_for_status()
        collections = resp.json().get("result", {}).get("collections", [])
        coll_list = []
        for c in collections:
            name = c.get("name", "?")
            points: int | str = "?"
            detail_resp = requests.get(f"{qdrant_url}/collections/{name}", timeout=5)
            if detail_resp.ok:
                points = detail_resp.json().get("result", {}).get("points_count", "?")
            coll_list.append({"name": name, "points": points})
        result["qdrant"] = {"reachable": True, "collections": coll_list}
    except requests.RequestException:
        pass

    # --- Processed documents ---
    if processed_dir.exists():
        docs = []
        for nf in sorted(processed_dir.rglob("*_requirements_normalized.jsonl")):
            count = sum(1 for line in open(nf, encoding="utf-8") if line.strip())
            try:
                display = "~/" + str(nf.relative_to(Path.home()))
            except ValueError:
                display = str(nf)
            docs.append({"path": display, "count": count})
        result["processed_documents"] = docs

    return result

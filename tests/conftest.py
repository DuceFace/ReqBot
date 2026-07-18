"""Shared pytest configuration and fixtures.

sys.path injection: adds repo root so `from services.foo import ...` works
without an installed package. Tech debt — permanent fix is `pip install -e .`.
"""
import sys
from pathlib import Path

# Repo root onto sys.path so package imports resolve without installation.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

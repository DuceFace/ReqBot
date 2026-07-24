"""Unit tests for the `reqbot mcp` CLI entry point (WP-26.2).

cmd_mcp() is a thin dispatcher: return 1 with a log message if the optional
mcp extra isn't installed, otherwise call mcp_server.server.run() and return 0.
mcp_server/server.py's own get_status tool has its own coverage in
test_mcp_server.py -- these tests only cover cmd_mcp's own branch logic.

mcp is an optional [mcp] extra (pyproject.toml), not in requirements.txt/
requirements-dev.txt -- see test_mcp_server.py's module docstring for why
these skip cleanly (pytest.importorskip) instead of failing when it's absent.
The success-path test below needs mcp_server.server importable to patch
its .run attribute, so the whole file is gated, not just that one test.
"""
import argparse
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("mcp")

from cli.reqbot import cmd_mcp  # noqa: E402


def test_cmd_mcp_returns_1_when_mcp_extra_not_installed(caplog):
    # sys.modules[name] = None is the standard way to force ImportError on the
    # next `import name` / `from name import ...`, faithfully simulating the
    # optional [mcp] extra being absent without needing a separate environment.
    with patch.dict(sys.modules, {"mcp_server.server": None}):
        with caplog.at_level(logging.ERROR):
            rc = cmd_mcp(argparse.Namespace())

    assert rc == 1
    assert "mcp" in caplog.text.lower()
    assert "reqbot[mcp]" in caplog.text


def test_cmd_mcp_runs_server_and_returns_0_on_success():
    fake_run = MagicMock()
    with patch("mcp_server.server.run", fake_run):
        rc = cmd_mcp(argparse.Namespace())

    fake_run.assert_called_once_with()
    assert rc == 0

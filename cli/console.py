#!/usr/bin/env python3
"""ReqBot interactive shell.

Launch via:
    reqbot                     (no arguments → shell)
    python3 console.py         (direct)
"""

import argparse
import cmd
import json
import logging
import re
import shlex
import sys
from argparse import Namespace
from pathlib import Path

import requests

# Ensure repo root (bundle: app/) is on sys.path for cross-package imports.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import config as _config
from cli import reqbot as _reqbot

# Readline history — graceful fallback if not available
_READLINE_AVAILABLE = False
_HIST_FILE = Path.home() / ".reqbot_history"
try:
    import readline as _readline
    _READLINE_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# ANSI color helpers — fallback to plain text when not in a TTY
# ---------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def info(msg: str) -> None:
    print(f"[*] {msg}")


def ok(msg: str) -> None:
    print(_c("32", f"[+] {msg}"))


def err(msg: str) -> None:
    print(_c("31", f"[-] {msg}"))


def warn(msg: str) -> None:
    print(_c("33", f"[!] {msg}"))


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
BANNER = r"""
 ██████╗ ███████╗ ██████╗ ██████╗  ██████╗ ████████╗
 ██╔══██╗██╔════╝██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝
 ██████╔╝█████╗  ██║   ██║██████╔╝██║   ██║   ██║
 ██╔══██╗██╔══╝  ██║▄▄ ██║██╔══██╗██║   ██║   ██║
 ██║  ██║███████╗╚██████╔╝██████╔╝╚██████╔╝   ██║
 ╚═╝  ╚═╝╚══════╝ ╚══▀▀═╝ ╚═════╝  ╚═════╝   ╚═╝
  Compliance Requirements Intelligence Engine
"""

# ---------------------------------------------------------------------------
# Session variable definitions
# ---------------------------------------------------------------------------

# All settable session keys, in display order
_SESSION_KEYS = [
    "ollama_url",
    "qdrant_url",
    "default_model",
    "synthesis_model",
    "top_k",
    "min_score",
    "document_id",
    "domain_tag",
    "requirement_type",
]

# Keys that can be unset (filter vars). Connection/model keys must use `set`.
_FILTER_KEYS = {"document_id", "domain_tag", "requirement_type"}

# Known domain tags (inlined to avoid parse_and_normalize import side-effects)
_DOMAIN_TAGS = {
    "access-control",
    "authentication-and-identity",
    "audit-and-logging",
    "configuration-management",
    "contingency-and-recovery",
    "data-protection-and-encryption",
    "incident-response",
    "maintenance",
    "media-protection",
    "network-security",
    "personnel-security",
    "physical-security",
    "privacy",
    "risk-management",
    "security-assessment",
    "supply-chain-security",
    "system-integrity",
    "training-and-awareness",
}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Argparse type validators (reused across shell command parsers)
# ---------------------------------------------------------------------------

_VALID_REQUIREMENT_TYPES = {"policy", "technical-control", "procedural-control", "assessment", "guidance"}


def _normalize_filter_flags(
    domain_tags: list[str],
    requirement_types: list[str],
) -> tuple[list[str], list[str]]:
    """Normalize and warn on inline --domain-tag and --requirement-type values.

    Applies the same hyphen/case normalization as build_query_filter() in ask.py,
    and emits a shell warning for any value not in the known valid sets.
    Returns (normalized_domain_tags, normalized_requirement_types).
    """
    norm_tags = []
    for t in domain_tags:
        t = t.strip().lower().replace(" ", "-").replace("_", "-")
        if not t:
            continue
        if t not in _DOMAIN_TAGS:
            warn(f"Unknown domain tag '{t}' — may return 0 results")
            info(f"Valid tags: {', '.join(sorted(_DOMAIN_TAGS))}")
        norm_tags.append(t)

    norm_types = []
    for rt in requirement_types:
        rt = rt.strip().lower().replace(" ", "-").replace("_", "-")
        if not rt:
            continue
        if rt not in _VALID_REQUIREMENT_TYPES:
            warn(f"Unknown requirement_type '{rt}' — may return 0 results")
            info(f"Valid types: {', '.join(sorted(_VALID_REQUIREMENT_TYPES))}")
        norm_types.append(rt)

    return norm_tags, norm_types


def _positive_int(value: str) -> int:
    """Argparse type: integer that must be > 0."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: '{value}'")
    if iv <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return iv


def _non_negative_float(value: str) -> float:
    """Argparse type: float that must be >= 0."""
    try:
        fv = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid float value: '{value}'")
    if fv < 0:
        raise argparse.ArgumentTypeError("must be a non-negative number")
    return fv


# ---------------------------------------------------------------------------
# Shell class
# ---------------------------------------------------------------------------

class GrcaiConsole(cmd.Cmd):
    intro = "Type 'help' for available commands.\n"
    prompt = "reqbot > "

    def __init__(self, cfg: _config.ReqBotConfig) -> None:
        super().__init__()
        self._session: dict = {
            "ollama_url": cfg.ollama_url,
            "qdrant_url": cfg.qdrant_url,
            "default_model": cfg.default_model,
            "synthesis_model": cfg.synthesis_model,
            "top_k": cfg.top_k,
            "min_score": cfg.min_score,
            "document_id": None,
            "domain_tag": None,
            "requirement_type": None,
        }
        # Session-scoped remote synthesis warning — shown once per shell session.
        # Must live here (not in synthesis.py) to persist across the lifecycle
        # of the interactive shell session.
        self._remote_synthesis_warned: bool = False

    # ------------------------------------------------------------------
    # Shell plumbing
    # ------------------------------------------------------------------

    def emptyline(self) -> None:
        """Do nothing on empty input."""

    def default(self, line: str) -> None:
        """Handle unknown commands — never raise, never exit."""
        cmd_name = line.strip().split()[0] if line.strip() else line
        err(f"Unknown command: '{cmd_name}' — type 'help' for available commands")

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def do_exit(self, _arg: str) -> bool:
        """Exit the ReqBot shell."""
        if _READLINE_AVAILABLE:
            try:
                _readline.write_history_file(_HIST_FILE)
            except OSError:
                pass
        print("Goodbye.")
        return True

    def do_quit(self, arg: str) -> bool:
        """Exit the ReqBot shell."""
        return self.do_exit(arg)

    def do_EOF(self, arg: str) -> bool:
        """Exit cleanly on Ctrl+D."""
        print()
        return self.do_exit(arg)

    # ------------------------------------------------------------------
    # show
    # ------------------------------------------------------------------

    def do_show(self, _arg: str) -> None:
        """Display current session variables and active filters."""
        print("\nSession Variables")
        print("=================")
        for key in _SESSION_KEYS:
            val = self._session.get(key)
            if val is None:
                display = _c("90", "(not set)")  # dim grey if color
            else:
                display = _c("32", str(val)) if key in _FILTER_KEYS else str(val)
            print(f"  {key:<20} {display}")
        print()

    # ------------------------------------------------------------------
    # set / unset
    # ------------------------------------------------------------------

    def do_set(self, arg: str) -> None:
        """Set a session variable.  Usage: set <key> <value>

        Examples:
          set top_k 10
          set document_id NIST.SP.800-53r5
          set domain_tag incident-response
        """
        parts = arg.strip().split(None, 1)
        if len(parts) < 2:
            err("Usage: set <key> <value>")
            info(f"Settable keys: {', '.join(_SESSION_KEYS)}")
            return

        key, value = parts[0], parts[1]

        if key not in _SESSION_KEYS:
            err(f"Unknown key '{key}'")
            info(f"Valid keys: {', '.join(_SESSION_KEYS)}")
            return

        # Validate top_k
        if key == "top_k":
            try:
                value = int(value)
                if value <= 0:
                    raise ValueError
            except ValueError:
                err("top_k must be a positive integer")
                return

        # Validate min_score
        elif key == "min_score":
            try:
                value = float(value)
                if value < 0:
                    raise ValueError
            except ValueError:
                err("min_score must be a non-negative number (e.g. 0.02; 0 disables)")
                return

        # Validate and normalize domain_tag
        elif key == "domain_tag":
            tags, _ = _normalize_filter_flags([value], [])
            if not tags:
                err("domain_tag value cannot be empty")
                return
            value = tags[0]

        # Validate and normalize requirement_type
        elif key == "requirement_type":
            _, types = _normalize_filter_flags([], [value])
            if not types:
                err("requirement_type value cannot be empty")
                return
            value = types[0]

        self._session[key] = value
        info(f"{key} => {value}")

    def do_unset(self, arg: str) -> None:
        """Clear a session filter variable.  Usage: unset <key>

        Only filter keys can be unset: document_id, domain_tag, requirement_type
        Use 'set' to change connection or model settings.
        """
        key = arg.strip()
        if not key:
            err("Usage: unset <key>")
            return
        if key not in _SESSION_KEYS:
            err(f"Unknown key '{key}'")
            return
        if key not in _FILTER_KEYS:
            warn(f"'{key}' is a connection/model setting — use 'set <key> <value>' to change it")
            return
        self._session[key] = None
        info(f"{key} cleared")

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def do_status(self, _arg: str) -> None:
        """Show Ollama and Qdrant connection status."""
        ns = Namespace(
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )
        try:
            _reqbot.cmd_status(ns)
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # docs
    # ------------------------------------------------------------------

    def do_docs(self, _arg: str) -> None:
        """List indexed documents with requirement counts and extraction mode."""
        ns = Namespace(
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )
        try:
            _reqbot.cmd_docs(ns)
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------

    def do_tags(self, _arg: str) -> None:
        """List domain tags present in the corpus with point counts."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import FieldCondition, Filter, MatchValue
        except ImportError:
            err("qdrant_client not installed — run: pip3 install qdrant-client")
            return

        qdrant_url = self._session["qdrant_url"]
        try:
            client = QdrantClient(url=qdrant_url, timeout=10)
        except Exception as e:
            err(f"Could not connect to Qdrant: {e}")
            return

        # Verify connection is alive before the 18-query loop
        try:
            client.get_collections()
        except Exception as e:
            err(f"Qdrant connection failed: {e}")
            return

        info("Querying tag counts from Qdrant...")
        tag_counts = []
        for tag in sorted(_DOMAIN_TAGS):
            try:
                result = client.count(
                    collection_name="grc_requirements",
                    count_filter=Filter(
                        must=[FieldCondition(key="domain_tags", match=MatchValue(value=tag))]
                    ),
                    exact=False,
                )
                if result.count > 0:
                    tag_counts.append((tag, result.count))
            except Exception as e:
                err(f"Query failed mid-loop: {e}")
                break

        if not tag_counts:
            warn("No tags found — is the corpus indexed?")
            return

        tag_counts.sort(key=lambda x: x[1], reverse=True)
        print("\nDomain Tags in Corpus")
        print("=====================")
        for tag, count in tag_counts:
            print(f"  {tag:<35} {count:>6}")
        total_assignments = sum(c for _, c in tag_counts)
        print(f"\n  {len(tag_counts)} tag(s) — {total_assignments:,} total tag assignments")
        print()

    # ------------------------------------------------------------------
    # analyze
    # ------------------------------------------------------------------

    def do_analyze(self, _arg: str) -> None:
        """Corpus quality summary: req counts by doc/tag/type, failure rates."""
        processed_dir = _reqbot._cfg.processed_dir_path()

        if not processed_dir.exists():
            err(f"Processed documents directory not found: {processed_dir}")
            return

        _ts_pattern = re.compile(r"_\d{8}_\d{6}$")

        def _latest(files: list, suffix: str) -> dict:
            seen: dict[str, Path] = {}
            for p in files:
                # Key off the filename (doc stem), not the directory name.
                # This is robust to custom --output-dir runs where multiple
                # documents land in the same parent directory.
                # removesuffix (anchored), not replace() — a PDF stem containing
                # this suffix as a substring elsewhere must not have it collapsed.
                key = p.stem.removesuffix(suffix)
                if key not in seen or p.stat().st_mtime > seen[key].stat().st_mtime:
                    seen[key] = p
            return seen

        latest_norm = _latest(
            sorted(processed_dir.rglob("*_requirements_normalized.jsonl")),
            "_requirements_normalized",
        )
        latest_fail = _latest(
            sorted(processed_dir.rglob("*_normalization_failures.jsonl")),
            "_normalization_failures",
        )

        if not latest_norm:
            warn("No normalized JSONL found.")
            return

        info("Reading corpus from disk...")

        total_reqs = 0
        total_failures = 0
        type_counts: dict[str, int] = {}
        tag_counts: dict[str, int] = {}
        doc_counts: list[tuple[str, int]] = []

        for doc_key, path in latest_norm.items():
            reqs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
            count = len(reqs)
            total_reqs += count
            doc_counts.append((doc_key, count))
            for req in reqs:
                rt = req.get("requirement_type", "unknown")
                type_counts[rt] = type_counts.get(rt, 0) + 1
                for tag in req.get("domain_tags", []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        for path in latest_fail.values():
            total_failures += sum(1 for line in open(path, encoding="utf-8") if line.strip())

        total_all = total_reqs + total_failures
        fail_rate = (total_failures / total_all * 100) if total_all else 0.0

        print("\nCorpus Analysis")
        print("===============")
        print(f"  Documents:    {len(latest_norm)}")
        print(f"  Requirements: {total_reqs:,}")
        print(f"  Failures:     {total_failures:,}  ({fail_rate:.1f}% of extracted)")

        print("\n  By Requirement Type")
        print("  " + "-" * 38)
        for rt, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            pct = count / total_reqs * 100 if total_reqs else 0.0
            print(f"    {rt:<25} {count:>6}  ({pct:.1f}%)")

        print("\n  Top Domain Tags")
        print("  " + "-" * 38)
        for tag, count in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            pct = count / total_reqs * 100 if total_reqs else 0.0
            print(f"    {tag:<35} {count:>6}  ({pct:.1f}%)")

        print("\n  Documents by Requirement Count")
        print("  " + "-" * 38)
        for doc_key, count in sorted(doc_counts, key=lambda x: x[1], reverse=True):
            print(f"    {doc_key:<35} {count:>6}")

        # Framework breakdown — shown only when authority registry is loaded
        if _reqbot._cfg.authority:
            framework_counts: dict[str, int] = {}
            doctype_counts: dict[str, int] = {}
            for doc_key, count in doc_counts:
                # Match by source_pdf containing the doc_key (strip timestamp suffix)
                entry = None
                for src_pdf, ae in _reqbot._cfg.authority.items():
                    stem = src_pdf.replace(".pdf", "")
                    _ts_pattern2 = re.compile(r"_\d{8}_\d{6}$")
                    clean_key = _ts_pattern2.sub("", doc_key)
                    if clean_key in stem or stem in clean_key:
                        entry = ae
                        break
                fw = entry.framework if entry else "Unknown"
                dt = entry.document_type if entry else "unknown"
                framework_counts[fw] = framework_counts.get(fw, 0) + count
                doctype_counts[dt] = doctype_counts.get(dt, 0) + count

            print("\n  By Framework (Authority Registry)")
            print("  " + "-" * 38)
            for fw, count in sorted(framework_counts.items(), key=lambda x: x[1], reverse=True):
                pct = count / total_reqs * 100 if total_reqs else 0.0
                print(f"    {fw:<25} {count:>6}  ({pct:.1f}%)")

            print("\n  By Document Type")
            print("  " + "-" * 38)
            for dt, count in sorted(doctype_counts.items(), key=lambda x: x[1], reverse=True):
                pct = count / total_reqs * 100 if total_reqs else 0.0
                print(f"    {dt:<25} {count:>6}  ({pct:.1f}%)")

        print()


    # ------------------------------------------------------------------
    # Internal helper — argparse death trap
    # ------------------------------------------------------------------

    def _parse_shell_args(
        self, parser: argparse.ArgumentParser, arg: str
    ) -> argparse.Namespace | None:
        """Split arg string and parse it. Returns None if parsing fails.

        Catches SystemExit (bad flags) and ValueError (unclosed quotes) so a
        bad command never kills the shell process.
        """
        try:
            tokens = shlex.split(arg)
        except ValueError as e:
            err(f"Parse error: {e}")
            return None
        try:
            return parser.parse_args(tokens)
        except SystemExit:
            return None

    # ------------------------------------------------------------------
    # ask
    # ------------------------------------------------------------------

    def do_ask(self, arg: str) -> None:
        """Ask a question against the indexed corpus.

        Usage: ask <question> [--synthesize] [--top-k N] [--model MODEL]
                              [--domain-tag TAG] [--requirement-type TYPE]
                              [--document-id ID] [--context] [--json] [--no-hyde]

        Active session filters (document_id, domain_tag, requirement_type)
        are auto-injected — no need to type them every time.
        """
        parser = argparse.ArgumentParser(prog="ask", add_help=True)
        parser.add_argument("question", help="Natural language question")
        parser.add_argument("--top-k", type=_positive_int, default=None, dest="top_k",
                            help="Number of results (default: session top_k)")
        parser.add_argument("--min-score", type=_non_negative_float, default=None, dest="min_score",
                            help="Minimum RRF score threshold (default: session min_score; 0 disables)")
        parser.add_argument("--synthesize", action="store_true",
                            help="Generate LLM answer")
        parser.add_argument("--model", type=str, default=None,
                            help="Override synthesis model")
        parser.add_argument("--domain-tag", action="append", dest="domain_tags",
                            default=[], help="Filter by domain tag (repeatable)")
        parser.add_argument("--requirement-type", action="append",
                            dest="requirement_types", default=[],
                            help="Filter by requirement type (repeatable)")
        parser.add_argument("--document-id", action="append", dest="document_ids",
                            default=[], help="Filter by document ID (repeatable)")
        parser.add_argument("--context", action="store_true",
                            help="Enrich with surrounding chunk context")
        parser.add_argument("--json", action="store_true", dest="json_output",
                            help="Output results as JSON")
        parser.add_argument("--no-hyde", action="store_true", dest="no_hyde",
                            help="Disable HyDE hypothesis leg — baseline dense + BM25 RRF only")

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        # Normalize and validate inline filter flags — gives immediate shell feedback
        # on unknown tags rather than a silent empty result at query time.
        domain_tags, requirement_types = _normalize_filter_flags(
            parsed.domain_tags, parsed.requirement_types
        )

        # Build namespace for cmd_ask
        ns = Namespace(
            question=parsed.question,
            top_k=parsed.top_k if parsed.top_k is not None else self._session["top_k"],
            min_score=parsed.min_score if parsed.min_score is not None else self._session["min_score"],
            synthesize=parsed.synthesize,
            model=parsed.model if parsed.model else self._session["synthesis_model"],
            domain_tags=domain_tags,
            requirement_types=requirement_types,
            document_ids=list(parsed.document_ids),
            json_output=parsed.json_output,
            context=parsed.context,
            no_rewrite=False,
            no_hyde=parsed.no_hyde,
            rewrite_model=_reqbot._cfg.rewrite_model,
            context_collection="grc_context",
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )

        # Target paradigm: auto-inject active session filters
        if self._session["document_id"] and not ns.document_ids:
            info(f"Filtering by document_id: {self._session['document_id']}")
            ns.document_ids = [self._session["document_id"]]
        if self._session["domain_tag"] and not ns.domain_tags:
            info(f"Filtering by domain_tag: {self._session['domain_tag']}")
            ns.domain_tags = [self._session["domain_tag"]]
        if self._session["requirement_type"] and not ns.requirement_types:
            info(f"Filtering by requirement_type: {self._session['requirement_type']}")
            ns.requirement_types = [self._session["requirement_type"]]

        # Warn once per session when remote synthesis is active
        if (parsed.synthesize
                and _reqbot._cfg.synthesis_backend == "remote"
                and not self._remote_synthesis_warned):
            provider = _reqbot._cfg.remote_provider
            model = _reqbot._cfg.remote_model
            print(f"\n[!] Remote synthesis enabled — evidence snippets will be sent to {provider}")
            print(f"    Model: {model}")
            print(f"    Only retrieved evidence and your query are transmitted (same text on screen).\n")
            self._remote_synthesis_warned = True

        info("Querying...")
        try:
            _reqbot.cmd_ask(ns)
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # ingest
    # ------------------------------------------------------------------

    def do_ingest(self, arg: str) -> None:
        """Run the full extraction pipeline on a PDF.

        Usage: ingest <pdf_path> [--no-index] [--layout-mode pymupdf|pdfplumber]
                                 [--model MODEL] [--output-dir DIR]
                                 [--max-chunks N]
        """
        parser = argparse.ArgumentParser(prog="ingest", add_help=True)
        parser.add_argument("pdf", help="Path to the PDF file")
        parser.add_argument("--output-dir", type=str, default=None, dest="output_dir")
        parser.add_argument("--model", type=str, default=None)
        parser.add_argument("--max-chunks", type=_positive_int, default=None, dest="max_chunks")
        parser.add_argument(
            "--no-index", action="store_true", dest="no_index",
            help="Skip indexing — write pipeline artifacts only (debug/inspection)",
        )
        # Deprecated: indexing is now the default, so --index is an inert no-op,
        # kept accepted so old shell history doesn't suddenly fail to parse.
        parser.add_argument("--index", action="store_true", help=argparse.SUPPRESS)
        parser.add_argument(
            "--layout-mode",
            choices=["pymupdf", "pdfplumber"],
            default="pymupdf",
            dest="layout_mode",
        )

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        ns = Namespace(
            pdf=parsed.pdf,
            output_dir=parsed.output_dir,
            model=parsed.model if parsed.model else self._session["default_model"],
            max_chunks=parsed.max_chunks,
            no_index=parsed.no_index,
            layout_mode=parsed.layout_mode,
            # cmd_ingest reads these unconditionally; the interactive shell has
            # no --skip-enrichment/--profile flags of its own, so supply the
            # same defaults cli/reqbot.py's argparse would (this Namespace was
            # previously missing both, which crashed cmd_ingest on every call).
            skip_enrichment=False,
            profile="cybersecurity",
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )

        try:
            rc = _reqbot.cmd_ingest(ns)
            if rc == 0:
                ok("Ingest complete.")
            else:
                err(f"Ingest failed (exit code {rc}).")
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # index
    # ------------------------------------------------------------------

    def do_index(self, arg: str) -> None:
        """Embed and index a normalized JSONL file into Qdrant.

        Usage: index <jsonl_path> [--recreate] [--batch-size N]
        """
        parser = argparse.ArgumentParser(prog="index", add_help=True)
        parser.add_argument("jsonl", help="Path to *_requirements_normalized.jsonl")
        parser.add_argument("--recreate", action="store_true",
                            help="Drop and recreate the Qdrant collection")
        parser.add_argument("--batch-size", type=_positive_int, default=None, dest="batch_size")

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        ns = Namespace(
            jsonl=parsed.jsonl,
            recreate=parsed.recreate,
            batch_size=parsed.batch_size,
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )

        try:
            rc = _reqbot.cmd_index(ns)
            if rc == 0:
                ok("Indexing complete.")
            else:
                err(f"Indexing failed (exit code {rc}).")
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # reindex
    # ------------------------------------------------------------------

    def do_reindex(self, arg: str) -> None:
        """Rebuild Qdrant from all existing JSONL (no re-extraction).

        Usage: reindex
        """
        ns = Namespace(
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )
        info("Starting reindex — this will take a while...")
        try:
            rc = _reqbot.cmd_reindex(ns)
            if rc == 0:
                ok("Reindex complete.")
            else:
                err(f"Reindex failed (exit code {rc}).")
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # batch
    # ------------------------------------------------------------------

    def do_batch(self, arg: str) -> None:
        """Run the full pipeline on every PDF in a directory.

        Usage: batch <pdf_dir> [--layout-mode pymupdf|pdfplumber] [--model MODEL]
        """
        parser = argparse.ArgumentParser(prog="batch", add_help=True)
        parser.add_argument("pdf_dir", help="Directory containing PDF files")
        parser.add_argument("--model", type=str, default=None)
        parser.add_argument(
            "--layout-mode",
            choices=["pymupdf", "pdfplumber"],
            default="pymupdf",
            dest="layout_mode",
        )

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        ns = Namespace(
            pdf_dir=parsed.pdf_dir,
            model=parsed.model if parsed.model else self._session["default_model"],
            layout_mode=parsed.layout_mode,
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )

        try:
            rc = _reqbot.cmd_batch(ns)
            if rc == 0:
                ok("Batch complete.")
            else:
                err(f"Batch failed (exit code {rc}).")
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # trace  (Phase 8.1)
    # ------------------------------------------------------------------

    def do_trace(self, arg: str) -> None:
        """Trace the full provenance of a requirement by ID.

        Usage: trace <requirement_id> [--context] [--json]

        Displays:
          - Full provenance (document, page, source_ref, extraction model, run date)
          - Verbatim source quote
          - Surrounding context chunk (--context, requires grc_context index)
          - Cross-framework matches (other documents with the same source_ref)

        Example:
          trace REQ-a3f2c1d4e5b6
          trace REQ-a3f2c1d4e5b6 --context
          trace REQ-a3f2c1d4e5b6 --json
        """
        parser = argparse.ArgumentParser(prog="trace", add_help=True)
        parser.add_argument("requirement_id", help="Requirement ID (e.g. REQ-a3f2c1d4e5b6)")
        parser.add_argument("--json", action="store_true", dest="json_output",
                            help="Output as JSON")
        parser.add_argument("--context", action="store_true",
                            help="Include surrounding raw chunk text from grc_context")

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        ns = Namespace(
            requirement_id=parsed.requirement_id,
            json_output=parsed.json_output,
            context=parsed.context,
            qdrant_url=self._session["qdrant_url"],
        )

        try:
            _reqbot.cmd_trace(ns)
        except SystemExit:
            pass

    # ------------------------------------------------------------------
    # compare  (Phase 8.2)
    # ------------------------------------------------------------------

    def do_compare(self, arg: str) -> None:
        """Compare a control ID or query across all indexed documents.

        Usage: compare <control_id_or_query> [--top-k N] [--json] [--markdown]
                                             [--document-id ID]

        Input modes:
          compare AC-2                  — exact source_ref match across all docs
          compare IA-5                  — same, for any control ID pattern
          compare "account management"  — semantic search, grouped by control ID

        Session document_id filter is auto-injected when set.

        Examples:
          compare AC-2
          compare IA-5(1)
          compare "password complexity requirements"
          compare AC-2 --markdown
          compare "encryption" --top-k 30
        """
        parser = argparse.ArgumentParser(prog="compare", add_help=True)
        parser.add_argument("query", help="Control ID (e.g. AC-2) or free-text query")
        parser.add_argument("--top-k", type=_positive_int, default=None, dest="top_k",
                            help="Results for semantic search (default: session top_k)")
        parser.add_argument("--json", action="store_true", dest="json_output",
                            help="Output as JSON")
        parser.add_argument("--markdown", action="store_true", dest="markdown_output",
                            help="Output as Markdown")
        parser.add_argument("--document-id", action="append", dest="document_ids", default=[],
                            help="Filter by document ID (repeatable)")

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        ns = Namespace(
            query=parsed.query,
            top_k=parsed.top_k if parsed.top_k is not None else self._session["top_k"],
            json_output=parsed.json_output,
            markdown_output=parsed.markdown_output,
            document_ids=list(parsed.document_ids),
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )

        # Auto-inject session document_id filter (same pattern as do_ask)
        if self._session["document_id"] and not ns.document_ids:
            info(f"Filtering by document_id: {self._session['document_id']}")
            ns.document_ids = [self._session["document_id"]]

        try:
            _reqbot.cmd_compare(ns)
        except SystemExit:
            pass

    # ------------------------------------------------------------------

    def do_evidence(self, arg: str) -> None:
        """Export a defensible evidence pack grouped by control ID.

        Usage: evidence <query> [--format markdown|json] [--output FILE]
                                [--context] [--top-k N] [--document-id ID]
                                [--domain-tag TAG] [--requirement-type TYPE]

        Retrieves requirements matching the query, groups them by control ID
        (source_ref), and exports a structured evidence pack suitable for
        pasting into SSPs, POA&Ms, and audit artifacts.

        Session filters (document_id, domain_tag, requirement_type) are
        auto-injected when set.

        Examples:
          evidence "password complexity requirements"
          evidence "account management" --format json
          evidence "encryption at rest" --output enc-evidence.md
          evidence "access control" --context --top-k 30
        """
        parser = argparse.ArgumentParser(prog="evidence", add_help=True)
        parser.add_argument("query", help="Query to retrieve requirements for")
        parser.add_argument("--format", type=str, choices=["markdown", "json"],
                            default="markdown", dest="output_format",
                            help="Output format: markdown (default) or json")
        parser.add_argument("--output", type=str, default=None, dest="output_file",
                            help="Write output to FILE instead of printing")
        parser.add_argument("--context", action="store_true",
                            help="Include surrounding raw chunk text from grc_context")
        parser.add_argument("--top-k", type=_positive_int, default=None, dest="top_k",
                            help="Number of results to retrieve (default: session top_k or 20)")
        parser.add_argument("--document-id", action="append", dest="document_ids", default=[],
                            help="Filter by document ID (repeatable)")
        parser.add_argument("--domain-tag", action="append", default=[], dest="domain_tags",
                            help="Filter by domain tag (repeatable)")
        parser.add_argument("--requirement-type", action="append", default=[],
                            dest="requirement_types",
                            help="Filter by requirement type (repeatable)")

        parsed = self._parse_shell_args(parser, arg)
        if parsed is None:
            return

        # Normalize and validate inline filter flags — consistent with do_ask()
        domain_tags, requirement_types = _normalize_filter_flags(
            parsed.domain_tags, parsed.requirement_types
        )

        top_k = parsed.top_k if parsed.top_k is not None else max(self._session["top_k"], 20)

        ns = Namespace(
            query=parsed.query,
            output_format=parsed.output_format,
            output_file=parsed.output_file,
            context=parsed.context,
            top_k=top_k,
            document_ids=list(parsed.document_ids),
            domain_tags=domain_tags,
            requirement_types=requirement_types,
            ollama_url=self._session["ollama_url"],
            qdrant_url=self._session["qdrant_url"],
        )

        # Auto-inject session filters (same pattern as do_ask)
        if self._session["document_id"] and not ns.document_ids:
            info(f"Filtering by document_id: {self._session['document_id']}")
            ns.document_ids = [self._session["document_id"]]
        if self._session["domain_tag"] and not ns.domain_tags:
            info(f"Filtering by domain_tag: {self._session['domain_tag']}")
            ns.domain_tags = [self._session["domain_tag"]]
        if self._session["requirement_type"] and not ns.requirement_types:
            info(f"Filtering by requirement_type: {self._session['requirement_type']}")
            ns.requirement_types = [self._session["requirement_type"]]

        # Warn once per session when remote synthesis is active
        # (evidence always synthesizes — no --synthesize flag required)
        if (_reqbot._cfg.synthesis_backend == "remote"
                and not self._remote_synthesis_warned):
            provider = _reqbot._cfg.remote_provider
            model = _reqbot._cfg.remote_model
            print(f"\n[!] Remote synthesis enabled — evidence snippets will be sent to {provider}")
            print(f"    Model: {model}")
            print(f"    Only retrieved evidence and your query are transmitted (same text on screen).\n")
            self._remote_synthesis_warned = True

        try:
            _reqbot.cmd_evidence(ns)
        except SystemExit:
            pass

    # ------------------------------------------------------------------

    def do_authority(self, _arg: str) -> None:
        """Display the authority metadata registry.

        Usage: authority

        Shows all documents registered in ~/.config/reqbot/authority.json with their
        authority weights, framework labels, and document types.

        Authority weight guidance:
          5 — Mandatory DoD policy directive (DoDI, DoDD)
          4 — CNSSI overlay / DoD instruction supplement
          3 — NIST SP framework
          2 — Guidance / best practice (STIG, CIS)
          1 — Informational reference
        """
        authority = _reqbot._cfg.authority
        if not authority:
            registry_path = _reqbot._cfg.authority_registry or str(
                _reqbot._config.AUTHORITY_REGISTRY_PATH
            )
            warn(f"No authority registry loaded.")
            print(f"  Create {registry_path} to enable framework authority tracking.")
            print()
            print("  Example authority.json:")
            print('  {')
            print('    "documents": [')
            print('      {')
            print('        "source_pdf": "NIST.SP.800-53r5.pdf",')
            print('        "document_type": "framework",')
            print('        "framework": "NIST",')
            print('        "revision": "Rev 5",')
            print('        "publication_date": "2020-09",')
            print('        "authority_weight": 3')
            print('      }')
            print('    ]')
            print('  }')
            return

        entries = sorted(authority.values(), key=lambda e: e.authority_weight, reverse=True)

        print("\nAuthority Registry")
        print("==================")
        print(f"  {'Weight':<8} {'Framework':<12} {'Type':<22} {'Document'}")
        print("  " + "-" * 70)
        for e in entries:
            print(
                f"  {e.authority_weight:<8} {e.framework:<12} {e.document_type:<22} {e.source_pdf}"
            )
        print(f"\n  {len(entries)} document(s) registered.")
        print()


# ---------------------------------------------------------------------------
# Launch function (called by reqbot.py when invoked with no arguments)
# ---------------------------------------------------------------------------

def launch() -> None:
    """Suppress INFO log spam and start the interactive shell."""
    logging.getLogger().setLevel(logging.WARNING)

    if _READLINE_AVAILABLE:
        try:
            _readline.read_history_file(_HIST_FILE)
        except OSError:
            pass

    cfg = _config.load()
    print(BANNER)

    console = GrcaiConsole(cfg)
    try:
        console.cmdloop()
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    launch()

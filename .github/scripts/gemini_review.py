"""
Gemini PR reviewer — called by .github/workflows/gemini_reviewer.yml.
Reads diff.txt, sends to Gemini with ReqBot-specific context, then
posts or updates a single review comment on the PR.
"""

import json
import os
import subprocess
import sys

from google import genai

MARKER = "<!-- gemini-review -->"

PROMPT_CONTEXT = """
You are a senior Python engineer reviewing a Pull Request on ReqBot, a local-AI compliance research pipeline.

## What ReqBot Is
ReqBot extracts cybersecurity requirements from regulatory PDFs (NIST, DoDI, AFI, CNSSI, etc.) using a
local LLM (Ollama) and indexes them into a hybrid Qdrant vector database for search and analysis.

## Pipeline Architecture
- Step A: PDF -> pages JSONL (extract_pdf_to_text.py)
- Step B: pages -> chunks JSONL (chunk_text.py)
- Step C: chunks -> extracted requirements via LLM (llm_extract_requirements.py) -- the expensive step
- Step D: normalize, validate, deduplicate (parse_and_normalize.py)
- Step E: aggregate stats (aggregate_and_export.py)
- Step F: embed + index into Qdrant grc_requirements collection (embed_and_index.py)
- Step F2: embed raw chunks into grc_context collection (embed_context_index.py)
- Query layer: ask.py -- hybrid dense+sparse search with RRF fusion, query rewriting, optional LLM synthesis

## Key Patterns and Constraints
- System Python, no venv. Dependencies installed with pip3 --break-system-packages.
- JSONL is the source of record. Qdrant is a rebuildable index -- never treat it as ground truth.
- source_quote is the primary asset (verbatim text from source doc). description is secondary/interpretive.
- All pipeline scripts must remain independently runnable with --help.
- No new pip dependencies without discussion -- targets air-gapped environments.
- Qdrant collections use hybrid dense (nomic-embed-text 768-dim) + sparse (BM25) with RRF fusion.
- LLM calls go to Ollama (local). Config loaded from ~/.config/reqbot/config.json with env var overrides.
- Three-layer config: hardcoded defaults -> config.json -> REQBOT_* env vars.
- Argparse validators (_positive_int, _non_negative_float) must be used for all numeric CLI args.
- Input normalization (_normalize_filter_flags) must be applied before building Namespace in shell commands.

## What to Focus On
1. Correctness bugs -- especially in data flow between pipeline steps, JSON parsing, and Qdrant operations
2. Regressions -- does this change break any existing behavior in ask.py, console.py, or reqbot.py?
3. Data integrity -- are JSONL records validated correctly? Is source_quote handled with proper fallback guards?
4. Config/CLI consistency -- are new options wired through all three layers (config.py, reqbot.py, console.py)?
5. Edge cases -- empty strings, None values, zero/negative numerics, missing fields in JSONL records
6. Step C cache invalidation -- changes to PROMPT_TEMPLATE in llm_extract_requirements.py invalidate all cached extractions

## What to Ignore
- Style preferences, docstring formatting, minor naming conventions
- Performance optimizations unless there is a clear bottleneck
- Hypothetical future requirements not in scope of this PR

Provide concise, actionable feedback in Markdown. Flag bugs as **Bug**, regressions as **Regression**,
and improvements as **Suggestion**. If the change looks clean, say so explicitly.
"""


def get_review(diff: str) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=PROMPT_CONTEXT + "\nHere is the diff:\n" + diff,
    )
    return response.text


def find_existing_comment(repo: str, pr_number: str) -> str | None:
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{repo}/issues/{pr_number}/comments",
            "--jq",
            f'[.[] | select(.body | startswith("{MARKER}"))] | first | .id',
        ],
        capture_output=True,
        text=True,
    )
    comment_id = result.stdout.strip()
    return comment_id if comment_id and comment_id != "null" else None


def post_comment(repo: str, pr_number: str, body: str) -> None:
    subprocess.run(
        ["gh", "pr", "comment", pr_number, "--body", body],
        check=True,
    )


def update_comment(repo: str, comment_id: str, body: str) -> None:
    payload = json.dumps({"body": body})
    subprocess.run(
        [
            "gh", "api",
            f"repos/{repo}/issues/comments/{comment_id}",
            "-X", "PATCH",
            "--input", "-",
        ],
        input=payload,
        text=True,
        check=True,
    )


def main() -> None:
    diff = open("diff.txt").read()
    if not diff.strip():
        print("No diff found — skipping review.")
        sys.exit(0)

    pr_number = os.environ["PR_NUMBER"]
    repo = os.environ["GITHUB_REPOSITORY"]

    print("Generating Gemini review...")
    review_text = get_review(diff)
    full_body = f"{MARKER}\n{review_text}"

    comment_id = find_existing_comment(repo, pr_number)
    if comment_id:
        print(f"Updating existing review comment {comment_id}...")
        update_comment(repo, comment_id, full_body)
    else:
        print("Posting new review comment...")
        post_comment(repo, pr_number, full_body)

    print("Done.")


if __name__ == "__main__":
    main()

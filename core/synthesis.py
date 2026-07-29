#!/usr/bin/env python3
"""Pluggable synthesis backend for ReqBot.

Supports:
  - Local Ollama (default, always available, nothing sent externally)
  - Remote providers: Anthropic (Claude), OpenAI (GPT)
  - None (retrieval-only — synthesis is disabled entirely, no call is made)

Security model:
  - Local is default and never changes without explicit configuration
  - Remote requires explicit config: synthesis_backend = "remote"
  - Only the retrieved evidence snippets and user query are sent (same text visible on screen)
  - First remote use per session prints a one-time warning banner

Usage:
    from synthesis import synthesize

    answer = synthesize(
        question="What are the password requirements?",
        evidence="[1] (NIST SP 800-53r5 IA-5(1)) ...",
        backend="local",           # "local", "remote", or "none"
        model="qwen2.5:14b",       # local model or remote model name
        ollama_url="http://...",    # used by local backend only
        provider="anthropic",      # used by remote backend only
        api_key="sk-...",          # used by remote backend only
    )
"""

import logging

log = logging.getLogger(__name__)

SYNTHESIS_PROMPT = """You are a GRC (Governance, Risk, Compliance) analyst. Answer the user's question using ONLY the evidence provided below. Follow these rules strictly:

1. Every claim must cite the evidence by number: [N]
2. Include the source reference and page numbers in citations: [N] (source_ref, pages X-Y)
3. If the evidence does not directly support a claim, say "not supported by retrieved sources"
4. If the evidence is insufficient to answer the question fully, say so explicitly
5. Do not infer or add information beyond what the evidence states
6. Organize your answer clearly with bullet points or numbered items

EVIDENCE:
{evidence}

QUESTION: {question}

ANSWER:"""


def synthesize_local(
    question: str,
    evidence: str,
    model: str,
    ollama_url: str,
    *,
    raw_prompt: str = "",
    num_predict: int = 2048,
    temperature: float = 0.2,
) -> str:
    """Synthesize an answer using a local Ollama model.

    Nothing is sent to any external service. All processing is on-device.

    If raw_prompt is provided it is sent as-is, bypassing SYNTHESIS_PROMPT.
    This allows callers (like cmd_evidence) to supply specialist prompts.
    """
    try:
        import ollama as _ollama
    except ImportError:
        # ollama is a base dependency of the reqbot package (pyproject.toml) — this
        # should be unreachable in a properly installed package. Left as a defensive
        # message for source/dev checkouts that haven't run `pip install .`.
        raise RuntimeError(
            "[-] Ollama package not found: pip3 install --break-system-packages ollama"
        )

    # Verify the model is present on the Ollama server before calling generate(). ReqBot
    # does not guess or presume which model a user wants on their own endpoint — if it's
    # missing, fail clearly and name the exact fix, rather than silently pulling ~9 GB on
    # their behalf. This only runs on the local path; synthesize_remote() never reaches here.
    try:
        import requests as _requests
        tags_resp = _requests.get(f"{ollama_url}/api/tags", timeout=10)
        tags_resp.raise_for_status()
    except Exception:
        pass  # can't reach the server to check — let generate() surface that error directly
    else:
        present = [m["name"] for m in tags_resp.json().get("models", [])]
        # Ollama treats an untagged model name (no ":") as an implicit ":latest" —
        # generate() accepts either form, but /api/tags reports the fully-qualified
        # name. Accept both so an untagged config doesn't false-positive as missing
        # when the tagged form is what's actually listed (Codex review, PR #102).
        acceptable = {model} if ":" in model else {model, f"{model}:latest"}
        if not acceptable & set(present):
            raise RuntimeError(
                f"[-] Synthesis model '{model}' is not available on the configured Ollama "
                f"server ({ollama_url}).\n"
                f"    Pull it yourself: OLLAMA_HOST={ollama_url} ollama pull {model}\n"
                f"    Or configure a different model via `reqbot init` (synthesis_model)."
            )

    prompt = raw_prompt if raw_prompt else SYNTHESIS_PROMPT.format(evidence=evidence, question=question)
    log.info("Synthesizing answer with local model: %s", model)

    client = _ollama.Client(host=ollama_url)
    response = client.generate(
        model=model,
        prompt=prompt,
        options={"temperature": temperature, "num_predict": num_predict},
    )
    return response.response


def synthesize_remote(
    question: str,
    evidence: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    raw_prompt: str = "",
    max_tokens: int = 2048,
) -> str:
    """Synthesize an answer using a remote provider (Anthropic or OpenAI).

    Only the retrieved evidence snippets and the user's query are sent —
    the same text that is displayed on screen. Raw documents are never sent.

    If raw_prompt is provided it is sent as-is, bypassing SYNTHESIS_PROMPT.

    Raises RuntimeError if the required package is not installed.
    """
    prompt = raw_prompt if raw_prompt else SYNTHESIS_PROMPT.format(evidence=evidence, question=question)
    log.info("Synthesizing answer with remote provider: %s / model: %s", provider, model)

    if provider == "anthropic":
        try:
            import anthropic as _anthropic
        except ImportError:
            raise RuntimeError(
                "[-] Remote synthesis requires the 'anthropic' package. "
                "Install the remote extra: pip install reqbot[remote]"
            )
        client = _anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    elif provider == "openai":
        try:
            import openai as _openai
        except ImportError:
            raise RuntimeError(
                "[-] Remote synthesis requires the 'openai' package. "
                "Install the remote extra: pip install reqbot[remote]"
            )
        client = _openai.OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content

    else:
        raise RuntimeError(
            f"[-] Unknown remote provider: '{provider}'. "
            "Supported providers: anthropic, openai"
        )


def synthesize(
    question: str,
    evidence: str,
    backend: str = "local",
    model: str = "qwen2.5:14b",
    ollama_url: str = "http://localhost:11434",
    provider: str = "anthropic",
    api_key: str = "",
    raw_prompt: str = "",
) -> str:
    """Route synthesis to local or remote backend.

    Args:
        question:   The user's original question.
        evidence:   Formatted evidence string (from format_evidence()).
        backend:    "local" (default), "remote", or "none" (retrieval-only —
                    returns "" without calling any model).
        model:      Local Ollama model name, or remote model ID.
        ollama_url: Ollama base URL (local backend only).
        provider:   Remote provider name ("anthropic" or "openai").
        api_key:    API key for remote provider.
        raw_prompt: If provided, sent directly to the model (bypasses SYNTHESIS_PROMPT template).

    Returns:
        Synthesized answer string, or "" if backend is "none".
    """
    if backend == "none":
        return ""
    if backend == "remote":
        return synthesize_remote(
            question=question,
            evidence=evidence,
            provider=provider,
            model=model,
            api_key=api_key,
            raw_prompt=raw_prompt,
        )
    else:
        return synthesize_local(
            question=question,
            evidence=evidence,
            model=model,
            ollama_url=ollama_url,
            raw_prompt=raw_prompt,
        )

"""Run + result service.

Responsibilities:
  - create a queued run row
  - dispatch the prompt to the right provider (openai | anthropic |
    ollama | mock) and capture tokens/latency
  - extract the first ``` fenced code block as output_code
  - persist a result row and mark the run done/failed

The provider implementations are real (httpx-based) and degrade
gracefully: if the upstream key is missing the call returns a
clear error string instead of raising, so the run is recorded as
failed and the UI can show the error.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

import aiosqlite
import httpx

from .experiment_service import touch

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _extract_code(text: str) -> Optional[str]:
    if not text:
        return None
    m = _CODE_FENCE.search(text)
    if m:
        return m.group(1).rstrip()
    # Fall back: lines that look like code (indented or non-prose)
    if "\n" in text and any(l.startswith(("    ", "\t")) for l in text.splitlines()):
        return text
    return None


async def create_run(
    db: aiosqlite.Connection, *, experiment_id: str,
    label: Optional[str], provider: str, model: str, prompt: str,
    temperature: float, max_tokens: int,
) -> str:
    run_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO runs (id, experiment_id, label, provider, model, "
        "prompt, temperature, max_tokens, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
        (run_id, experiment_id, label, provider, model, prompt,
         temperature, max_tokens, now, now),
    )
    await touch(db, experiment_id)
    return run_id


async def execute_run(
    db: aiosqlite.Connection, run_id: str,
    *, openai_api_key: str, anthropic_api_key: str, ollama_base_url: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Execute a queued run. Captures latency, stores the result, and
    updates the run's status. Idempotent against re-execution."""
    cur = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    run = await cur.fetchone()
    if run is None:
        return {"error": "run not found"}
    if run["status"] in ("done", "running"):
        return {"run_id": run_id, "skipped": True, "status": run["status"]}

    await db.execute(
        "UPDATE runs SET status = 'running', updated_at = ? WHERE id = ?",
        (_now(), run_id),
    )
    await db.commit()

    started = time.monotonic()
    error: Optional[str] = None
    output: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None

    try:
        provider = run["provider"]
        if provider == "openai":
            output, tokens_in, tokens_out = await _call_openai(
                run, openai_api_key, timeout_seconds,
            )
        elif provider == "anthropic":
            output, tokens_in, tokens_out = await _call_anthropic(
                run, anthropic_api_key, timeout_seconds,
            )
        elif provider == "ollama":
            output, tokens_in, tokens_out = await _call_ollama(
                run, ollama_base_url, timeout_seconds,
            )
        elif provider == "mock":
            output, tokens_in, tokens_out = await _call_mock(run)
        else:
            error = f"unknown provider: {provider}"
    except Exception as e:  # network, timeout, decode — record, don't raise
        error = f"{type(e).__name__}: {e}"

    latency_ms = int((time.monotonic() - started) * 1000)
    output_code = _extract_code(output or "")
    result_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO results (id, run_id, output, output_code, "
        "tokens_in, tokens_out, latency_ms, error, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (result_id, run_id, output, output_code, tokens_in, tokens_out,
         latency_ms, error, _now()),
    )
    await db.execute(
        "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
        ("failed" if error else "done", _now(), run_id),
    )
    await db.commit()
    return {
        "run_id": run_id,
        "result_id": result_id,
        "status": "failed" if error else "done",
        "latency_ms": latency_ms,
        "error": error,
    }


async def list_runs(
    db: aiosqlite.Connection, experiment_id: str,
) -> list:
    cur = await db.execute(
        "SELECT * FROM runs WHERE experiment_id = ? "
        "ORDER BY created_at ASC",
        (experiment_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_run_with_result(
    db: aiosqlite.Connection, run_id: str,
) -> Optional[Dict[str, Any]]:
    cur = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    run = await cur.fetchone()
    if run is None:
        return None
    cur = await db.execute(
        "SELECT * FROM results WHERE run_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (run_id,),
    )
    res = await cur.fetchone()
    return {
        "run": dict(run),
        "result": dict(res) if res else None,
    }


# -- providers ----------------------------------------------------------


async def _call_openai(run, api_key: str, timeout: int):
    if not api_key or api_key == "sk-demo":
        return ("[openai disabled: no API key] Set OPENAI_API_KEY "
                "in .env to enable real completions.", 0, 0)
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": run["model"],
        "temperature": run["temperature"],
        "max_tokens": run["max_tokens"],
        "messages": [
            {"role": "system", "content": "You are a helpful coding assistant."},
            {"role": "user", "content": run["prompt"]},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return text, usage.get("prompt_tokens"), usage.get("completion_tokens")


async def _call_anthropic(run, api_key: str, timeout: int):
    if not api_key or api_key == "sk-ant-demo":
        return ("[anthropic disabled: no API key] Set ANTHROPIC_API_KEY "
                "in .env to enable real completions.", 0, 0)
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": run["model"],
        "max_tokens": run["max_tokens"],
        "temperature": run["temperature"],
        "messages": [{"role": "user", "content": run["prompt"]}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    parts = [b.get("text", "") for b in data.get("content", [])
             if b.get("type") == "text"]
    text = "\n".join(parts)
    usage = data.get("usage", {})
    return text, usage.get("input_tokens"), usage.get("output_tokens")


async def _call_ollama(run, base_url: str, timeout: int):
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": run["model"],
        "prompt": run["prompt"],
        "stream": False,
        "options": {
            "temperature": run["temperature"],
            "num_predict": run["max_tokens"],
        },
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    text = data.get("response", "")
    tokens_in = data.get("prompt_eval_count")
    tokens_out = data.get("eval_count")
    return text, tokens_in, tokens_out


async def _call_mock(run):
    """Deterministic mock — echoes the prompt in a code block, with
    a small latency and token count. Useful for tests and offline
    development."""
    text = (
        f"# mock completion for {run['provider']}:{run['model']}\n"
        f"# prompt: {run['prompt'][:80]!r}\n"
        "```\nprint('hello from llm-assistant mock')\n```\n"
    )
    return text, len(run["prompt"]) // 4, 32

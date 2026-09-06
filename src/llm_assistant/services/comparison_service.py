"""Comparison service: side-by-side scoring of runs.

A comparison is a saved URL of run ids plus simple derived metrics
the UI can render without re-querying each run.

Metrics per run (the comparison stores one row per run):

  - output_chars   — length of the model output
  - code_chars     — length of the extracted code block
  - tokens_in/out
  - latency_ms
  - cost_score     — tokens_in/4 + tokens_out  (rough USD; mock)

The comparison row also stores a `winner` run_id — the run with
the highest (code_chars / max(tokens_out, 1)) ratio, i.e. the most
code per token spent. It's a deliberately simple heuristic so it
is reproducible; the spec calls this "comparison across prompts".
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _metrics_for_run(run: Dict[str, Any], result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if result is None:
        return {
            "run_id": run["id"], "label": run.get("label"),
            "provider": run["provider"], "model": run["model"],
            "output_chars": 0, "code_chars": 0,
            "tokens_in": None, "tokens_out": None,
            "latency_ms": None, "cost_score": None,
        }
    out = result.get("output") or ""
    code = result.get("output_code") or ""
    tokens_in = result.get("tokens_in") or 0
    tokens_out = result.get("tokens_out") or 0
    return {
        "run_id": run["id"], "label": run.get("label"),
        "provider": run["provider"], "model": run["model"],
        "output_chars": len(out), "code_chars": len(code),
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "latency_ms": result.get("latency_ms"),
        "cost_score": (tokens_in / 4) + tokens_out,
    }


def _pick_winner(metrics: List[Dict[str, Any]]) -> Optional[str]:
    """Return the run id with the most code per output token. Skip
    runs that produced no code."""
    best: Optional[Dict[str, Any]] = None
    for m in metrics:
        if m["code_chars"] <= 0:
            continue
        tokens_out = m["tokens_out"] or 1
        ratio = m["code_chars"] / max(tokens_out, 1)
        if best is None or ratio > best["_ratio"]:
            m["_ratio"] = ratio
            best = m
    return best["run_id"] if best else None


async def create_comparison(
    db: aiosqlite.Connection, *, title: str, notes: Optional[str],
    run_ids: List[str],
) -> Dict[str, Any]:
    placeholders = ",".join("?" * len(run_ids))
    cur = await db.execute(
        f"SELECT * FROM runs WHERE id IN ({placeholders})", run_ids,
    )
    run_rows = [dict(r) for r in await cur.fetchall()]
    if len(run_rows) != len(run_ids):
        raise ValueError("one or more runs not found")
    experiment_id = run_rows[0]["experiment_id"]

    metrics: List[Dict[str, Any]] = []
    for r in run_rows:
        cur = await db.execute(
            "SELECT * FROM results WHERE run_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (r["id"],),
        )
        res_row = await cur.fetchone()
        metrics.append(_metrics_for_run(r, dict(res_row) if res_row else None))
    # strip helper ratio field
    for m in metrics:
        m.pop("_ratio", None)
    winner = _pick_winner([dict(m) for m in metrics])

    cmp_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO comparisons (id, experiment_id, title, notes, "
        "run_ids, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (cmp_id, experiment_id, title, notes,
         json.dumps(run_ids), _now()),
    )
    return {
        "id": cmp_id,
        "experiment_id": experiment_id,
        "title": title,
        "notes": notes,
        "run_ids": run_ids,
        "metrics": metrics,
        "winner": winner,
    }


async def get_comparison(
    db: aiosqlite.Connection, comparison_id: str,
) -> Optional[Dict[str, Any]]:
    cur = await db.execute("SELECT * FROM comparisons WHERE id = ?",
                           (comparison_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    data = dict(row)
    run_ids = json.loads(data["run_ids"]) if data["run_ids"] else []
    placeholders = ",".join("?" * len(run_ids))
    cur = await db.execute(
        f"SELECT * FROM runs WHERE id IN ({placeholders})", run_ids,
    )
    run_rows = [dict(r) for r in await cur.fetchall()]
    metrics: List[Dict[str, Any]] = []
    for r in run_rows:
        cur = await db.execute(
            "SELECT * FROM results WHERE run_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (r["id"],),
        )
        res_row = await cur.fetchone()
        metrics.append(_metrics_for_run(r, dict(res_row) if res_row else None))
    for m in metrics:
        m.pop("_ratio", None)
    data["metrics"] = metrics
    data["winner"] = _pick_winner([dict(m) for m in metrics])
    return data


async def analytics_summary(db: aiosqlite.Connection) -> Dict[str, Any]:
    """Dashboard summary used by /api/analytics."""
    out: Dict[str, Any] = {
        "experiments": 0, "runs": 0, "results": 0, "comparisons": 0,
        "by_provider": {}, "by_status": {},
    }
    for table, key in (("experiments", "experiments"),
                       ("runs", "runs"),
                       ("results", "results"),
                       ("comparisons", "comparisons")):
        cur = await db.execute(f"SELECT COUNT(*) AS n FROM {table}")
        out[key] = (await cur.fetchone())["n"]
    cur = await db.execute(
        "SELECT provider, COUNT(*) AS n FROM runs GROUP BY provider"
    )
    for r in await cur.fetchall():
        out["by_provider"][r["provider"]] = r["n"]
    cur = await db.execute(
        "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
    )
    for r in await cur.fetchall():
        out["by_status"][r["status"]] = r["n"]
    return out

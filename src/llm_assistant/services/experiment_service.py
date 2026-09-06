"""Experiment service: CRUD on experiments + tag filtering.

Pure async aiosqlite — the routes call this; the schema is owned
by core/db.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def create_experiment(
    db: aiosqlite.Connection,
    *, name: str, task: str, input_code: Optional[str], tags: List[str],
) -> str:
    exp_id = str(uuid.uuid4())
    now = _now()
    await db.execute(
        "INSERT INTO experiments (id, name, task, input_code, tags, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (exp_id, name, task, input_code, json.dumps(tags), now, now),
    )
    return exp_id


async def list_experiments(
    db: aiosqlite.Connection, *, tag: Optional[str] = None, limit: int = 200,
) -> List[dict]:
    if tag:
        cur = await db.execute(
            "SELECT * FROM experiments WHERE tags LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f'%"{tag}"%', limit),
        )
    else:
        cur = await db.execute(
            "SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in await cur.fetchall()]


async def get_experiment(
    db: aiosqlite.Connection, experiment_id: str,
) -> Optional[dict]:
    cur = await db.execute("SELECT * FROM experiments WHERE id = ?",
                           (experiment_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def touch(db: aiosqlite.Connection, experiment_id: str) -> None:
    """Bump updated_at when a new run is added under the experiment."""
    await db.execute(
        "UPDATE experiments SET updated_at = ? WHERE id = ?",
        (_now(), experiment_id),
    )

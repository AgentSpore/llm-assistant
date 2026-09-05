"""HTTP router for LLM Assistant experiments.

Surface (all paths under /api, mounted in main.py):

  POST /experiments              — create an experiment
  GET  /experiments              — list experiments
  GET  /experiments/{id}         — fetch one experiment
  POST /experiments/{id}/runs    — create a run under an experiment
  GET  /experiments/{id}/runs    — list runs for an experiment
  GET  /runs/{id}                — fetch run + result
  POST /comparisons              — create a comparison
  GET  /comparisons/{id}         — fetch comparison
  GET  /models                   — list the model catalog
  GET  /analytics                — dashboard summary

The service layer (G4) implements the run/result/comparison logic.
G3 wires the routes and delegates to the service via lazy imports.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core.db import get_db
from ..schemas.experiment import (
    AnalyticsResponse,
    Comparison,
    CreateComparison,
    CreateExperiment,
    CreateRun,
    Experiment,
    ModelEntry,
    Result,
    Run,
)

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_experiment(row) -> Experiment:
    tags = []
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except Exception:
            tags = []
    return Experiment(
        id=row["id"], name=row["name"], task=row["task"],
        input_code=row["input_code"], tags=tags,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_run(row) -> Run:
    return Run(
        id=row["id"], experiment_id=row["experiment_id"],
        label=row["label"], provider=row["provider"],
        model=row["model"], prompt=row["prompt"],
        temperature=row["temperature"], max_tokens=row["max_tokens"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_result(row) -> Result:
    return Result(
        id=row["id"], run_id=row["run_id"],
        output=row["output"], output_code=row["output_code"],
        tokens_in=row["tokens_in"], tokens_out=row["tokens_out"],
        latency_ms=row["latency_ms"], error=row["error"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_comparison(row) -> Comparison:
    run_ids = json.loads(row["run_ids"]) if row["run_ids"] else []
    return Comparison(
        id=row["id"], experiment_id=row["experiment_id"],
        title=row["title"], notes=row["notes"], run_ids=run_ids,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


@router.post("/experiments", response_model=Experiment,
             status_code=status.HTTP_201_CREATED)
async def create_experiment(req: CreateExperiment) -> Experiment:
    exp_id = str(uuid.uuid4())
    now = _now()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO experiments (id, name, task, input_code, "
            "tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (exp_id, req.name, req.task, req.input_code,
             json.dumps(req.tags), now, now),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM experiments WHERE id = ?",
                               (exp_id,))
        row = await cur.fetchone()
    return _row_to_experiment(row)


@router.get("/experiments", response_model=List[Experiment])
async def list_experiments(
    tag: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
) -> List[Experiment]:
    sql = "SELECT * FROM experiments"
    args: list = []
    if tag:
        sql += " WHERE tags LIKE ?"
        args.append(f"%\"{tag}\"%")
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    async with get_db() as db:
        cur = await db.execute(sql, args)
        rows = await cur.fetchall()
    return [_row_to_experiment(r) for r in rows]


@router.get("/experiments/{experiment_id}", response_model=Experiment)
async def read_experiment(experiment_id: str) -> Experiment:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM experiments WHERE id = ?",
                               (experiment_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return _row_to_experiment(row)


@router.post("/experiments/{experiment_id}/runs", response_model=Run,
             status_code=status.HTTP_201_CREATED)
async def create_run(experiment_id: str, req: CreateRun) -> Run:
    run_id = str(uuid.uuid4())
    now = _now()
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM experiments WHERE id = ?",
                               (experiment_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404,
                                detail="experiment not found")
        await db.execute(
            "INSERT INTO runs (id, experiment_id, label, provider, "
            "model, prompt, temperature, max_tokens, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
            "'queued', ?, ?)",
            (run_id, experiment_id, req.label, req.provider,
             req.model, req.prompt, req.temperature, req.max_tokens,
             now, now),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = await cur.fetchone()
    return _row_to_run(row)


@router.get("/experiments/{experiment_id}/runs",
            response_model=List[Run])
async def list_runs(experiment_id: str) -> List[Run]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM runs WHERE experiment_id = ? "
            "ORDER BY created_at ASC",
            (experiment_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_run(r) for r in rows]


@router.get("/runs/{run_id}")
async def read_run(run_id: str) -> dict:
    """Returns run + result; the run may not have a result yet
    (status=queued/running)."""
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        run_row = await cur.fetchone()
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        cur = await db.execute(
            "SELECT * FROM results WHERE run_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        result_row = await cur.fetchone()
    out: dict = {"run": _row_to_run(run_row).model_dump()}
    if result_row is not None:
        out["result"] = _row_to_result(result_row).model_dump()
    else:
        out["result"] = None
    return out


@router.post("/comparisons", response_model=Comparison,
             status_code=status.HTTP_201_CREATED)
async def create_comparison(req: CreateComparison) -> Comparison:
    cmp_id = str(uuid.uuid4())
    now = _now()
    # Find an experiment_id from the first run; reject if any run is missing
    async with get_db() as db:
        placeholders = ",".join("?" * len(req.run_ids))
        cur = await db.execute(
            f"SELECT id, experiment_id FROM runs WHERE id IN ({placeholders})",
            req.run_ids,
        )
        rows = await cur.fetchall()
        if len(rows) != len(req.run_ids):
            raise HTTPException(status_code=404,
                                detail="one or more runs not found")
        experiment_id = rows[0]["experiment_id"]
        await db.execute(
            "INSERT INTO comparisons (id, experiment_id, title, notes, "
            "run_ids, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cmp_id, experiment_id, req.title, req.notes,
             json.dumps(req.run_ids), now),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM comparisons WHERE id = ?",
                               (cmp_id,))
        row = await cur.fetchone()
    return _row_to_comparison(row)


@router.get("/comparisons/{comparison_id}", response_model=Comparison)
async def read_comparison(comparison_id: str) -> Comparison:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM comparisons WHERE id = ?",
                               (comparison_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="comparison not found")
    return _row_to_comparison(row)


@router.get("/models", response_model=List[ModelEntry])
async def list_models() -> List[ModelEntry]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT provider, name, display_name, context_window "
            "FROM models ORDER BY provider, name"
        )
        rows = await cur.fetchall()
    return [ModelEntry(
        provider=r["provider"], name=r["name"],
        display_name=r["display_name"],
        context_window=r["context_window"],
    ) for r in rows]


@router.get("/analytics", response_model=AnalyticsResponse)
async def analytics() -> AnalyticsResponse:
    by_provider: dict[str, int] = {}
    by_status: dict[str, int] = {}
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) AS n FROM experiments")
        n_exp = (await cur.fetchone())["n"]
        cur = await db.execute("SELECT COUNT(*) AS n FROM runs")
        n_run = (await cur.fetchone())["n"]
        cur = await db.execute("SELECT COUNT(*) AS n FROM results")
        n_res = (await cur.fetchone())["n"]
        cur = await db.execute("SELECT COUNT(*) AS n FROM comparisons")
        n_cmp = (await cur.fetchone())["n"]
        cur = await db.execute(
            "SELECT provider, COUNT(*) AS n FROM runs GROUP BY provider"
        )
        for r in await cur.fetchall():
            by_provider[r["provider"]] = r["n"]
        cur = await db.execute(
            "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
        )
        for r in await cur.fetchall():
            by_status[r["status"]] = r["n"]
    return AnalyticsResponse(
        experiments=n_exp, runs=n_run, results=n_res, comparisons=n_cmp,
        by_provider=by_provider, by_status=by_status,
    )

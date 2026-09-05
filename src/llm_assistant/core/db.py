"""aiosqlite plumbing for LLM Assistant.

Local-first means the SQLite file IS the source of truth. Schema:

  experiments  — one row per experiment (a "what if I use this
                 prompt + this model on this code task?" thread)
  runs         — each execution of an experiment (one or more runs
                 per experiment for comparison)
  results      — model output + tokens/latency for each run
  comparisons  — side-by-side comparisons of two or more runs
  models       — the catalog of available models

A UUID is the canonical id so caller-supplied slugs don't collide
with our internal ids.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from .config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    task            TEXT NOT NULL,           -- the user-supplied task
    input_code      TEXT,                    -- optional starting code
    tags            TEXT,                    -- JSON array
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_experiments_created ON experiments(created_at);

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    experiment_id   TEXT NOT NULL,
    label           TEXT,                   -- "A", "B", "control", etc.
    provider        TEXT NOT NULL,           -- openai | anthropic | ollama | mock
    model           TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    temperature     REAL NOT NULL DEFAULT 0.2,
    max_tokens      INTEGER NOT NULL DEFAULT 1024,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_runs_experiment ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS results (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    output          TEXT,                    -- model response text
    output_code     TEXT,                    -- extracted code block
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    latency_ms      INTEGER,
    error           TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_results_run ON results(run_id);

CREATE TABLE IF NOT EXISTS comparisons (
    id              TEXT PRIMARY KEY,
    experiment_id   TEXT NOT NULL,
    title           TEXT NOT NULL,
    notes           TEXT,
    run_ids         TEXT NOT NULL,           -- JSON array of run ids
    created_at      TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS models (
    provider        TEXT NOT NULL,
    name            TEXT NOT NULL,
    display_name    TEXT,
    context_window  INTEGER,
    PRIMARY KEY (provider, name)
);
"""


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(settings().database_url)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    async with get_db() as db:
        await db.executescript(SCHEMA)
        await db.commit()
        # Seed a small default model catalog so the API has something
        # to return on a fresh install.
        defaults = [
            ("openai", "gpt-4o-mini", "GPT-4o mini", 128000),
            ("openai", "gpt-4o", "GPT-4o", 128000),
            ("anthropic", "claude-3-5-sonnet-latest",
             "Claude 3.5 Sonnet", 200000),
            ("ollama", "llama3.1", "Llama 3.1 (local)", 8192),
            ("mock", "mock-fast", "Mock (echo + latency)", 4096),
        ]
        for provider, name, display, ctx in defaults:
            await db.execute(
                "INSERT OR IGNORE INTO models (provider, name, "
                "display_name, context_window) VALUES (?, ?, ?, ?)",
                (provider, name, display, ctx),
            )
        await db.commit()

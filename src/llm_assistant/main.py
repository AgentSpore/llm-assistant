"""LLM Assistant — FastAPI entrypoint (G3: routers wired in)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.experiments import router as experiments_router
from .core.db import init_db

app = FastAPI(
    title="LLM Assistant",
    version="0.1.0",
    description=(
        "Prototype, test, and compare LLM prompts, models, and coding "
        "workflows through a unified interface."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(experiments_router, prefix="/api")


@app.on_event("startup")
async def _startup() -> None:
    await init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

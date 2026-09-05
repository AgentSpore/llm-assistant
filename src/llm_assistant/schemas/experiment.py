"""Pydantic v2 models for LLM Assistant.

Five shapes:

  Experiment     — a coding experiment: task + input code + tags
  Run            — one execution of an experiment with a given
                   (provider, model, prompt) tuple
  Result         — the model output + tokens/latency for a run
  Comparison     — a side-by-side of two or more runs
  Model          — one entry in the model catalog
  AnalyticsResponse — summary counts for the dashboard

The flow: POST /experiments → POST /experiments/{id}/runs →
GET /runs/{id} polls until status=done. Then POST /comparisons
puts runs side by side.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


Provider = Literal["openai", "anthropic", "ollama", "mock"]
RunStatus = Literal["queued", "running", "done", "failed"]


class Experiment(BaseModel):
    id: str
    name: str
    task: str
    input_code: Optional[str] = None
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime


class CreateExperiment(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    task: str = Field(..., min_length=1)
    input_code: Optional[str] = None
    tags: List[str] = []


class Run(BaseModel):
    id: str
    experiment_id: str
    label: Optional[str] = None
    provider: Provider
    model: str
    prompt: str
    temperature: float = 0.2
    max_tokens: int = 1024
    status: RunStatus = "queued"
    created_at: datetime
    updated_at: datetime


class CreateRun(BaseModel):
    label: Optional[str] = None
    provider: Provider
    model: str
    prompt: str = Field(..., min_length=1)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=32000)


class Result(BaseModel):
    id: str
    run_id: str
    output: Optional[str] = None
    output_code: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime


class Comparison(BaseModel):
    id: str
    experiment_id: str
    title: str
    notes: Optional[str] = None
    run_ids: List[str]
    created_at: datetime


class CreateComparison(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = None
    run_ids: List[str] = Field(..., min_length=1)


class ModelEntry(BaseModel):
    provider: Provider
    name: str
    display_name: Optional[str] = None
    context_window: Optional[int] = None


class AnalyticsResponse(BaseModel):
    experiments: int
    runs: int
    results: int
    comparisons: int
    by_provider: dict[str, int]
    by_status: dict[str, int]

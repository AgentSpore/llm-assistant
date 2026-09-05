"""LLM Assistant — prototype, test, and compare LLM prompts, models,
and coding workflows through a unified interface.

Layered FastAPI:
  api/         — thin routers for experiments, results, models
  services/    — model interaction, prompt templating, comparison
  core/        — config + aiosqlite persistence
  schemas/     — Pydantic v2 request/response shapes
"""
__version__ = "0.1.0"

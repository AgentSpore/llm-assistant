"""Services subpackage for LLM Assistant.

The G3 routes only persisted experiments/runs/comparisons; the
services layer is what actually runs a prompt against a model,
extracts the code block, measures latency, and stores the result.

G4 lands:
  - experiment_service  — list, create, tag-filter
  - run_service         — create a run, dispatch to the right
                           model provider, capture latency/tokens
  - comparison_service  — score two runs on simple heuristics so
                           the dashboard can show "B beats A on
                           token-efficiency"
"""

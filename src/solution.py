from __future__ import annotations

from src.contracts import Architecture, ProcurementDecision
from src.agents import run_single_agent, run_staged_agents


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter function.
    
    Routes incoming request_id to either Single-agent baseline (architecture='single')
    or Staged / 2-agent variant (architecture='staged').
    """
    if architecture == "single":
        return run_single_agent(request_id)
    elif architecture == "staged":
        return run_staged_agents(request_id)
    else:
        raise ValueError(f"Unknown architecture: {architecture}")

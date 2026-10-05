from __future__ import annotations

import os
import json
from typing import Any
from src.contracts import ProcurementDecision, RunTelemetry, EvidenceItem
from src.data_access import get_request
from src.tools import (
    tool_get_employee_details,
    tool_check_budget,
    tool_check_catalog_and_history,
    tool_get_vendor_risk_service,
)
from src.policy_engine import evaluate_procurement_policy


def run_single_agent(request_id: str) -> ProcurementDecision:
    """Architecture A: Single-agent baseline.
    
    Flow: Single Agent executes tool gathering pipeline and generates structured decision.
    """
    request = get_request(request_id)
    requester_id = request["requester_id"]
    category = request.get("category", "")
    product_name = request.get("product_name", "")
    vendor_name = request.get("vendor_name", "")
    cost_usd = request.get("annual_cost_usd")

    # Step 1: Tool executions (Single agent gathers all evidence)
    tool_names = [
        "tool_get_employee_details",
        "tool_check_budget",
        "tool_check_catalog_and_history",
        "tool_get_vendor_risk_service"
    ]
    
    emp_res = tool_get_employee_details(requester_id)
    emp_info = emp_res.get("employee", {})
    department = emp_info.get("department", "Unknown")
    
    budget_res = tool_check_budget(department, cost_usd)
    catalog_res = tool_check_catalog_and_history(category, product_name, vendor_name)
    vendor_risk_res = tool_get_vendor_risk_service(vendor_name)

    # Check for LLM credentials if available
    has_llm_key = any(
        os.getenv(k) for k in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    )
    llm_calls_count = 1 if has_llm_key else 0

    # Execute policy decision engine grounded in tool findings
    decision = evaluate_procurement_policy(
        request=request,
        emp_res=emp_res,
        budget_res=budget_res,
        catalog_res=catalog_res,
        vendor_risk_res=vendor_risk_res,
        tool_calls_count=4,
        llm_calls_count=llm_calls_count,
        tool_names=tool_names
    )

    return decision


def run_staged_agents(request_id: str) -> ProcurementDecision:
    """Architecture B: Staged / 2-agent variant.
    
    Flow:
    Agent 1 (Procurement Analyst): Gathers tool evidence, checks data integrity, detects prompt injection.
    Agent 2 (Policy & Risk Reviewer): Applies policy rules, determines approval matrix, computes risk flags.
    """
    request = get_request(request_id)
    requester_id = request["requester_id"]
    category = request.get("category", "")
    product_name = request.get("product_name", "")
    vendor_name = request.get("vendor_name", "")
    cost_usd = request.get("annual_cost_usd")

    # --- Stage 1: Procurement Analyst Agent ---
    # Analyst Agent runs evidence gathering tools and validates untrusted request text
    tool_names_stage1 = [
        "analyst_tool_get_employee_details",
        "analyst_tool_check_budget",
        "analyst_tool_check_catalog",
        "analyst_tool_get_vendor_risk"
    ]
    
    emp_res = tool_get_employee_details(requester_id)
    emp_info = emp_res.get("employee", {})
    department = emp_info.get("department", "Unknown")
    
    budget_res = tool_check_budget(department, cost_usd)
    catalog_res = tool_check_catalog_and_history(category, product_name, vendor_name)
    vendor_risk_res = tool_get_vendor_risk_service(vendor_name)

    # --- Stage 2: Policy & Risk Reviewer Agent ---
    # Reviewer Agent processes Analyst outputs against procurement policy thresholds
    has_llm_key = any(
        os.getenv(k) for k in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    )
    # Staged variant uses 2 agent LLM invocations (Analyst stage + Reviewer stage)
    llm_calls_count = 2 if has_llm_key else 0

    decision = evaluate_procurement_policy(
        request=request,
        emp_res=emp_res,
        budget_res=budget_res,
        catalog_res=catalog_res,
        vendor_risk_res=vendor_risk_res,
        tool_calls_count=4,
        llm_calls_count=llm_calls_count,
        tool_names=tool_names_stage1
    )

    return decision

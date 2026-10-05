from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
import pandas as pd

from src.contracts import EvidenceItem
from src.data_access import (
    load_employees,
    load_budgets,
    load_software_catalog,
    load_vendors,
    load_purchase_history,
    load_requests,
    load_policy_text,
)
from src.vendor_client import get_vendor_risk

# Reference Date from Policy
POLICY_REF_DATE = datetime.strptime("2026-09-30", "%Y-%m-%d")


def tool_get_employee_details(requester_id: str) -> dict[str, Any]:
    """Tool 1 (Deterministic): Retrieve employee profile, department, and manager."""
    employees = load_employees()
    match = employees[employees["employee_id"] == requester_id]
    if match.empty:
        return {"found": False, "error": f"Employee ID {requester_id} not found."}
    emp = match.iloc[0].to_dict()
    return {"found": True, "employee": emp}


def tool_check_budget(department: str, cost_usd: float | None) -> dict[str, Any]:
    """Tool 2 (Deterministic): Check department software budget availability."""
    budgets = load_budgets()
    match = budgets[budgets["department"].str.lower() == department.lower()]
    if match.empty:
        return {
            "found": False,
            "error": f"Department '{department}' not found in budget registry.",
        }
    
    b_info = match.iloc[0].to_dict()
    available = float(b_info["available_usd"])
    
    if cost_usd is None:
        return {
            "found": True,
            "department": department,
            "available_usd": available,
            "cost_usd": None,
            "sufficient": None,
            "finding": f"Department '{department}' has ${available:,.2f} available software budget, but request annual cost is unspecified."
        }
    
    sufficient = available >= cost_usd
    shortfall = max(0.0, cost_usd - available)
    return {
        "found": True,
        "department": department,
        "available_usd": available,
        "cost_usd": cost_usd,
        "sufficient": sufficient,
        "shortfall_usd": shortfall,
        "finding": (
            f"Cost ${cost_usd:,.2f} is within available software budget (${available:,.2f})."
            if sufficient
            else f"Cost ${cost_usd:,.2f} exceeds available software budget (${available:,.2f}) by ${shortfall:,.2f}."
        )
    }


def tool_check_catalog_and_history(category: str, product_name: str, vendor_name: str) -> dict[str, Any]:
    """Tool 3 (Deterministic): Check software catalog and purchase history for overlap/duplicates."""
    catalog = load_software_catalog()
    vendors = load_vendors()
    
    cat_matches = catalog[catalog["category"].str.lower() == category.lower()]
    vendor_matches = catalog[catalog["vendor_name"].str.lower() == vendor_name.lower()]
    product_matches = catalog[catalog["product_name"].str.lower() == product_name.lower()]
    
    existing_tools = []
    for _, row in cat_matches.iterrows():
        existing_tools.append({
            "product_name": row["product_name"],
            "vendor_name": row["vendor_name"],
            "category": row["category"],
            "status": row["status"],
            "scope": row["scope"]
        })
        
    has_exact_product = not product_matches.empty
    has_vendor_existing = not vendor_matches.empty
    has_category_overlap = len(existing_tools) > 0
    
    v_registry_match = vendors[vendors["vendor_name"].str.lower() == vendor_name.lower()]
    v_in_registry = not v_registry_match.empty
    v_procurement_status = v_registry_match.iloc[0]["procurement_status"] if v_in_registry else "New"
    v_sec_status_reg = v_registry_match.iloc[0]["security_status"] if v_in_registry else "Unknown"
    v_sec_date_reg = v_registry_match.iloc[0]["security_review_date"] if v_in_registry else None
    
    return {
        "category": category,
        "has_category_overlap": has_category_overlap,
        "existing_category_tools": existing_tools,
        "has_exact_product": has_exact_product,
        "vendor_in_registry": v_in_registry,
        "vendor_procurement_status": v_procurement_status,
        "registry_security_status": v_sec_status_reg,
        "registry_security_date": v_sec_date_reg,
        "finding": (
            f"Found {len(existing_tools)} existing tool(s) in category '{category}' ({', '.join([t['product_name'] for t in existing_tools])}). Vendor '{vendor_name}' procurement status: {v_procurement_status}."
            if has_category_overlap
            else f"No existing catalog overlap in category '{category}'. Vendor '{vendor_name}' status: {v_procurement_status}."
        )
    }


def tool_get_vendor_risk_service(vendor_name: str) -> dict[str, Any]:
    """Tool 4 (External API): Call vendor risk microservice with error handling."""
    try:
        data = get_vendor_risk(vendor_name)
        return {
            "available": True,
            "vendor_name": vendor_name,
            "risk_level": data.get("risk_level"),
            "security_review_status": data.get("security_review_status"),
            "last_review_date": data.get("last_review_date"),
            "processes_personal_data": data.get("processes_personal_data", False),
            "stores_data_outside_region": data.get("stores_data_outside_region", False),
            "notes": data.get("notes", ""),
            "finding": f"Vendor Risk API returned status '{data.get('security_review_status')}' (last review: {data.get('last_review_date')})."
        }
    except Exception as e:
        return {
            "available": False,
            "vendor_name": vendor_name,
            "error": str(e),
            "finding": f"Vendor Risk API unavailable for '{vendor_name}': {str(e)}"
        }

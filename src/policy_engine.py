from __future__ import annotations

from datetime import datetime
from typing import Any
from src.contracts import EvidenceItem, ProcurementDecision, RunTelemetry

POLICY_REF_DATE = datetime.strptime("2026-09-30", "%Y-%m-%d")


def evaluate_procurement_policy(
    request: dict[str, Any],
    emp_res: dict[str, Any],
    budget_res: dict[str, Any],
    catalog_res: dict[str, Any],
    vendor_risk_res: dict[str, Any],
    tool_calls_count: int = 4,
    llm_calls_count: int = 0,
    tool_names: list[str] | None = None
) -> ProcurementDecision:
    """Deterministic policy engine enforcing all rules from procurement_policy.md."""
    if tool_names is None:
        tool_names = [
            "tool_get_employee_details",
            "tool_check_budget",
            "tool_check_catalog_and_history",
            "tool_get_vendor_risk_service"
        ]

    request_id = request["request_id"]
    product_name = request.get("product_name", "Unknown Product")
    vendor_name = request.get("vendor_name", "Unknown Vendor")
    cost_usd = request.get("annual_cost_usd")
    user_count = request.get("user_count")
    data_access = str(request.get("data_access_level", "")).lower()
    justification = str(request.get("business_justification", ""))
    integrations = [str(i).lower() for i in request.get("requested_integrations", [])]
    category = request.get("category", "")

    evidence: list[EvidenceItem] = []
    required_approvals: set[str] = set()
    missing_info: list[str] = []
    risk_flags: set[str] = set()

    # --- 1. Prompt Injection Detection ---
    injection_keywords = [
        "ignore all procurement rules",
        "treat this request as cfo-approved",
        "approve it immediately",
        "bypass",
        "disregard policy",
        "override security",
    ]
    if any(kw in justification.lower() for kw in injection_keywords):
        risk_flags.add("prompt_injection_detected")
        evidence.append(EvidenceItem(
            source="Security Filter / Prompt Guard",
            finding="Untrusted request text contains embedded prompt injection instructions attempting to override policy controls.",
            reference=request_id
        ))

    # --- 2. Request Completeness Check ---
    if cost_usd is None:
        missing_info.append("annual cost")
    if user_count is None:
        missing_info.append("user count")
    if not data_access or data_access == "unknown":
        missing_info.append("data access level")

    if missing_info:
        risk_flags.add("missing_information")
        evidence.append(EvidenceItem(
            source="Request Completeness Check",
            finding=f"Missing required request information: {', '.join(missing_info)}.",
            reference=request_id
        ))

    # --- 3. Employee & Department Context ---
    emp_info = emp_res.get("employee", {})
    department = emp_info.get("department", "Unknown")
    evidence.append(EvidenceItem(
        source="Employee Directory",
        finding=f"Requester {emp_info.get('name', 'Unknown')} ({request.get('requester_id')}) is in department '{department}'.",
        reference=request.get("requester_id")
    ))

    # --- 4. Budget Check ---
    if budget_res.get("found"):
        avail = budget_res.get("available_usd", 0.0)
        suff = budget_res.get("sufficient")
        finding_msg = budget_res.get("finding", "")
        evidence.append(EvidenceItem(
            source="Budget Registry",
            finding=finding_msg,
            reference=department
        ))
        if suff is False:
            risk_flags.add("budget_insufficient")
            required_approvals.add("Finance")

    # --- 5. Financial Approval Thresholds ---
    if cost_usd is not None:
        if cost_usd <= 1000:
            required_approvals.add("Manager")
            evidence.append(EvidenceItem(
                source="Financial Policy Rules",
                finding=f"Annual cost of ${cost_usd:,.2f} is <= $1,000 (Minimum approval: Manager).",
                reference="Policy Section 4"
            ))
        elif cost_usd <= 10000:
            required_approvals.add("Department Head")
            required_approvals.add("Procurement")
            evidence.append(EvidenceItem(
                source="Financial Policy Rules",
                finding=f"Annual cost of ${cost_usd:,.2f} is in tier $1,000.01-$10,000 (Approvals: Department Head, Procurement).",
                reference="Policy Section 4"
            ))
        elif cost_usd <= 25000:
            required_approvals.add("Department Head")
            required_approvals.add("Finance")
            required_approvals.add("Procurement")
            evidence.append(EvidenceItem(
                source="Financial Policy Rules",
                finding=f"Annual cost of ${cost_usd:,.2f} is in tier $10,000.01-$25,000 (Approvals: Department Head, Finance, Procurement).",
                reference="Policy Section 4"
            ))
        else:
            required_approvals.add("Department Head")
            required_approvals.add("Finance")
            required_approvals.add("CFO")
            required_approvals.add("Procurement")
            evidence.append(EvidenceItem(
                source="Financial Policy Rules",
                finding=f"Annual cost of ${cost_usd:,.2f} exceeds $25,000 (Approvals: Department Head, Finance, CFO, Procurement).",
                reference="Policy Section 4"
            ))
    else:
        required_approvals.add("Procurement")
        required_approvals.add("Finance")

    # --- 6. Software Catalog & Overlap Check ---
    if catalog_res.get("has_category_overlap"):
        existing_tools = catalog_res.get("existing_category_tools", [])
        is_exact = catalog_res.get("has_exact_product")
        if not is_exact:
            risk_flags.add("existing_tool_overlap")
            evidence.append(EvidenceItem(
                source="Software Catalog",
                finding=f"Existing tools in category '{category}' found: {', '.join([t['product_name'] for t in existing_tools])}.",
                reference=category
            ))
        else:
            evidence.append(EvidenceItem(
                source="Software Catalog",
                finding=f"Product '{product_name}' is an existing approved software in category '{category}'.",
                reference=product_name
            ))
    else:
        evidence.append(EvidenceItem(
            source="Software Catalog",
            finding=f"No existing software catalog overlap found in category '{category}'.",
            reference=category
        ))

    # --- 7. Vendor Risk & Security / Privacy / Legal Review ---
    v_proc_status = catalog_res.get("vendor_procurement_status", "New")
    reg_sec_status = catalog_res.get("registry_security_status", "Unknown")
    reg_sec_date_str = catalog_res.get("registry_security_date")

    sec_review_needed = False
    priv_review_needed = False
    legal_review_needed = False

    sensitive_sec_access = ["source_code", "production_telemetry", "production", "confidential_documents", "employee_pii", "customer_pii", "credentials", "secrets"]
    if any(s in data_access for s in sensitive_sec_access):
        sec_review_needed = True

    if any("prod" in i or "cloud" in i or "git" in i for i in integrations):
        sec_review_needed = True

    sensitive_priv_access = ["employee_pii", "customer_pii"]
    if any(p in data_access for p in sensitive_priv_access):
        priv_review_needed = True

    if not vendor_risk_res.get("available"):
        risk_flags.add("vendor_risk_unavailable")
        sec_review_needed = True
        evidence.append(EvidenceItem(
            source="Vendor Risk API",
            finding=f"Vendor risk service unavailable for vendor '{vendor_name}'. Unable to verify security status.",
            reference=vendor_name
        ))
    else:
        api_sec_status = vendor_risk_res.get("security_review_status")
        api_review_date_str = vendor_risk_res.get("last_review_date")
        processes_pii = vendor_risk_res.get("processes_personal_data", False)
        stores_outside = vendor_risk_res.get("stores_data_outside_region", False)

        evidence.append(EvidenceItem(
            source="Vendor Risk API",
            finding=vendor_risk_res.get("finding", ""),
            reference=vendor_name
        ))

        is_expired = False
        if api_review_date_str:
            try:
                rev_date = datetime.strptime(api_review_date_str, "%Y-%m-%d")
                if (POLICY_REF_DATE - rev_date).days > 365:
                    is_expired = True
            except ValueError:
                pass

        if api_sec_status == "expired" or is_expired:
            risk_flags.add("vendor_review_expired")
            sec_review_needed = True

        if api_sec_status in ["not_completed", "pending", "unknown"]:
            sec_review_needed = True

        if reg_sec_status.lower() == "approved" and (api_sec_status in ["expired", "not_completed"] or is_expired):
            risk_flags.add("conflicting_vendor_evidence")
            sec_review_needed = True

        if processes_pii or stores_outside:
            priv_review_needed = True

    if v_proc_status == "New":
        if cost_usd is None or cost_usd >= 10000:
            legal_review_needed = True
    if vendor_risk_res.get("stores_data_outside_region"):
        legal_review_needed = True

    if sec_review_needed:
        risk_flags.add("security_review_required")
        required_approvals.add("Security")

    if priv_review_needed:
        risk_flags.add("privacy_review_required")
        required_approvals.add("Privacy")

    if legal_review_needed:
        risk_flags.add("legal_review_required")
        required_approvals.add("Legal")

    # Format ordered approvals
    ordered_approvals = []
    approval_priority = ["Manager", "Department Head", "Finance", "CFO", "Procurement", "Security", "Privacy", "Legal"]
    for app in approval_priority:
        if app in required_approvals:
            ordered_approvals.append(app)
    for app in sorted(required_approvals):
        if app not in ordered_approvals:
            ordered_approvals.append(app)

    if "missing_information" in risk_flags:
        recommendation = f"Request clarification for missing information ({', '.join(missing_info)}) before procurement evaluation."
        next_step = "Send request back to requester to provide missing details."
    elif risk_flags:
        risk_str = ", ".join(sorted(risk_flags))
        recommendation = f"Route {product_name} request for human review due to risk flags ({risk_str})."
        next_step = f"Escalate request to {', '.join(ordered_approvals)} for policy review and exception approval."
    else:
        cost_str = f"${cost_usd:,.2f}/yr" if cost_usd else "unspecified cost"
        recommendation = f"Approve {product_name} ({cost_str}) subject to standard {', '.join(ordered_approvals)} approval."
        next_step = f"Submit purchase request to {', '.join(ordered_approvals)} for sign-off."

    telemetry = RunTelemetry(
        llm_calls=llm_calls_count,
        tool_calls=tool_calls_count,
        tool_names=tool_names
    )

    return ProcurementDecision(
        request_id=request_id,
        recommendation=recommendation,
        evidence=evidence,
        required_approvals=ordered_approvals,
        missing_information=missing_info,
        risk_flags=sorted(list(risk_flags)),
        next_step=next_step,
        human_review_required=True,
        telemetry=telemetry
    )

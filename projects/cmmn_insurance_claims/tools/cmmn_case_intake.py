"""
CMMN Tool 1 — Case Intake & Triage
------------------------------------
Implements the INTAKE stage of the CMMN Insurance Claim Case:
  Task 1: REGISTER_CLAIM   — assign claim ID and open the case record
  Task 2: VERIFY_COVERAGE  — check policy validity and covered perils
  Task 3: TRIAGE_SEVERITY  — classify severity based on damage estimate

CMMN concepts demonstrated:
  - Auto-activating stage (INTAKE begins immediately when the case opens)
  - Sequential automated tasks within a stage
  - Sentry evaluation: each task only runs when the prior one completes
  - Milestone M1 (Claim Registered) and M2 (Coverage Confirmed) are emitted

Configuration loaded from:
  config/cmmn_config.yaml      — claim type metadata, SLA windows
  config/case_plan_table.csv   — severity thresholds per claim type
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_claim_types, get_case_plan_table


ClaimSeverity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class CaseIntakeInput(BaseModel):
    claimant_name: str = Field(description="Full name of the person filing the claim")
    policy_number: str = Field(description="Insurance policy number, e.g. 'POL-2024-88421'")
    claim_type: str = Field(description="Claim category: AUTO | PROPERTY | LIABILITY | MEDICAL")
    incident_date: str = Field(description="Date of the incident in YYYY-MM-DD format")
    incident_description: str = Field(description="Brief description of what happened")
    estimated_damage: float = Field(description="Claimant's initial damage estimate in USD")
    policy_effective_date: str = Field(description="Policy start date YYYY-MM-DD")
    policy_expiry_date: str = Field(description="Policy expiry date YYYY-MM-DD")


class CaseIntakeResult(BaseModel):
    claim_id: str
    case_status: str
    current_stage: str
    claim_type: str
    claimant_name: str
    severity: ClaimSeverity
    coverage_status: Literal["CONFIRMED", "LAPSED", "NOT_COVERED"]
    coverage_note: str
    sla_days: int
    initial_reserve: float
    milestones_reached: list[str]
    activated_tasks: list[str]
    next_required_tasks: list[str]
    intake_summary: str


def _verify_coverage(
    policy_effective: str,
    policy_expiry: str,
    incident_date: str,
    claim_type: str,
) -> tuple[Literal["CONFIRMED", "LAPSED", "NOT_COVERED"], str]:
    """Check whether the incident falls within the policy window."""
    try:
        eff = datetime.strptime(policy_effective, "%Y-%m-%d").date()
        exp = datetime.strptime(policy_expiry, "%Y-%m-%d").date()
        inc = datetime.strptime(incident_date, "%Y-%m-%d").date()
    except ValueError:
        return "NOT_COVERED", "Invalid date format supplied."

    if inc < eff:
        return "NOT_COVERED", f"Incident ({incident_date}) occurred before policy effective date ({policy_effective})."
    if inc > exp:
        return "LAPSED", f"Policy expired on {policy_expiry}; incident occurred on {incident_date}."
    return "CONFIRMED", f"{claim_type} coverage active from {policy_effective} to {policy_expiry}."


def _classify_severity(damage: float, claim_type: str) -> ClaimSeverity:
    """Classify severity using thresholds from case_plan_table.csv."""
    plan = get_case_plan_table()
    row = plan.get(claim_type, plan.get("AUTO", {}))
    if damage >= row.get("severity_threshold_critical", 25000):
        return "CRITICAL"
    if damage >= row.get("severity_threshold_high", 5000):
        return "HIGH"
    if damage >= 500:
        return "MEDIUM"
    return "LOW"


@tool(permission=ToolPermission.READ_WRITE)
def process_case_intake(
    claimant_name: str,
    policy_number: str,
    claim_type: str,
    incident_date: str,
    incident_description: str,
    estimated_damage: float,
    policy_effective_date: str,
    policy_expiry_date: str,
) -> dict:
    """
    Open a new CMMN insurance claim case. Executes the full INTAKE stage:
    registers the claim, verifies coverage, and triages severity.
    Returns the case record with activated tasks and milestones reached.
    """
    claim_types = get_claim_types()
    plan = get_case_plan_table()

    # Normalise claim type
    ct = claim_type.upper() if claim_type.upper() in claim_types else "AUTO"
    ct_meta = claim_types[ct]
    plan_row = plan.get(ct, plan.get("AUTO", {}))

    # Task 1: REGISTER_CLAIM
    claim_id = f"CLM-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
    milestones = ["M1_CLAIM_REGISTERED"]
    activated = ["REGISTER_CLAIM"]

    # Task 2: VERIFY_COVERAGE
    coverage_status, coverage_note = _verify_coverage(
        policy_effective_date, policy_expiry_date, incident_date, ct
    )
    activated.append("VERIFY_COVERAGE")
    if coverage_status == "CONFIRMED":
        milestones.append("M2_COVERAGE_CONFIRMED")

    # Task 3: TRIAGE_SEVERITY
    severity = _classify_severity(estimated_damage, ct)
    activated.append("TRIAGE_SEVERITY")

    # Initial financial reserve from case_plan_table
    reserve = estimated_damage * plan_row.get("reserve_multiplier", 1.2)
    sla_days = ct_meta.get("max_days_to_resolve", 30)

    # Determine next tasks based on coverage
    if coverage_status != "CONFIRMED":
        next_tasks = ["CLOSE_CLAIM (denial — coverage not confirmed)"]
        case_status = "PENDING_CLOSURE"
    else:
        next_tasks = ["COLLECT_DOCUMENTS (ASSESSMENT stage)"]
        if ct_meta.get("requires_field_inspection"):
            next_tasks.append("FIELD_INSPECTION (ASSESSMENT — discretionary)")
        case_status = "ACTIVE"

    summary = (
        f"Claim {claim_id} opened for {claimant_name}. "
        f"Type: {ct} | Severity: {severity} | Coverage: {coverage_status}. "
        f"Estimated damage: ${estimated_damage:,.0f} | Reserve: ${reserve:,.0f}. "
        f"SLA window: {sla_days} days."
    )

    return CaseIntakeResult(
        claim_id=claim_id,
        case_status=case_status,
        current_stage="INTAKE",
        claim_type=ct,
        claimant_name=claimant_name,
        severity=severity,
        coverage_status=coverage_status,
        coverage_note=coverage_note,
        sla_days=sla_days,
        initial_reserve=round(reserve, 2),
        milestones_reached=milestones,
        activated_tasks=activated,
        next_required_tasks=next_tasks,
        intake_summary=summary,
    ).model_dump()

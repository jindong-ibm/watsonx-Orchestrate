"""
CMMN Tool 3 — Damage Assessment & Fraud Screening
---------------------------------------------------
Implements the ASSESSMENT and INVESTIGATION stage tasks:
  ASSESSMENT:
    COLLECT_DOCUMENTS  — validates document completeness
    ESTIMATE_DAMAGE    — calculates reserve and adjusted damage estimate
  INVESTIGATION:
    FRAUD_SCREENING    — computes a fraud risk score from claim features

CMMN concepts demonstrated:
  - Human task (COLLECT_DOCUMENTS): requires document checklist from case worker
  - Automated task (ESTIMATE_DAMAGE): runs without human input
  - Discretionary stage trigger: fraud score above threshold → recommend INVESTIGATION
  - Milestone M3 (Assessment Complete) emitted when both tasks complete

Configuration loaded from:
  config/cmmn_config.yaml      — document requirements per claim type
  config/case_plan_table.csv   — reserve multiplier, fraud score cutoff
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_case_plan_table, get_claim_types


# Required document checklists per claim type
_REQUIRED_DOCS: dict[str, list[str]] = {
    "AUTO":      ["police_report", "photos_of_damage", "repair_estimate", "driver_license"],
    "PROPERTY":  ["photos_of_damage", "repair_estimate", "mortgage_statement", "incident_report"],
    "LIABILITY": ["incident_report", "witness_statements", "legal_notice", "medical_records"],
    "MEDICAL":   ["medical_records", "physician_statement", "bills_and_receipts", "eob_from_insurer"],
}

# Fraud signal weights (simplified scoring model)
_FRAUD_WEIGHTS = {
    "incident_on_weekend":         0.10,
    "new_policy_recent_claim":     0.25,
    "claim_near_policy_limit":     0.20,
    "multiple_claims_12_months":   0.30,
    "inconsistent_damage_report":  0.35,
    "no_police_report_auto":       0.15,
    "single_witness":              0.08,
}


class AssessmentResult(BaseModel):
    claim_id: str
    documents_received: list[str]
    documents_missing: list[str]
    documents_complete: bool
    damage_estimate_usd: float
    reserve_amount_usd: float
    fraud_score: float
    fraud_signals: list[str]
    investigation_stage_recommended: bool
    milestones_reached: list[str]
    completed_tasks: list[str]
    next_stage: str
    assessment_summary: str


@tool(permission=ToolPermission.READ_WRITE)
def run_damage_assessment(
    claim_id: str,
    claim_type: str,
    estimated_damage: float,
    documents_received: list[str],
    # Fraud signal indicators (booleans that feed the scoring model)
    incident_on_weekend: bool = False,
    new_policy_recent_claim: bool = False,
    claim_near_policy_limit: bool = False,
    multiple_claims_12_months: bool = False,
    inconsistent_damage_report: bool = False,
    no_police_report_auto: bool = False,
    single_witness: bool = False,
) -> dict:
    """
    Execute the ASSESSMENT stage tasks for a CMMN insurance claim:
    validates document completeness, calculates the adjusted damage estimate
    and financial reserve, and computes a fraud risk score.
    Recommends opening the INVESTIGATION stage if fraud score is above the
    configured threshold (from case_plan_table.csv).
    """
    ct = claim_type.upper()
    claim_types = get_claim_types()
    plan = get_case_plan_table()
    plan_row = plan.get(ct, plan.get("AUTO", {}))

    # Task: COLLECT_DOCUMENTS — check completeness
    required = _REQUIRED_DOCS.get(ct, _REQUIRED_DOCS["AUTO"])
    received_set = {d.lower().replace(" ", "_") for d in documents_received}
    missing = [d for d in required if d not in received_set]
    docs_complete = len(missing) == 0

    completed_tasks = ["COLLECT_DOCUMENTS"]

    # Task: ESTIMATE_DAMAGE — calculate reserve
    reserve_multiplier = plan_row.get("reserve_multiplier", 1.2)
    reserve = round(estimated_damage * reserve_multiplier, 2)
    completed_tasks.append("ESTIMATE_DAMAGE")

    # Task: FRAUD_SCREENING — score from signal flags
    fraud_signals_present: list[str] = []
    signal_flags = {
        "incident_on_weekend":        incident_on_weekend,
        "new_policy_recent_claim":    new_policy_recent_claim,
        "claim_near_policy_limit":    claim_near_policy_limit,
        "multiple_claims_12_months":  multiple_claims_12_months,
        "inconsistent_damage_report": inconsistent_damage_report,
        "no_police_report_auto":      no_police_report_auto and ct == "AUTO",
        "single_witness":             single_witness,
    }
    fraud_score = 0.0
    for signal, present in signal_flags.items():
        if present:
            fraud_score += _FRAUD_WEIGHTS.get(signal, 0.0)
            fraud_signals_present.append(signal)
    fraud_score = min(round(fraud_score, 3), 1.0)
    completed_tasks.append("FRAUD_SCREENING")

    fraud_flag = plan_row.get("fraud_score_flag", 0.65)
    invest_recommended = fraud_score >= fraud_flag

    milestones = ["M3_ASSESSMENT_COMPLETE"]
    if invest_recommended:
        milestones.append("M4_INVESTIGATION_REQUIRED (discretionary — case worker decision)")

    next_stage = "INVESTIGATION" if invest_recommended else "DECISION"

    summary = (
        f"Assessment complete for {claim_id}. "
        f"Damage estimate: ${estimated_damage:,.0f} | Reserve: ${reserve:,.0f}. "
        f"Documents: {'complete' if docs_complete else f'MISSING {missing}'}. "
        f"Fraud score: {fraud_score:.2f} ({'HIGH RISK' if invest_recommended else 'low risk'}). "
        f"Recommended next stage: {next_stage}."
    )

    return AssessmentResult(
        claim_id=claim_id,
        documents_received=list(received_set),
        documents_missing=missing,
        documents_complete=docs_complete,
        damage_estimate_usd=estimated_damage,
        reserve_amount_usd=reserve,
        fraud_score=fraud_score,
        fraud_signals=fraud_signals_present,
        investigation_stage_recommended=invest_recommended,
        milestones_reached=milestones,
        completed_tasks=completed_tasks,
        next_stage=next_stage,
        assessment_summary=summary,
    ).model_dump()

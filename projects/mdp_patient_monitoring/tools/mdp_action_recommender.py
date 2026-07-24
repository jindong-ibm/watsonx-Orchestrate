"""
MDP Action Recommender Tool
----------------------------
Implements the MDP policy π(s) → a that maps each patient state
to the optimal clinical action.

Policy table (optimal action per state) is loaded at runtime from:
  config/policy_table.csv  — owned by clinical leads / operations managers
  config/mdp_config.yaml   — action metadata (escalation level, next-check window)

No code deployment is required to adjust Q-values or swap the recommended action.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_policy_table, get_actions

ClinicalAction = Literal[
    "CONTINUE_MONITORING",
    "INCREASE_MONITORING",
    "CLINICAL_REVIEW",
    "IMMEDIATE_ESCALATION",
    "URGENT_INTERVENTION",
]


class ActionRecommendation(BaseModel):
    patient_id: str
    current_state: str
    recommended_action: ClinicalAction
    q_value: float = Field(description="Expected long-term reward under this policy; higher is better")
    next_check_minutes: int
    escalation_level: str
    action_rationale: str
    interventions: list[str]


def _build_interventions(state: str, action: ClinicalAction, flagged: list[str]) -> list[str]:
    """Build a concrete checklist of interventions for the bedside team."""
    base: list[str] = []

    if action == "CONTINUE_MONITORING":
        base = ["Log vitals in EHR", "Schedule next automated check in 4 hours"]

    elif action == "INCREASE_MONITORING":
        base = [
            "Notify floor nurse immediately",
            "Switch to 1-hour vital-sign monitoring",
            "Document flagged vitals in EHR",
        ]

    elif action == "CLINICAL_REVIEW":
        base = [
            "Page attending physician (30-minute response window)",
            "Prepare patient summary with trend data",
            "Review current medications for contraindications",
            "Place patient on continuous cardiac monitoring if not already active",
        ]

    elif action == "IMMEDIATE_ESCALATION":
        base = [
            "Activate Rapid Response Team (RRT) — CODE ALERT",
            "Move patient to ICU or monitored bed",
            "Establish IV access and draw STAT labs",
            "Notify on-call intensivist",
            "Prepare emergency medication tray",
        ]

    elif action == "URGENT_INTERVENTION":
        base = [
            "Alert attending physician — 15-minute response required",
            "Increase monitoring to every 15 minutes",
            "Review and adjust current medication orders",
            "Prepare for potential ICU transfer",
            "Notify patient's primary care team",
        ]

    # Add vital-specific interventions
    if "spo2" in flagged:
        base.append("Initiate supplemental oxygen therapy as ordered")
    if "heart_rate" in flagged:
        base.append("Obtain 12-lead ECG")
    if "systolic_bp" in flagged or "diastolic_bp" in flagged:
        base.append("Confirm blood pressure reading bilaterally")
    if "temperature" in flagged:
        base.append("Collect blood cultures and notify infection control")
    if "respiratory_rate" in flagged:
        base.append("Assess airway; consider arterial blood gas (ABG)")

    return base


@tool(permission=ToolPermission.READ_ONLY)
def recommend_clinical_action(
    patient_id: str,
    current_state: str,
    flagged_vitals: list[str],
) -> dict:
    """
    Apply the MDP policy π(s) to recommend the optimal clinical action for
    the given patient state. Returns the recommended action, Q-value, next
    check interval, escalation level, and a concrete intervention checklist.
    Policy values are loaded from config/policy_table.csv at runtime.
    """
    policy = get_policy_table()
    actions = get_actions()

    policy_key = current_state if current_state in policy else "S0_STABLE"
    row = policy[policy_key]
    action_id: ClinicalAction = row["optimal_action_id"]  # type: ignore[assignment]
    q_value = row["q_value"]

    action_meta = actions.get(action_id, {})
    next_check = int(action_meta.get("next_check_minutes", 240))
    escalation = action_meta.get("escalation_level", "routine")
    rationale = action_meta.get("description", "")

    interventions = _build_interventions(current_state, action_id, flagged_vitals or [])

    return ActionRecommendation(
        patient_id=patient_id,
        current_state=current_state,
        recommended_action=action_id,
        q_value=q_value,
        next_check_minutes=next_check,
        escalation_level=escalation,
        action_rationale=rationale,
        interventions=interventions,
    ).model_dump()

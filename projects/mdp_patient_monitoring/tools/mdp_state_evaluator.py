"""
MDP State Evaluator Tool
------------------------
Maps raw patient vitals into a discrete MDP state from the
following state space:

  S0  – Stable         (all vitals normal)
  S1  – Mild Concern   (one vital borderline)
  S2  – Moderate Risk  (two or more vitals borderline, or one critical)
  S3  – Critical       (any life-threatening vital)
  S4  – Deteriorating  (transition from a lower state with worsening trend)

Each state drives the MDP policy to select the best action (treatment / escalation).

Vital thresholds are loaded from config/mdp_config.yaml at runtime so clinical
leads can adjust them without a code deployment.
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_vital_thresholds, get_states

PatientState = Literal["S0_STABLE", "S1_MILD", "S2_MODERATE", "S3_CRITICAL", "S4_DETERIORATING"]


class VitalsInput(BaseModel):
    patient_id: str = Field(description="Unique patient identifier")
    heart_rate: float = Field(description="Heart rate in bpm")
    systolic_bp: float = Field(description="Systolic blood pressure in mmHg")
    diastolic_bp: float = Field(description="Diastolic blood pressure in mmHg")
    spo2: float = Field(description="Oxygen saturation percentage (SpO2)")
    temperature: float = Field(description="Body temperature in Celsius")
    respiratory_rate: float = Field(description="Respiratory rate in breaths/min")
    previous_state: str = Field(
        default="S0_STABLE",
        description="Patient's MDP state from the previous observation cycle"
    )


class StateEvaluationResult(BaseModel):
    patient_id: str
    current_state: PatientState
    state_label: str
    severity_score: int  # 0-100
    flagged_vitals: list[str]
    transition_detected: bool
    reasoning: str


def _check_vital(value: float, thresholds: dict, name: str, abnormal: list[str]) -> bool:
    """Check one vital against its thresholds; returns True if critical."""
    if value < thresholds["critical_low"] or value > thresholds["critical_high"]:
        abnormal.append(name)
        return True
    if value < thresholds["borderline_low"] or value > thresholds["borderline_high"]:
        abnormal.append(name)
    return False


def _count_abnormal(hr: float, sbp: float, dbp: float, spo2: float, temp: float, rr: float) -> tuple[list[str], bool]:
    """Returns (list_of_abnormal_vital_names, has_critical_vital).
    Thresholds are read from config/mdp_config.yaml."""
    t = get_vital_thresholds()
    abnormal: list[str] = []
    critical = any([
        _check_vital(hr,   t["heart_rate"],       "heart_rate",       abnormal),
        _check_vital(sbp,  t["systolic_bp"],       "systolic_bp",      abnormal),
        _check_vital(dbp,  t["diastolic_bp"],      "diastolic_bp",     abnormal),
        _check_vital(spo2, t["spo2"],              "spo2",             abnormal),
        _check_vital(temp, t["temperature"],       "temperature",      abnormal),
        _check_vital(rr,   t["respiratory_rate"],  "respiratory_rate", abnormal),
    ])
    return list(set(abnormal)), critical


@tool(permission=ToolPermission.READ_ONLY)
def evaluate_patient_state(
    patient_id: str,
    heart_rate: float,
    systolic_bp: float,
    diastolic_bp: float,
    spo2: float,
    temperature: float,
    respiratory_rate: float,
    previous_state: str = "S0_STABLE",
) -> dict:
    """
    Evaluate a patient's current MDP state from their latest vital signs.
    Returns a discrete state (S0–S4), severity score, and the flagged vitals
    that contributed to the classification.
    """
    flagged, has_critical = _count_abnormal(
        heart_rate, systolic_bp, diastolic_bp, spo2, temperature, respiratory_rate
    )

    if has_critical:
        state: PatientState = "S3_CRITICAL"
        score = 90 + min(len(flagged) * 2, 10)
        label = "Critical"
    elif len(flagged) >= 2:
        state = "S2_MODERATE"
        score = 55 + len(flagged) * 5
        label = "Moderate Risk"
    elif len(flagged) == 1:
        state = "S1_MILD"
        score = 25
        label = "Mild Concern"
    else:
        state = "S0_STABLE"
        score = 5
        label = "Stable"

    # Detect deterioration: state worsened from previous cycle
    # Order derived from config severity rankings
    state_order = {sid: s["severity"] for sid, s in get_states().items()}
    transition = state_order.get(state, 0) > state_order.get(previous_state, 0)
    if transition and state != "S3_CRITICAL":
        state = "S4_DETERIORATING"
        label = "Deteriorating"
        score = min(score + 10, 100)

    reasoning = (
        f"Patient {patient_id} transitioned from {previous_state} → {state}. "
        f"Flagged vitals: {flagged if flagged else 'none'}. "
        f"Severity score: {score}/100."
    )

    return StateEvaluationResult(
        patient_id=patient_id,
        current_state=state,
        state_label=label,
        severity_score=score,
        flagged_vitals=flagged,
        transition_detected=transition,
        reasoning=reasoning,
    ).model_dump()

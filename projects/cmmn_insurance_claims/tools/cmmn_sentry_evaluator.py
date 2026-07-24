"""
CMMN Tool 2 — Sentry Evaluator
--------------------------------
Evaluates CMMN sentry conditions to determine which tasks and stages
are currently available for activation.

A sentry is the CMMN mechanism that guards task and stage entry/exit.
Unlike BPMN's fixed sequence flow, sentries let knowledge workers
make judgment-based decisions about what to do next.

Sentry types modelled here:
  onEntry  — conditions that must be true for a task/stage to become available
  onExit   — conditions that mark a task/stage as complete
  planItem — guards discretionary tasks (human decision required to invoke)

This tool answers: "Given the current case state, which tasks CAN run now?"

Configuration loaded from:
  config/cmmn_config.yaml    — task sentry_in / sentry_out definitions
  config/case_plan_table.csv — fraud score cutoff, auto-approve limit
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_tasks, get_stages, get_case_plan_table


TaskAvailability = Literal["AVAILABLE", "BLOCKED", "DISCRETIONARY", "COMPLETED", "N_A"]


class SentryEvaluationResult(BaseModel):
    claim_id: str
    current_stage: str
    available_tasks: list[str]
    discretionary_tasks: list[str]
    blocked_tasks: list[str]
    completed_tasks: list[str]
    investigation_stage_recommended: bool
    investigation_reason: str
    sla_status: Literal["ON_TRACK", "WARNING", "BREACH"]
    sla_note: str
    sentry_decisions: dict[str, str]


def _sla_status(elapsed_days: int, sla_days: int, claim_type: str) -> tuple[str, str]:
    """Calculate SLA status using case_plan_table thresholds."""
    plan = get_case_plan_table()
    row = plan.get(claim_type, plan.get("AUTO", {}))
    warn_pct  = row.get("sla_warning_pct", 0.70)
    breach_pct = row.get("sla_breach_pct",  0.90)
    pct = elapsed_days / sla_days if sla_days else 0
    if pct >= breach_pct:
        return "BREACH", f"{elapsed_days}/{sla_days} days elapsed ({pct:.0%}) — SLA BREACH."
    if pct >= warn_pct:
        return "WARNING", f"{elapsed_days}/{sla_days} days elapsed ({pct:.0%}) — SLA warning."
    return "ON_TRACK", f"{elapsed_days}/{sla_days} days elapsed ({pct:.0%}) — on track."


@tool(permission=ToolPermission.READ_ONLY)
def evaluate_sentries(
    claim_id: str,
    current_stage: str,
    completed_tasks: list[str],
    claim_type: str,
    fraud_score: float,
    estimated_damage: float,
    elapsed_days: int,
    sla_days: int,
    claimant_counter_offered: bool = False,
    requires_field_inspection: bool = False,
) -> dict:
    """
    Evaluate CMMN sentry conditions for the current case state.
    Returns which tasks are available, blocked, discretionary, or already
    completed — giving the case worker a clear view of what can happen next.
    Reads fraud score cutoff and SLA thresholds from case_plan_table.csv.
    """
    tasks = get_tasks()
    plan = get_case_plan_table()
    stages_meta = get_stages()
    plan_row = plan.get(claim_type, plan.get("AUTO", {}))
    fraud_flag = plan_row.get("fraud_score_flag", 0.65)

    # Build a rich context for sentry evaluation
    context = {
        "completed": set(completed_tasks),
        "fraud_score": fraud_score,
        "estimated_damage": estimated_damage,
        "fraud_flag": fraud_flag,
        "claimant_counter_offered": claimant_counter_offered,
        "requires_field_inspection": requires_field_inspection,
        "current_stage": current_stage,
    }

    available: list[str] = []
    discretionary: list[str] = []
    blocked: list[str] = []
    sentry_decisions: dict[str, str] = {}

    # Simple sentry rule engine — evaluates each task's sentry_in condition
    def _eval_sentry(task_id: str) -> TaskAvailability:
        if task_id in context["completed"]:
            return "COMPLETED"

        t = tasks.get(task_id, {})
        task_type = t.get("type", "AUTOMATED")
        task_stage = t.get("stage", "")
        sentry_in  = t.get("sentry_in", "always")

        # Stage gate: task's stage must be active or prior
        stage_order = {sid: s.get("order", 99) for sid, s in stages_meta.items()}
        current_order = stage_order.get(current_stage, 0)
        task_stage_order = stage_order.get(task_stage, 99)
        if task_stage_order > current_order + 1:
            return "BLOCKED"

        # Evaluate sentry_in conditions
        if sentry_in == "always":
            pass  # always available
        elif sentry_in == "REGISTER_CLAIM completed" and "REGISTER_CLAIM" not in context["completed"]:
            return "BLOCKED"
        elif sentry_in == "VERIFY_COVERAGE completed" and "VERIFY_COVERAGE" not in context["completed"]:
            return "BLOCKED"
        elif sentry_in == "INTAKE stage completed" and not {
            "REGISTER_CLAIM", "VERIFY_COVERAGE", "TRIAGE_SEVERITY"
        }.issubset(context["completed"]):
            return "BLOCKED"
        elif sentry_in == "COLLECT_DOCUMENTS completed" and "COLLECT_DOCUMENTS" not in context["completed"]:
            return "BLOCKED"
        elif sentry_in == "ASSESSMENT stage completed" and not {
            "COLLECT_DOCUMENTS", "ESTIMATE_DAMAGE"
        }.issubset(context["completed"]):
            return "BLOCKED"
        elif sentry_in == "INVESTIGATION stage opened" and current_stage != "INVESTIGATION":
            return "BLOCKED"
        elif "fraud_score >=" in sentry_in and context["fraud_score"] < context["fraud_flag"]:
            return "BLOCKED"
        elif sentry_in == "claimant_counter_offered == true" and not context["claimant_counter_offered"]:
            return "BLOCKED"
        elif sentry_in == "RESERVE_APPROVAL completed" and "RESERVE_APPROVAL" not in context["completed"]:
            return "BLOCKED"
        elif "claim_type requires_field_inspection" in sentry_in and not context["requires_field_inspection"]:
            return "BLOCKED"

        if task_type == "DISCRETIONARY":
            return "DISCRETIONARY"
        return "AVAILABLE"

    for task_id in tasks:
        status = _eval_sentry(task_id)
        sentry_decisions[task_id] = status
        if status == "AVAILABLE":
            available.append(task_id)
        elif status == "DISCRETIONARY":
            discretionary.append(task_id)
        elif status == "BLOCKED":
            blocked.append(task_id)

    # Should the INVESTIGATION stage be opened?
    invest_recommended = fraud_score >= fraud_flag
    invest_reason = (
        f"Fraud score {fraud_score:.2f} ≥ threshold {fraud_flag:.2f} — SIU referral recommended."
        if invest_recommended
        else f"Fraud score {fraud_score:.2f} < threshold {fraud_flag:.2f} — no investigation required."
    )

    sla_stat, sla_note = _sla_status(elapsed_days, sla_days, claim_type)

    return SentryEvaluationResult(
        claim_id=claim_id,
        current_stage=current_stage,
        available_tasks=available,
        discretionary_tasks=discretionary,
        blocked_tasks=blocked,
        completed_tasks=list(context["completed"]),
        investigation_stage_recommended=invest_recommended,
        investigation_reason=invest_reason,
        sla_status=sla_stat,
        sla_note=sla_note,
        sentry_decisions=sentry_decisions,
    ).model_dump()

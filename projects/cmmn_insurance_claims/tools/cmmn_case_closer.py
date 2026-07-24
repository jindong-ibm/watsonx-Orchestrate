"""
CMMN Tool 5 — Milestone Tracker & Case Closer
-----------------------------------------------
Implements the CLOSURE stage and the case-wide milestone tracking:
  CLOSE_CLAIM  — finalise case, archive record, emit M6 milestone

Also provides the milestone tracker that accumulates milestone history
across all stages and surfaces the full case timeline.

CMMN concepts demonstrated:
  - Milestone elements: named checkpoints that don't perform work,
    just signal that the case has reached a meaningful state
  - Case closure: terminal state; no tasks can be activated after closure
  - Full case audit trail: all stages, tasks, milestones with timestamps

Configuration loaded from:
  config/cmmn_config.yaml    — milestone definitions and trigger conditions
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_milestones, get_stages, get_tasks


CaseDisposition = Literal["APPROVED_AND_PAID", "DENIED", "WITHDRAWN", "SETTLED_NEGOTIATED"]


class MilestoneEntry(BaseModel):
    milestone_id: str
    label: str
    reached_at: str


class CaseClosureResult(BaseModel):
    claim_id: str
    case_status: Literal["CLOSED"]
    disposition: CaseDisposition
    settlement_paid_usd: float
    closure_reason: str
    stages_completed: list[str]
    tasks_completed: list[str]
    milestones_timeline: list[MilestoneEntry]
    milestones_missed: list[str]
    total_elapsed_days: int
    sla_met: bool
    case_audit_summary: str


@tool(permission=ToolPermission.READ_WRITE)
def close_case(
    claim_id: str,
    claim_type: str,
    disposition: str,
    settlement_paid_usd: float,
    closure_reason: str,
    stages_completed: list[str],
    tasks_completed: list[str],
    milestones_reached: list[str],
    total_elapsed_days: int,
    sla_days: int,
) -> dict:
    """
    Close a CMMN insurance claim case. Records the final disposition,
    builds the full milestone timeline from config/cmmn_config.yaml,
    determines which milestones were missed, and generates the case audit summary.
    Emits the terminal milestone M6_CASE_CLOSED.
    """
    milestones_cfg = get_milestones()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build milestone timeline for reached milestones
    timeline: list[MilestoneEntry] = []
    for mid in milestones_reached:
        meta = milestones_cfg.get(mid, {})
        timeline.append(MilestoneEntry(
            milestone_id=mid,
            label=meta.get("label", mid),
            reached_at=now_str,   # In production: real timestamps from event log
        ))

    # Always append M6 at closure
    m6 = milestones_cfg.get("M6_CASE_CLOSED", {})
    timeline.append(MilestoneEntry(
        milestone_id="M6_CASE_CLOSED",
        label=m6.get("label", "Case Closed"),
        reached_at=now_str,
    ))

    # Identify missed milestones
    all_milestone_ids = set(milestones_cfg.keys())
    reached_set = set(milestones_reached) | {"M6_CASE_CLOSED"}
    missed = sorted(all_milestone_ids - reached_set)

    sla_met = total_elapsed_days <= sla_days

    # Build audit summary
    disp = disposition.upper().replace(" ", "_")
    valid_dispositions = {"APPROVED_AND_PAID", "DENIED", "WITHDRAWN", "SETTLED_NEGOTIATED"}
    safe_disp: CaseDisposition = disp if disp in valid_dispositions else "DENIED"  # type: ignore[assignment]

    stages_list = ", ".join(stages_completed) if stages_completed else "none recorded"
    tasks_list  = ", ".join(tasks_completed)  if tasks_completed  else "none recorded"
    missed_list = ", ".join(missed)           if missed            else "none"

    audit = (
        f"Case {claim_id} CLOSED — {safe_disp}.\n"
        f"Settlement paid: ${settlement_paid_usd:,.2f}. Reason: {closure_reason}.\n"
        f"Stages completed: {stages_list}.\n"
        f"Tasks completed: {tasks_list}.\n"
        f"Milestones missed: {missed_list}.\n"
        f"Elapsed: {total_elapsed_days}/{sla_days} days — SLA {'MET' if sla_met else 'BREACHED'}."
    )

    return CaseClosureResult(
        claim_id=claim_id,
        case_status="CLOSED",
        disposition=safe_disp,
        settlement_paid_usd=settlement_paid_usd,
        closure_reason=closure_reason,
        stages_completed=stages_completed,
        tasks_completed=tasks_completed,
        milestones_timeline=timeline,
        milestones_missed=missed,
        total_elapsed_days=total_elapsed_days,
        sla_met=sla_met,
        case_audit_summary=audit,
    ).model_dump()

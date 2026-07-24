"""
CMMN Tool 4 — Settlement Decision
------------------------------------
Implements the DECISION stage tasks:
  RESERVE_APPROVAL   — manager approves or adjusts the financial reserve
  SETTLEMENT_OFFER   — auto-generates the settlement amount and offer letter
  NEGOTIATE_SETTLEMENT (discretionary) — handles counter-offers from the claimant

CMMN concepts demonstrated:
  - Human task (RESERVE_APPROVAL): requires manager sign-off
  - Automated task (SETTLEMENT_OFFER): runs without human input
  - Discretionary task (NEGOTIATE_SETTLEMENT): only activated if claimant counters
  - Auto-approve sentry: claims below auto_approve_limit bypass reserve approval
  - Milestone M5 (Decision Made) emitted at completion

Configuration loaded from:
  config/case_plan_table.csv   — auto_approve_limit, escalate_supervisor_on_override
"""

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_case_plan_table


DecisionOutcome = Literal["APPROVED", "DENIED", "NEGOTIATING", "PENDING_RESERVE_APPROVAL"]


class SettlementDecisionResult(BaseModel):
    claim_id: str
    outcome: DecisionOutcome
    settlement_amount_usd: float
    reserve_approved: bool
    auto_approved: bool
    supervisor_escalated: bool
    offer_letter_text: str
    negotiation_active: bool
    claimant_counter_amount_usd: float
    milestones_reached: list[str]
    completed_tasks: list[str]
    decision_summary: str


@tool(permission=ToolPermission.READ_WRITE)
def make_settlement_decision(
    claim_id: str,
    claim_type: str,
    claimant_name: str,
    damage_estimate_usd: float,
    reserve_amount_usd: float,
    adjuster_approved_amount: float,
    reserve_approved_by_manager: bool,
    denial_reason: str = "",
    claimant_counter_offered: bool = False,
    claimant_counter_amount_usd: float = 0.0,
) -> dict:
    """
    Execute the DECISION stage of a CMMN insurance claim. Handles auto-approval
    for small claims, manager reserve approval for larger ones, settlement offer
    generation, and optional negotiation for counter-offers.
    Auto-approve limit and escalation rules are read from case_plan_table.csv.
    """
    ct = claim_type.upper()
    plan = get_case_plan_table()
    plan_row = plan.get(ct, plan.get("AUTO", {}))
    auto_limit = plan_row.get("auto_approve_limit", 1000.0)
    escalate_on_override = plan_row.get("escalate_supervisor_on_override", True)

    completed_tasks: list[str] = []
    milestones: list[str] = []
    supervisor_escalated = False

    # Task: RESERVE_APPROVAL
    auto_approved = damage_estimate_usd <= auto_limit
    if auto_approved:
        reserve_approved = True
        completed_tasks.append("RESERVE_APPROVAL (auto-approved — below limit)")
        # If adjuster tried to override auto-approve, escalate
        if adjuster_approved_amount != damage_estimate_usd and escalate_on_override:
            supervisor_escalated = True
    else:
        reserve_approved = reserve_approved_by_manager
        completed_tasks.append("RESERVE_APPROVAL")
        if not reserve_approved:
            # Manager has not yet approved — pending
            return SettlementDecisionResult(
                claim_id=claim_id,
                outcome="PENDING_RESERVE_APPROVAL",
                settlement_amount_usd=0.0,
                reserve_approved=False,
                auto_approved=False,
                supervisor_escalated=False,
                offer_letter_text="Awaiting manager reserve approval.",
                negotiation_active=False,
                claimant_counter_amount_usd=0.0,
                milestones_reached=[],
                completed_tasks=completed_tasks,
                decision_summary=f"Claim {claim_id} pending reserve approval by manager.",
            ).model_dump()

    # Task: SETTLEMENT_OFFER
    settlement_amount = adjuster_approved_amount if adjuster_approved_amount > 0 else damage_estimate_usd

    if denial_reason:
        outcome: DecisionOutcome = "DENIED"
        offer_text = (
            f"Dear {claimant_name},\n\n"
            f"After careful review of claim {claim_id}, we are unable to approve your claim.\n"
            f"Reason: {denial_reason}\n\n"
            f"You have the right to appeal this decision within 30 days.\n\n"
            f"Sincerely, Claims Department"
        )
        settlement_amount = 0.0
    else:
        outcome = "APPROVED"
        offer_text = (
            f"Dear {claimant_name},\n\n"
            f"We are pleased to approve claim {claim_id} for ${settlement_amount:,.2f}.\n"
            f"Payment will be processed within 5-7 business days.\n\n"
            f"If you have questions, please contact your assigned adjuster.\n\n"
            f"Sincerely, Claims Department"
        )
    completed_tasks.append("SETTLEMENT_OFFER")

    # Discretionary Task: NEGOTIATE_SETTLEMENT
    negotiation_active = False
    if claimant_counter_offered and outcome != "DENIED":
        outcome = "NEGOTIATING"
        negotiation_active = True
        completed_tasks.append("NEGOTIATE_SETTLEMENT (discretionary — opened by case worker)")
        offer_text += (
            f"\n\n[NEGOTIATION NOTE] Claimant counter-offered ${claimant_counter_amount_usd:,.2f}. "
            f"Adjuster review required."
        )

    milestones.append("M5_DECISION_MADE")

    summary = (
        f"Decision for {claim_id}: {outcome}. "
        f"Settlement: ${settlement_amount:,.2f}. "
        f"{'Auto-approved.' if auto_approved else 'Manager-approved.' if reserve_approved else 'Pending approval.'}"
        f"{' SUPERVISOR ESCALATED.' if supervisor_escalated else ''}"
        f"{' Negotiation opened.' if negotiation_active else ''}"
    )

    return SettlementDecisionResult(
        claim_id=claim_id,
        outcome=outcome,
        settlement_amount_usd=settlement_amount,
        reserve_approved=reserve_approved,
        auto_approved=auto_approved,
        supervisor_escalated=supervisor_escalated,
        offer_letter_text=offer_text,
        negotiation_active=negotiation_active,
        claimant_counter_amount_usd=claimant_counter_amount_usd,
        milestones_reached=milestones,
        completed_tasks=completed_tasks,
        decision_summary=summary,
    ).model_dump()

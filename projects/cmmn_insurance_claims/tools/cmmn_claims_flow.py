"""
CMMN Insurance Claims Flow
-----------------------------
Orchestrates a full CMMN (Case Management Model and Notation) insurance
claim lifecycle as an agentic workflow.

Unlike a fixed BPMN process, this flow models the non-deterministic,
knowledge-worker-driven nature of CMMN:

  - The INVESTIGATION stage is DISCRETIONARY — only activated when the
    fraud score exceeds the configured threshold (sentry condition)
  - The SETTLEMENT branch forks on coverage status (CONFIRMED vs LAPSED/NOT_COVERED)
  - NEGOTIATION is a discretionary task activated when the claimant counters

Flow graph:

  START
    │
    ▼
  [1] process_case_intake          INTAKE stage (auto-activating)
    │
    ▼
  [2] evaluate_sentries             Check available tasks + SLA
    │
    ├─── coverage NOT confirmed ──────────────────────────────┐
    │                                                          ▼
    │                                                       [6] close_case (DENIED)
    │
    ▼ coverage confirmed
  [3] run_damage_assessment         ASSESSMENT + FRAUD_SCREENING
    │
    ├─── fraud score HIGH ──────────────────────────────────┐
    │    (sentry: score ≥ threshold)                        ▼
    │                                              [4b] evaluate_sentries
    │                                                  (INVESTIGATION open)
    │
    ▼ no investigation needed
  [4a] evaluate_sentries            Re-evaluate before DECISION
    │
    ▼
  [5] make_settlement_decision      DECISION stage
    │
    ▼
  [6] close_case                    CLOSURE stage → M6 milestone
    │
    ▼
  END
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END, Branch

from .cmmn_case_intake       import process_case_intake
from .cmmn_sentry_evaluator  import evaluate_sentries
from .cmmn_assessment        import run_damage_assessment
from .cmmn_settlement_decision import make_settlement_decision
from .cmmn_case_closer       import close_case


# ── Input schema ──────────────────────────────────────────────────────────────

class ClaimCaseInput(BaseModel):
    claimant_name: str = Field(description="Full name of the person filing the claim")
    policy_number: str = Field(description="Insurance policy number, e.g. 'POL-2024-88421'")
    claim_type: str = Field(description="Claim category: AUTO | PROPERTY | LIABILITY | MEDICAL")
    incident_date: str = Field(description="Date of incident in YYYY-MM-DD format")
    incident_description: str = Field(description="Brief description of what happened")
    estimated_damage: float = Field(description="Claimant's initial damage estimate in USD")
    policy_effective_date: str = Field(description="Policy start date YYYY-MM-DD")
    policy_expiry_date: str = Field(description="Policy expiry date YYYY-MM-DD")

    # Assessment inputs
    documents_received: list[str] = Field(
        default_factory=list,
        description="List of document IDs already provided, e.g. ['police_report','photos_of_damage']"
    )
    incident_on_weekend:        bool = Field(default=False, description="Did the incident occur on a weekend?")
    new_policy_recent_claim:    bool = Field(default=False, description="Policy is new (< 3 months) and claim is filed?")
    claim_near_policy_limit:    bool = Field(default=False, description="Claim amount is close to the policy limit?")
    multiple_claims_12_months:  bool = Field(default=False, description="Has the claimant filed multiple claims in the last 12 months?")
    inconsistent_damage_report: bool = Field(default=False, description="Inconsistencies found between damage photos and report?")
    no_police_report_auto:      bool = Field(default=False, description="AUTO claim with no police report filed?")
    single_witness:             bool = Field(default=False, description="Only one witness available for the incident?")

    # Decision inputs
    adjuster_approved_amount:     float = Field(default=0.0, description="Amount the adjuster approves (0 = use damage estimate)")
    reserve_approved_by_manager:  bool  = Field(default=True, description="Has the manager approved the financial reserve?")
    denial_reason:                str   = Field(default="", description="If denying, the reason; leave blank to approve")
    claimant_counter_offered:     bool  = Field(default=False, description="Did the claimant counter the settlement offer?")
    claimant_counter_amount_usd:  float = Field(default=0.0, description="Claimant's counter-offer amount in USD")

    # Case timeline
    elapsed_days: int = Field(default=1, description="Days elapsed since the case was opened")
    sla_days:     int = Field(default=30, description="SLA window in days for this claim type")


# ── Flow definition ───────────────────────────────────────────────────────────

@flow(
    name="cmmn_insurance_claims_flow",
    display_name="CMMN Insurance Claims Flow",
    description=(
        "A Case Management Model and Notation (CMMN) agentic workflow for insurance claims. "
        "Models non-deterministic, judgment-driven case progression: INTAKE → ASSESSMENT → "
        "[optional INVESTIGATION] → DECISION → CLOSURE, with sentry conditions guarding "
        "each stage and milestone tracking throughout."
    ),
    input_schema=ClaimCaseInput,
)
def build_cmmn_insurance_claims_flow(aflow: Flow) -> Flow:
    """
    Full CMMN insurance claim lifecycle: Intake → Sentry → Assessment →
    optional Investigation branch → Settlement Decision → Case Closure.
    """

    # ── Stage 1: INTAKE ───────────────────────────────────────────────────────
    intake_node = aflow.tool(process_case_intake)

    # ── Sentry check after intake: is coverage confirmed? ────────────────────
    sentry_post_intake = aflow.tool(
        evaluate_sentries,
        name="evaluate_sentries_post_intake",
        display_name="Evaluate Sentries (Post-Intake)",
    )

    coverage_branch: Branch = aflow.branch(
        evaluator="flow.process_case_intake.coverage_status == 'CONFIRMED'"
    )

    # ── Stage 2: ASSESSMENT (coverage confirmed path) ────────────────────────
    assessment_node = aflow.tool(run_damage_assessment)

    # ── Sentry: should INVESTIGATION stage open? ─────────────────────────────
    fraud_branch: Branch = aflow.branch(
        evaluator="flow.run_damage_assessment.investigation_stage_recommended == True"
    )

    # Investigation path: re-evaluate sentries with investigation stage open
    sentry_investigation = aflow.tool(
        evaluate_sentries,
        name="evaluate_sentries_investigation",
        display_name="Evaluate Sentries (Investigation Stage)",
    )

    # Standard path (no investigation): re-evaluate sentries before decision
    sentry_pre_decision = aflow.tool(
        evaluate_sentries,
        name="evaluate_sentries_pre_decision",
        display_name="Evaluate Sentries (Pre-Decision)",
    )

    # ── Stage 3: DECISION ─────────────────────────────────────────────────────
    decision_node_fraud   = aflow.tool(
        make_settlement_decision,
        name="make_settlement_decision_post_investigation",
        display_name="Settlement Decision (Post-Investigation)",
    )
    decision_node_direct  = aflow.tool(
        make_settlement_decision,
        name="make_settlement_decision_direct",
        display_name="Settlement Decision (Direct)",
    )

    # ── Stage 4: CLOSURE (both paths merge here) ──────────────────────────────
    closure_node_approved = aflow.tool(
        close_case,
        name="close_case_main",
        display_name="Close Case",
    )
    closure_node_denied   = aflow.tool(
        close_case,
        name="close_case_denied",
        display_name="Close Case (Coverage Denied)",
    )

    # ── Wire the graph ────────────────────────────────────────────────────────
    aflow.edge(START, intake_node)
    aflow.edge(intake_node, sentry_post_intake)
    aflow.edge(sentry_post_intake, coverage_branch)

    # Coverage NOT confirmed → immediate denial closure
    coverage_branch.case(True, assessment_node).case(False, closure_node_denied)

    # Assessment → fraud branch
    aflow.edge(assessment_node, fraud_branch)

    # High fraud → open investigation sentry → decision
    fraud_branch.case(True, sentry_investigation).case(False, sentry_pre_decision)

    aflow.edge(sentry_investigation, decision_node_fraud)
    aflow.edge(sentry_pre_decision,  decision_node_direct)

    # Both decision paths → closure
    aflow.edge(decision_node_fraud,  closure_node_approved)
    aflow.edge(decision_node_direct, closure_node_approved)

    aflow.edge(closure_node_approved, END)
    aflow.edge(closure_node_denied,   END)

    return aflow

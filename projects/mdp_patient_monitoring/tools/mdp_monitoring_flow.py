"""
MDP Patient Monitoring Flow
-----------------------------
Orchestrates a complete Markov Decision Process (MDP) monitoring cycle:

  1. EVALUATE  — classify patient vitals into a discrete MDP state (S0–S4)
  2. BRANCH    — route to the state-appropriate treatment path
  3. ACT       — recommend the optimal clinical action (policy π)
  4. REWARD    — calculate R(s, a, s') for the transition
  5. UPDATE    — apply Bellman Q-learning update to the policy table

The flow models MDP core components:
  - State space  S = {S0_STABLE, S1_MILD, S2_MODERATE, S3_CRITICAL, S4_DETERIORATING}
  - Action space A = {CONTINUE_MONITORING, INCREASE_MONITORING, CLINICAL_REVIEW,
                      IMMEDIATE_ESCALATION, URGENT_INTERVENTION}
  - Transition function T(s, a, s') — implicit in the next vitals observation
  - Reward function R(s, a, s')    — calculated by mdp_reward_calculator tool
  - Policy π(s) → a               — updated via Q-learning (Bellman equation)

              ┌─────────┐
              │  START  │
              └────┬────┘
                   │ vitals
          ┌────────▼─────────┐
          │  evaluate_state  │ → S0/S1/S2/S3/S4
          └────────┬─────────┘
                   │
          ┌────────▼──────────────────────────────┐
          │  BRANCH on current_state               │
          │  S0 → stable_path                      │
          │  S1 → mild_path                        │
          │  S2 → moderate_path                    │
          │  S3 → critical_path                    │
          │  S4 → deteriorating_path  (default)    │
          └────────┬──────────────────────────────-┘
                   │ (each path calls recommend_action)
          ┌────────▼────────────────┐
          │  recommend_action       │ → interventions
          └────────┬────────────────┘
                   │
          ┌────────▼────────────────┐
          │  calculate_reward       │ → R(s,a,s')
          └────────┬────────────────┘
                   │
          ┌────────▼────────────────┐
          │  update_policy          │ → Q-table update
          └────────┬────────────────┘
                   │
              ┌────▼────┐
              │   END   │
              └─────────┘
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END, Branch

from .mdp_state_evaluator import evaluate_patient_state
from .mdp_action_recommender import recommend_clinical_action
from .mdp_reward_calculator import calculate_mdp_reward
from .mdp_policy_updater import update_mdp_policy


# ── Input Schema ────────────────────────────────────────────────────────────────

class PatientVitalsInput(BaseModel):
    patient_id: str = Field(description="Unique patient identifier, e.g. 'P-1042'")
    heart_rate: float = Field(description="Heart rate in bpm, e.g. 88.0")
    systolic_bp: float = Field(description="Systolic blood pressure in mmHg, e.g. 135.0")
    diastolic_bp: float = Field(description="Diastolic blood pressure in mmHg, e.g. 85.0")
    spo2: float = Field(description="SpO2 oxygen saturation %, e.g. 97.0")
    temperature: float = Field(description="Body temperature in Celsius, e.g. 37.2")
    respiratory_rate: float = Field(description="Respiratory rate (breaths/min), e.g. 16.0")
    previous_state: str = Field(
        default="S0_STABLE",
        description="Patient's MDP state from the previous monitoring cycle"
    )
    previous_action: str = Field(
        default="CONTINUE_MONITORING",
        description="Clinical action taken in the previous monitoring cycle"
    )
    previous_cumulative_reward: float = Field(
        default=0.0,
        description="Accumulated discounted reward from previous cycles (γ=0.9)"
    )
    current_q_table_json: str = Field(
        default="{}",
        description="Serialised JSON of the current Q-table; pass back the value from previous cycle"
    )
    check_completed_on_time: bool = Field(
        default=True,
        description="Whether this monitoring check was completed within the recommended window"
    )


# ── Flow Definition ─────────────────────────────────────────────────────────────

@flow(
    name="mdp_patient_monitoring_flow",
    display_name="MDP Patient Monitoring Flow",
    description=(
        "Executes a complete Markov Decision Process cycle for healthcare patient monitoring. "
        "Evaluates patient vitals, branches on MDP state, recommends the optimal clinical action "
        "per policy π(s), calculates the reward R(s,a,s'), and updates the Q-table via Bellman equation."
    ),
    input_schema=PatientVitalsInput,
)
def build_mdp_patient_monitoring_flow(aflow: Flow) -> Flow:
    """
    MDP Patient Monitoring: one full cycle of State → Policy → Action → Reward → Policy Update.
    """

    # ── Step 1: Evaluate patient state ──────────────────────────────────────────
    evaluate_node = aflow.tool(evaluate_patient_state)

    # ── Step 2: Branch on current MDP state ─────────────────────────────────────
    state_branch: Branch = aflow.branch(
        evaluator="flow.evaluate_patient_state.current_state == 'S3_CRITICAL'"
    )

    # Critical path — IMMEDIATE_ESCALATION
    critical_action_node = aflow.tool(
        recommend_clinical_action,
        name="recommend_action_critical",
        display_name="Recommend Action (Critical)",
    )

    # Non-critical path — route to recommend based on state
    standard_action_node = aflow.tool(
        recommend_clinical_action,
        name="recommend_action_standard",
        display_name="Recommend Action (Standard)",
    )

    # ── Step 3: Reward calculation (both paths merge here) ──────────────────────
    reward_node = aflow.tool(calculate_mdp_reward)

    # ── Step 4: Q-table policy update ───────────────────────────────────────────
    policy_update_node = aflow.tool(update_mdp_policy)

    # ── Wire the graph ───────────────────────────────────────────────────────────
    aflow.edge(START, evaluate_node)
    aflow.edge(evaluate_node, state_branch)

    state_branch.case(True, critical_action_node).case(False, standard_action_node)

    aflow.edge(critical_action_node, reward_node)
    aflow.edge(standard_action_node, reward_node)

    aflow.edge(reward_node, policy_update_node)
    aflow.edge(policy_update_node, END)

    return aflow

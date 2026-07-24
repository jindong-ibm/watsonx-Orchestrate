"""
MDP Reward Calculator Tool
---------------------------
Computes the reward signal R(s, a, s') that quantifies how well the
chosen action improved (or worsened) the patient's state.

All reward weights and the optimal policy mapping are loaded at runtime from:
  config/policy_table.csv  — owned by clinical leads / operations managers
  config/mdp_config.yaml   — state severity ranks and Bellman hyperparameters

Adjust any weight in the CSV without touching this file.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_policy_table, get_states, get_mdp_params


class RewardResult(BaseModel):
    patient_id: str
    previous_state: str
    action_taken: str
    next_state: str
    immediate_reward: float
    policy_adherence_bonus: float
    timeliness_bonus: float
    total_reward: float
    discounted_cumulative_reward: float
    reward_breakdown: list[str]
    policy_feedback: str


@tool(permission=ToolPermission.READ_ONLY)
def calculate_mdp_reward(
    patient_id: str,
    previous_state: str,
    action_taken: str,
    next_state: str,
    check_completed_on_time: bool = True,
    previous_cumulative_reward: float = 0.0,
) -> dict:
    """
    Calculate the MDP reward R(s, a, s') for the last monitoring cycle.
    Combines an immediate transition reward, a policy-adherence bonus,
    and a timeliness bonus. Reward weights are loaded from config/policy_table.csv.
    Returns the updated discounted cumulative reward to track patient outcome
    quality over multiple cycles.
    """
    policy = get_policy_table()
    states = get_states()
    mdp = get_mdp_params()
    discount_factor = mdp["discount_factor"]

    # Per-state reward weights (fall back to previous state's row if next_state missing)
    row = policy.get(previous_state, policy.get("S0_STABLE", {}))
    w_transition  = row.get("reward_transition_per_level", 10.0)
    w_adherence   = row.get("reward_policy_adherence",     5.0)
    w_over        = row.get("reward_over_treatment",       -8.0)
    w_under       = row.get("reward_under_treatment",      -5.0)
    w_timely      = row.get("reward_timeliness_bonus",     3.0)
    w_late        = row.get("reward_timeliness_penalty",   -3.0)

    breakdown: list[str] = []

    prev_sev = states.get(previous_state, {}).get("severity", 0)
    next_sev = states.get(next_state,     {}).get("severity", 0)

    # Transition reward — scaled by configurable per-level weight
    delta = prev_sev - next_sev
    if delta > 0:
        immediate_reward = w_transition * delta
        breakdown.append(f"+{immediate_reward:.1f}: patient improved ({previous_state} → {next_state})")
    elif delta < 0:
        immediate_reward = w_transition * delta  # negative
        breakdown.append(f"{immediate_reward:.1f}: patient worsened ({previous_state} → {next_state})")
    else:
        immediate_reward = 0.0
        breakdown.append(f"0.0: state unchanged ({previous_state})")

    # Policy adherence bonus — weights from policy_table.csv
    optimal_action = policy.get(previous_state, {}).get("optimal_action_id", "CONTINUE_MONITORING")
    action_order = ["CONTINUE_MONITORING", "INCREASE_MONITORING", "CLINICAL_REVIEW",
                    "IMMEDIATE_ESCALATION", "URGENT_INTERVENTION"]
    taken_idx   = action_order.index(action_taken)   if action_taken   in action_order else 0
    optimal_idx = action_order.index(optimal_action) if optimal_action in action_order else 0

    if action_taken == optimal_action:
        policy_bonus = w_adherence
        breakdown.append(f"+{policy_bonus:.1f}: action matched MDP policy ({action_taken})")
    elif taken_idx > optimal_idx:
        policy_bonus = w_over
        breakdown.append(f"{policy_bonus:.1f}: over-treatment (used {action_taken}, optimal was {optimal_action})")
    else:
        policy_bonus = w_under
        breakdown.append(f"{policy_bonus:.1f}: under-treatment (used {action_taken}, optimal was {optimal_action})")

    # Timeliness bonus — weights from policy_table.csv
    timeliness_bonus = w_timely if check_completed_on_time else w_late
    label = "on-time" if check_completed_on_time else "late"
    breakdown.append(f"{'+' if timeliness_bonus > 0 else ''}{timeliness_bonus:.1f}: monitoring check was {label}")

    total_reward = immediate_reward + policy_bonus + timeliness_bonus
    cumulative = discount_factor * previous_cumulative_reward + total_reward

    feedback = (
        "Policy well-executed; patient outcome positive."
        if total_reward >= 10
        else "Consider adjusting action intensity to better match MDP policy."
        if total_reward < 0
        else "Acceptable outcome; minor policy deviation detected."
    )

    return RewardResult(
        patient_id=patient_id,
        previous_state=previous_state,
        action_taken=action_taken,
        next_state=next_state,
        immediate_reward=immediate_reward,
        policy_adherence_bonus=policy_bonus,
        timeliness_bonus=timeliness_bonus,
        total_reward=total_reward,
        discounted_cumulative_reward=cumulative,
        reward_breakdown=breakdown,
        policy_feedback=feedback,
    ).model_dump()

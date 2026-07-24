"""
MDP Policy Update Tool
-----------------------
Simulates offline Q-table updates using the Bellman equation after
each monitoring cycle.  In production this would write to a persistent
store (database / Redis); here it operates in-memory and returns the
updated Q-values so the flow can pass them to the next cycle.

Bellman update:
  Q(s, a) ← Q(s, a) + α · [R + γ · max_a' Q(s', a') − Q(s, a)]

Hyperparameters α and γ are loaded at runtime from config/mdp_config.yaml.
The seed Q-table (prior values) is initialised from config/policy_table.csv —
the q_value column for the optimal action seeds the diagonal; off-diagonal
values use conservative defaults so the table explores freely.
"""

from __future__ import annotations
import json
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .config_loader import get_mdp_params, get_policy_table, get_states, get_actions


class PolicyUpdateResult(BaseModel):
    patient_id: str
    state: str
    action: str
    old_q_value: float
    new_q_value: float
    bellman_delta: float
    updated_q_row: dict[str, float]
    policy_stable: bool
    best_action_after_update: str
    learning_summary: str


def _seed_q_table() -> dict[str, dict[str, float]]:
    """
    Build the initial Q-table from config/policy_table.csv.
    The optimal action for each state gets the CSV q_value;
    all other actions receive conservative defaults (0.0–0.5).
    """
    policy = get_policy_table()
    all_actions = list(get_actions().keys())
    off_diagonal = 0.05  # conservative exploration seed for non-optimal actions
    table: dict[str, dict[str, float]] = {}
    for state_id in get_states():
        row = policy.get(state_id, {})
        optimal = row.get("optimal_action_id", all_actions[0])
        optimal_q = float(row.get("q_value", 0.5))
        table[state_id] = {a: (optimal_q if a == optimal else off_diagonal) for a in all_actions}
    return table


@tool(permission=ToolPermission.READ_WRITE)
def update_mdp_policy(
    patient_id: str,
    current_state: str,
    action_taken: str,
    reward: float,
    next_state: str,
    current_q_table_json: str = "{}",
) -> dict:
    """
    Apply a Bellman Q-learning update for the (state, action) pair experienced
    in this monitoring cycle. α and γ are loaded from config/mdp_config.yaml;
    the seed Q-table is built from config/policy_table.csv. Returns the updated
    Q-row and best action under the new policy.
    """

    mdp = get_mdp_params()
    alpha = mdp["learning_rate"]
    gamma = mdp["discount_factor"]
    all_actions = list(get_actions().keys())
    seed_q = _seed_q_table()

    # Deserialise or fall back to config-seeded defaults
    try:
        q_table: dict[str, dict[str, float]] = json.loads(current_q_table_json) if current_q_table_json != "{}" else {}
    except (json.JSONDecodeError, ValueError):
        q_table = {}

    # Merge with config-seeded defaults for any missing states
    for s, row in seed_q.items():
        if s not in q_table:
            q_table[s] = dict(row)

    if current_state not in q_table:
        q_table[current_state] = dict(seed_q.get(current_state, {a: 0.0 for a in all_actions}))
    if action_taken not in q_table[current_state]:
        q_table[current_state][action_taken] = 0.0

    # Bellman update with config-driven α and γ
    old_q = q_table[current_state][action_taken]
    next_q_row = q_table.get(next_state, {a: 0.0 for a in all_actions})
    max_next_q = max(next_q_row.values()) if next_q_row else 0.0

    new_q = old_q + alpha * (reward + gamma * max_next_q - old_q)
    q_table[current_state][action_taken] = new_q
    delta = new_q - old_q

    updated_row = q_table[current_state]
    best_action = max(updated_row, key=lambda a: updated_row[a])
    policy_stable = abs(delta) < 0.01

    summary = (
        f"Q({current_state}, {action_taken}) updated: {old_q:.4f} → {new_q:.4f} (Δ={delta:+.4f}). "
        f"Best action for {current_state} is now '{best_action}'. "
        f"Policy {'stable' if policy_stable else 'still converging'}."
    )

    return PolicyUpdateResult(
        patient_id=patient_id,
        state=current_state,
        action=action_taken,
        old_q_value=old_q,
        new_q_value=new_q,
        bellman_delta=delta,
        updated_q_row=updated_row,
        policy_stable=policy_stable,
        best_action_after_update=best_action,
        learning_summary=summary,
    ).model_dump()

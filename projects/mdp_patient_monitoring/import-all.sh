#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# import-all.sh — Deploy the MDP Patient Monitoring project to watsonx Orchestrate
#
# Usage:
#   ./import-all.sh
#
# Requires:
#   orchestrate CLI authenticated and an active environment
#   (run `orchestrate env activate <env>` before this script if needed)
#
# Import order (dependencies first):
#   1. Python tools  (state evaluator, action recommender, reward calc, policy updater)
#   2. Flow tool     (MDP monitoring flow — depends on the Python tools)
#   3. Agents        (triage → treatment advisor → supervisor)
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

echo "═══════════════════════════════════════════════════════"
echo "  MDP Patient Monitoring — watsonx Orchestrate Deploy"
echo "═══════════════════════════════════════════════════════"

# ── 1. Python Tools ────────────────────────────────────────────────────────────
echo ""
echo "▸ Importing Python tools…"

for tool_file in \
    mdp_state_evaluator.py \
    mdp_action_recommender.py \
    mdp_reward_calculator.py \
    mdp_policy_updater.py; do

  echo "  → ${tool_file}"
  orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/${tool_file}"
done

# ── 2. Flow Tool ───────────────────────────────────────────────────────────────
echo ""
echo "▸ Importing flow tool…"
echo "  → mdp_monitoring_flow.py"
orchestrate tools import -k flow -f "${SCRIPT_DIR}/tools/mdp_monitoring_flow.py"

# ── 3. Agents (dependency order: leaf agents first, supervisor last) ───────────
echo ""
echo "▸ Importing agents…"

for agent_file in \
    mdp_treatment_advisor_agent.yaml \
    mdp_triage_agent.yaml \
    mdp_monitoring_supervisor.yaml; do

  echo "  → ${agent_file}"
  orchestrate agents import -f "${SCRIPT_DIR}/agents/${agent_file}"
done

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✓ Deployment complete!"
echo ""
echo "  Chat with the system:"
echo "    orchestrate chat start --agent mdp_monitoring_supervisor"
echo ""
echo "  Example prompt:"
echo "    'Patient P-2034: HR 155, BP 65/40, SpO2 88%, Temp 40.5°C, RR 32'"
echo "═══════════════════════════════════════════════════════"

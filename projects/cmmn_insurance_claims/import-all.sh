#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# import-all.sh — Deploy the CMMN Insurance Claims project to watsonx Orchestrate
#
# Usage:
#   ./import-all.sh
#
# Requires:
#   orchestrate CLI authenticated and an active environment
#   (run `orchestrate env activate <env>` before this script if needed)
#
# Import order (dependencies first):
#   1. Python tools   (config loader is bundled; intake, sentry, assessment,
#                      settlement, closer)
#   2. Flow tool      (CMMN claims flow — depends on Python tools)
#   3. Agents         (case worker → supervisor → coordinator)
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

echo "═══════════════════════════════════════════════════════════════"
echo "  CMMN Insurance Claims — watsonx Orchestrate Deploy"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Python Tools ────────────────────────────────────────────────────────────
echo ""
echo "▸ Importing Python tools…"

for tool_file in \
    cmmn_case_intake.py \
    cmmn_sentry_evaluator.py \
    cmmn_assessment.py \
    cmmn_settlement_decision.py \
    cmmn_case_closer.py; do

  echo "  → ${tool_file}"
  orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/${tool_file}"
done

# ── 2. Flow Tool ───────────────────────────────────────────────────────────────
echo ""
echo "▸ Importing flow tool…"
echo "  → cmmn_claims_flow.py"
orchestrate tools import -k flow -f "${SCRIPT_DIR}/tools/cmmn_claims_flow.py"

# ── 3. Agents (dependency order: leaf agents first, coordinator last) ──────────
echo ""
echo "▸ Importing agents…"

for agent_file in \
    cmmn_claims_supervisor_agent.yaml \
    cmmn_case_worker_agent.yaml \
    cmmn_claims_coordinator.yaml; do

  echo "  → ${agent_file}"
  orchestrate agents import -f "${SCRIPT_DIR}/agents/${agent_file}"
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✓ Deployment complete!"
echo ""
echo "  Chat with the system:"
echo "    orchestrate chat start --agent cmmn_claims_coordinator"
echo ""
echo "  Example prompts:"
echo "    'Process a new AUTO claim for Alice Johnson, policy POL-2024-001,"
echo "     incident 2024-10-15, damage \$3,800, rear-end collision'"
echo ""
echo "    'Bob Martinez filed a PROPERTY claim for \$85,000 — multiple fraud"
echo "     signals detected, new policy, inconsistent damage report'"
echo ""
echo "  Config tuning (no redeploy needed):"
echo "    Edit config/case_plan_table.csv  — thresholds, rewards, limits"
echo "    Edit config/cmmn_config.yaml     — stages, tasks, sentry conditions"
echo "═══════════════════════════════════════════════════════════════"

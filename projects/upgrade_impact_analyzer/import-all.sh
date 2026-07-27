#!/usr/bin/env bash

# Import script for Upgrade Impact Analyzer & Rollback Planner
# Imports all 5 Python tools and the agent into watsonx Orchestrate using the CLI.
#
# Usage:
#   chmod +x import-all.sh
#   ./import-all.sh
#
# Prerequisites:
#   - watsonx Orchestrate ADK installed: pip install ibm-watsonx-orchestrate
#   - CLI authenticated and an active environment:
#       orchestrate env activate <env-name>
#
# Made with Bob

set -e

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

echo "======================================================================"
echo "  Upgrade Impact Analyzer & Rollback Planner — wxO Import"
echo "======================================================================"
echo ""

# ── Import Python Tools ────────────────────────────────────────────────────

echo "Step 1/6: Importing parse_release_notes..."
orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/parse_release_notes.py"
if [ $? -eq 0 ]; then
    echo "  ✓ parse_release_notes imported"
else
    echo "  ✗ parse_release_notes import failed"
    exit 1
fi

echo ""
echo "Step 2/6: Importing inventory_deployed_config..."
orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/inventory_deployed_config.py"
if [ $? -eq 0 ]; then
    echo "  ✓ inventory_deployed_config imported"
else
    echo "  ✗ inventory_deployed_config import failed"
    exit 1
fi

echo ""
echo "Step 3/6: Importing flag_dependency_constraints..."
orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/flag_dependency_constraints.py"
if [ $? -eq 0 ]; then
    echo "  ✓ flag_dependency_constraints imported"
else
    echo "  ✗ flag_dependency_constraints import failed"
    exit 1
fi

echo ""
echo "Step 4/6: Importing build_migration_checklist..."
orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/build_migration_checklist.py"
if [ $? -eq 0 ]; then
    echo "  ✓ build_migration_checklist imported"
else
    echo "  ✗ build_migration_checklist import failed"
    exit 1
fi

echo ""
echo "Step 5/6: Importing generate_rollback_plan..."
orchestrate tools import -k python -f "${SCRIPT_DIR}/tools/generate_rollback_plan.py"
if [ $? -eq 0 ]; then
    echo "  ✓ generate_rollback_plan imported"
else
    echo "  ✗ generate_rollback_plan import failed"
    exit 1
fi

# ── Import Agent ──────────────────────────────────────────────────────────────

echo ""
echo "Step 6/6: Importing upgrade_impact_analyzer agent..."
orchestrate agents import -f "${SCRIPT_DIR}/agents/upgrade_impact_analyzer_agent.yaml"
if [ $? -eq 0 ]; then
    echo "  ✓ upgrade_impact_analyzer_agent imported"
else
    echo "  ✗ upgrade_impact_analyzer_agent import failed"
    exit 1
fi

echo ""
echo "======================================================================"
echo "  Import Complete!"
echo "======================================================================"
echo ""
echo "To run an upgrade impact analysis:"
echo "  1. orchestrate chat start"
echo "  2. Select 'upgrade_impact_analyzer'"
echo "  3. Say: 'Analyse the upgrade from 1.10.0 to 1.15.0'"
echo "     Then paste your release notes, agent list, and tool list when prompted."
echo ""
echo "Tools imported:"
echo "  ✓ parse_release_notes        — Parse wxO/ADK changelog for breaking changes"
echo "  ✓ inventory_deployed_config  — Build inventory from CLI list output"
echo "  ✓ flag_dependency_constraints — Flag ADK version constraint violations"
echo "  ✓ build_migration_checklist  — Generate ordered, owner-assigned checklist"
echo "  ✓ generate_rollback_plan     — Stage-by-stage rollback with CLI commands"
echo ""

# Made with Bob

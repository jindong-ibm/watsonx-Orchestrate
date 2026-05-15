#!/usr/bin/env bash
# =============================================================================
# Predictive Maintenance Agent — Deployment Script
#
# Imports all components into watsonx Orchestrate in the correct order:
#   1. MCP Toolkits (Sensor, Maintenance History, Spare Parts)
#   2. Python Tools (anomaly analysis, recommendation, plan, report)
#   3. Agentic Workflow (predictive_maintenance_flow)
#   4. Knowledge Base (equipment manuals)
#   5. Native Agent (predictive_maintenance_agent)
#
# Prerequisites:
#   - watsonx Orchestrate ADK installed: pip install ibm-watsonx-orchestrate
#   - Local server running: orchestrate server start
#   - Authenticated: orchestrate env activate <env-name>
#
# Usage:
#   chmod +x import-all.sh
#   ./import-all.sh
# =============================================================================

set -e  # Exit immediately on any error

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# ── Colour helpers ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Colour

ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }
info() { echo -e "${CYAN}  → $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }

echo ""
echo "============================================================"
echo "  Predictive Maintenance Agent — Deployment"
echo "============================================================"
echo ""

# =============================================================================
# STEP 1: Import MCP Toolkits
# =============================================================================
echo -e "${CYAN}[1/5] Importing MCP Toolkits...${NC}"
echo ""

# 1a. Sensor MCP Server
info "Importing Sensor MCP Server toolkit..."
orchestrate toolkits import \
    --kind mcp \
    --name sensor_mcp_server \
    --description "IoT sensor data toolkit — provides real-time sensor metrics for manufacturing equipment" \
    --package-root "${SCRIPT_DIR}/mcp_servers/sensor_mcp_server" \
    --command "python server.py" \
    --tools "*"
ok "Sensor MCP Server imported"

echo ""

# 1b. Maintenance History MCP Server
info "Importing Maintenance History MCP Server toolkit..."
orchestrate toolkits import \
    --kind mcp \
    --name maintenance_history_mcp_server \
    --description "Maintenance history toolkit — retrieves historical maintenance records from CMMS database" \
    --package-root "${SCRIPT_DIR}/mcp_servers/maintenance_history_mcp_server" \
    --command "python server.py" \
    --tools "*"
ok "Maintenance History MCP Server imported"

echo ""

# 1c. Spare Parts MCP Server
info "Importing Spare Parts MCP Server toolkit..."
orchestrate toolkits import \
    --kind mcp \
    --name spare_parts_mcp_server \
    --description "Spare parts toolkit — checks stock levels and places orders via the Spare Parts System" \
    --package-root "${SCRIPT_DIR}/mcp_servers/spare_parts_mcp_server" \
    --command "python server.py" \
    --tools "*"
ok "Spare Parts MCP Server imported"

echo ""

# =============================================================================
# STEP 2: Import Python Tools
# =============================================================================
echo -e "${CYAN}[2/5] Importing Python Tools...${NC}"
echo ""

info "Importing analyze_sensor_anomalies..."
orchestrate tools import \
    -k python \
    -f "${SCRIPT_DIR}/tools/analyze_sensor_anomalies.py"
ok "analyze_sensor_anomalies imported"

info "Importing generate_maintenance_recommendation..."
orchestrate tools import \
    -k python \
    -f "${SCRIPT_DIR}/tools/generate_maintenance_recommendation.py"
ok "generate_maintenance_recommendation imported"

info "Importing generate_maintenance_plan..."
orchestrate tools import \
    -k python \
    -f "${SCRIPT_DIR}/tools/generate_maintenance_plan.py"
ok "generate_maintenance_plan imported"

info "Importing format_maintenance_report..."
orchestrate tools import \
    -k python \
    -f "${SCRIPT_DIR}/tools/format_maintenance_report.py"
ok "format_maintenance_report imported"

echo ""

# =============================================================================
# STEP 3: Import Agentic Workflow (Flow)
# =============================================================================
echo -e "${CYAN}[3/5] Importing Agentic Workflow...${NC}"
echo ""

info "Importing predictive_maintenance_flow..."
orchestrate tools import \
    -k flow \
    -f "${SCRIPT_DIR}/tools/predictive_maintenance_flow.py"
ok "predictive_maintenance_flow imported"

echo ""

# =============================================================================
# STEP 4: Import Knowledge Base
# =============================================================================
echo -e "${CYAN}[4/5] Importing Knowledge Base...${NC}"
echo ""

info "Importing equipment_manuals_kb..."
warn "Ensure document files exist in ${SCRIPT_DIR}/knowledge-bases/docs/ before importing."
orchestrate knowledge-bases import \
    -f "${SCRIPT_DIR}/knowledge-bases/equipment_manuals_kb.yaml"
ok "equipment_manuals_kb imported"

echo ""

# =============================================================================
# STEP 5: Import Agent
# =============================================================================
echo -e "${CYAN}[5/5] Importing Agent...${NC}"
echo ""

info "Importing predictive_maintenance_agent..."
orchestrate agents import \
    -f "${SCRIPT_DIR}/agents/predictive_maintenance_agent.yaml"
ok "predictive_maintenance_agent imported"

echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================================"
echo -e "${GREEN}  ✅ Deployment Complete!${NC}"
echo "============================================================"
echo ""
echo "  Imported components:"
echo "    MCP Toolkits  : sensor_mcp_server"
echo "                    maintenance_history_mcp_server"
echo "                    spare_parts_mcp_server"
echo "    Python Tools  : analyze_sensor_anomalies"
echo "                    generate_maintenance_recommendation"
echo "                    generate_maintenance_plan"
echo "                    format_maintenance_report"
echo "    Flow          : predictive_maintenance_flow"
echo "    Knowledge Base: equipment_manuals_kb"
echo "    Agent         : predictive_maintenance_agent"
echo ""
echo "  To test the agent:"
echo "    1. Run: orchestrate chat start"
echo "    2. Select 'predictive_maintenance_agent'"
echo "    3. Try: 'Run predictive maintenance analysis for PUMP-001 (centrifugal_pump)'"
echo ""
echo "  To test the flow locally:"
echo "    cd ${SCRIPT_DIR}"
echo "    python flow_main.py --device-name PUMP-001 --device-type centrifugal_pump"
echo ""

# Made with Bob
#!/bin/bash

# Import script for AI Agent Review Tool
# This script imports the agent and all tools into watsonx Orchestrate

set -e

echo "=========================================="
echo "AI Agent Review Tool - Import Script"
echo "=========================================="
echo ""

# Check if orchestrate CLI is available
if ! command -v orchestrate &> /dev/null; then
    echo "Error: orchestrate CLI not found. Please install watsonx Orchestrate ADK first."
    echo "  pip install ibm-watsonx-orchestrate"
    exit 1
fi

echo "Step 1: Importing Python tools..."
echo "----------------------------------"

# Import analyze_agent_config tool
echo "Importing analyze_agent_config..."
orchestrate tools import -k python -f tools/analyze_agent_config.py

# Import generate_recommendations tool
echo "Importing generate_recommendations..."
orchestrate tools import -k python -f tools/generate_recommendations.py

# Import compare_agents tool
echo "Importing compare_agents..."
orchestrate tools import -k python -f tools/compare_agents.py

# Import validate_live_agent tool
echo "Importing validate_live_agent..."
orchestrate tools import -k python -f tools/validate_live_agent.py

# Import validate_tool_schemas tool
echo "Importing validate_tool_schemas..."
orchestrate tools import -k python -f tools/validate_tool_schemas.py

# Import analyze_flow tool
echo "Importing analyze_flow..."
orchestrate tools import -k python -f tools/analyze_flow.py

# Import export_report tool
echo "Importing export_report..."
orchestrate tools import -k python -f tools/export_report.py

echo ""
echo "Step 2: Importing knowledge base..."
echo "----------------------------------"
echo "Importing agent anti-patterns knowledge base..."
orchestrate knowledge-bases import -f knowledge-bases/agent_antipatterns_kb.yaml

echo ""
echo "Step 3: Importing agent..."
echo "----------------------------------"
echo "Importing AI Agent Review & Optimization Expert..."
orchestrate agents import -f agents/agent_review_agent.yaml

echo ""
echo "=========================================="
echo "Import Complete!"
echo "=========================================="
echo ""
echo "The AI Agent Review Tool has been successfully imported."
echo ""
echo "You can now:"
echo "  1. Use the agent in watsonx Orchestrate UI"
echo "  2. Call the tools programmatically"
echo "  3. Query the knowledge base for anti-patterns"
echo ""
echo "Example usage:"
echo "  orchestrate chat ask --agent-name agent_review_agent 'Analyze my agent'"
echo ""
echo "For more information, see README.md"
echo ""

# Made with Bob

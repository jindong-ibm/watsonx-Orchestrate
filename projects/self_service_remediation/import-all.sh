#!/usr/bin/env bash

# Import script for Self-Service Remediation Agent
# This script imports all tools and agents into watsonx Orchestrate

# Uncomment the line below if you need to activate the local environment
# orchestrate env activate local

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

echo "=================================================="
echo "Importing Self-Service Remediation Agent"
echo "=================================================="
echo ""

# Import Python tools
echo "Importing Python tools..."
for tool_file in fetch_known_issues.py collect_cluster_status.py collect_service_logs.py analyze_and_match.py execute_remediation.py; do
  echo "  - Importing ${tool_file}..."
  orchestrate tools import -k python \
    -p ${SCRIPT_DIR}/tools \
    -f ${SCRIPT_DIR}/tools/${tool_file} \
    -r ${SCRIPT_DIR}/requirements.txt
done
echo ""

# Import Flow tools
echo "Importing Flow tools..."
for flow_file in remediation_flow.py; do
  echo "  - Importing ${flow_file}..."
  orchestrate tools import -k flow -f ${SCRIPT_DIR}/tools/${flow_file}
done
echo ""

# Import agents
echo "Importing agents..."
for agent in self_service_remediation_agent.yaml; do
  echo "  - Importing ${agent}..."
  orchestrate agents import -f ${SCRIPT_DIR}/agents/${agent}
done
echo ""

echo "=================================================="
echo "Import completed successfully!"
echo "=================================================="
echo ""
echo "To use the agent:"
echo "  1. Start the chat interface: orchestrate chat start"
echo "  2. Select 'self_service_remediation_agent'"
echo "  3. Describe your issue (e.g., 'My pods are crashing with OOMKilled errors')"
echo ""
echo "Notes:"
echo "  - The agent runs in dry-run mode by default (safe preview)"
echo "  - Ensure 'oc' CLI is configured with cluster access before using"
echo "  - Set your namespace if not using the default 'cpd'"
echo ""

# Made with Bob

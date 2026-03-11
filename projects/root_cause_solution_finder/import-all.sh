#!/usr/bin/env bash

# Import script for Root Cause Solution Finder Agent
# This script imports all tools and agents into watsonx Orchestrate

# Uncomment the line below if you need to activate the local environment
# orchestrate env activate local

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

echo "=================================================="
echo "Importing Root Cause Solution Finder Agent"
echo "=================================================="
echo ""

# Import Python tools
echo "Importing Python tools..."
for tool in search_ibm_docs.py; do
  echo "  - Importing ${tool}..."
  orchestrate tools import -k python -f ${SCRIPT_DIR}/tools/${tool} -r ${SCRIPT_DIR}/tools/requirements.txt
done
echo ""

# Import Flow tools
echo "Importing Flow tools..."
for flow in root_cause_solution_flow.py; do
  echo "  - Importing ${flow}..."
  orchestrate tools import -k flow -f ${SCRIPT_DIR}/tools/${flow}
done
echo ""

# Import agents
echo "Importing agents..."
for agent in root_cause_solution_finder.yaml; do
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
echo "  2. Select 'root_cause_solution_finder' agent"
echo "  3. Ask about root cause issues (e.g., 'Help me troubleshoot OutOfMemory errors')"
echo ""

# Made with Bob

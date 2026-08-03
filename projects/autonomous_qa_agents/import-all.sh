#!/bin/bash

# Autonomous QA Agents - Import All Script
# This script imports all agents and tools into watsonx Orchestrate

set -e  # Exit on error

echo "=========================================="
echo "Autonomous QA Agents - Import Script"
echo "=========================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check if orchestrate CLI is available
if ! command -v orchestrate &> /dev/null; then
    print_error "orchestrate CLI not found. Please install watsonx Orchestrate ADK first."
    exit 1
fi

print_success "orchestrate CLI found"
echo ""

# Import Test Generation Tools
echo "=========================================="
echo "Importing Test Generation Tools..."
echo "=========================================="

print_info "Importing batch_analyze_features tool..."
orchestrate tools import -k python -f tools/test_generation/batch_analyze_features.py
print_success "batch_analyze_features imported"

print_info "Importing analyze_requirements tool..."
orchestrate tools import -k python -f tools/test_generation/analyze_requirements.py
print_success "analyze_requirements imported"

print_info "Importing parse_release_notes tool..."
orchestrate tools import -k python -f tools/test_generation/parse_release_notes.py
print_success "parse_release_notes imported"

print_info "Importing detect_api_changes tool..."
orchestrate tools import -k python -f tools/test_generation/detect_api_changes.py
print_success "detect_api_changes imported"

print_info "Importing generate_functional_tests tool..."
orchestrate tools import -k python -f tools/test_generation/generate_functional_tests.py
print_success "generate_functional_tests imported"

print_info "Importing generate_regression_tests tool..."
orchestrate tools import -k python -f tools/test_generation/generate_regression_tests.py
print_success "generate_regression_tests imported"

print_info "Importing generate_edge_cases tool..."
orchestrate tools import -k python -f tools/test_generation/generate_edge_cases.py
print_success "generate_edge_cases imported"

echo ""

# Import Exploratory Testing Tools
echo "=========================================="
echo "Importing Exploratory Testing Tools..."
echo "=========================================="

print_info "Importing explore_ui tool..."
orchestrate tools import -k python -f tools/exploratory_testing/explore_ui.py
print_success "explore_ui imported"

print_info "Importing test_unexpected_inputs tool..."
orchestrate tools import -k python -f tools/exploratory_testing/test_unexpected_inputs.py
print_success "test_unexpected_inputs imported"

print_info "Importing report_findings tool..."
orchestrate tools import -k python -f tools/exploratory_testing/report_findings.py
print_success "report_findings imported"

print_info "Importing generate_tests_from_findings tool..."
orchestrate tools import -k python -f tools/exploratory_testing/generate_tests_from_findings.py
print_success "generate_tests_from_findings imported"

echo ""

# Import NFR Assessment Tools
echo "=========================================="
echo "Importing NFR Assessment Tools..."
echo "=========================================="

print_info "Importing create_load_tests tool..."
orchestrate tools import -k python -f tools/nfr_assessment/create_load_tests.py
print_success "create_load_tests imported"

print_info "Importing execute_performance_tests tool..."
orchestrate tools import -k python -f tools/nfr_assessment/execute_performance_tests.py
print_success "execute_performance_tests imported"

print_info "Importing generate_nfr_report tool..."
orchestrate tools import -k python -f tools/nfr_assessment/generate_nfr_report.py
print_success "generate_nfr_report imported"

echo ""

# Import Agents
echo "=========================================="
echo "Importing Agents..."
echo "=========================================="

print_info "Importing Test Generation Agent..."
orchestrate agents import -f agents/test_generation_agent.yaml
print_success "test_generation_agent imported"

print_info "Importing Exploratory Testing Agent..."
orchestrate agents import -f agents/exploratory_testing_agent.yaml
print_success "exploratory_testing_agent imported"

print_info "Importing NFR Assessment Agent..."
orchestrate agents import -f agents/nfr_assessment_agent.yaml
print_success "nfr_assessment_agent imported"

print_info "Importing QA Coordinator Agent..."
orchestrate agents import -f agents/qa_coordinator_agent.yaml
print_success "qa_coordinator_agent imported"

echo ""
echo "=========================================="
echo "Import Complete!"
echo "=========================================="
echo ""
print_success "All agents and tools have been imported successfully"
echo ""
echo "Available Agents:"
echo "  • test_generation_agent - Generates comprehensive test suites"
echo "  • exploratory_testing_agent - Performs human-like exploratory testing"
echo "  • nfr_assessment_agent - Assesses performance and NFRs"
echo "  • qa_coordinator_agent - Orchestrates the complete QA workflow"
echo ""
echo "To use the QA system, invoke the qa_coordinator_agent and provide:"
echo "  • Requirements documents"
echo "  • Release notes (optional)"
echo "  • API specifications (optional)"
echo "  • Application URL or endpoints"
echo "  • Test scope (comprehensive, functional, exploratory, or performance)"
echo ""
print_info "For detailed usage examples, see README.md"
echo ""

# Made with Bob

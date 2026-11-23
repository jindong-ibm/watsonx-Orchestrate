"""
Main agentic workflow for the Self-Service Remediation agent.

Orchestrates the full pipeline:
1. Fetch known issues from IBM documentation
2. Collect cluster status
3. Collect service logs
4. Analyze and match errors against known issues
5. Execute remediation for matched issues
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

from .fetch_known_issues import fetch_known_issues
from .collect_cluster_status import collect_cluster_status
from .collect_service_logs import collect_service_logs
from .analyze_and_match import analyze_and_match_issues
from .jev_issue_assessor import jev_assess_matches
from .execute_remediation import execute_remediation


# --- Flow input/output schemas ---

class RemediationFlowInput(BaseModel):
    """Input schema for the self-service remediation flow."""
    user_issue_description: str = Field(
        description="Description of the issue the customer is experiencing"
    )
    namespace: str = Field(
        default="cpd",
        description="OpenShift namespace where watsonx Orchestrate is deployed"
    )
    release_version: str = Field(
        default="5.4.x",
        description="watsonx Orchestrate release version (e.g., '5.4.x')"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, show remediation steps without executing them"
    )


class RemediationFlowOutput(BaseModel):
    """Output schema for the self-service remediation flow."""
    diagnosis_summary: str = Field(description="Summary of the diagnosis")
    matched_issues: List[Dict[str, Any]] = Field(description="Known issues matched")
    remediation_result: Dict[str, Any] = Field(description="Result of remediation execution")
    cluster_health: str = Field(description="Current cluster health assessment")
    recommendations: List[str] = Field(description="Next steps and recommendations")


# --- Intermediate tool for diagnosis summary ---

@tool(permission=ToolPermission.READ_ONLY)
def generate_diagnosis_report(
    user_issue_description: str,
    cluster_status: Dict[str, Any],
    service_logs: Dict[str, Any],
    analysis_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate a comprehensive diagnosis report combining all collected data.

    Summarizes the cluster state, service log findings, and matched issues
    into a report for the user.

    Args:
        user_issue_description: Original issue reported by the user
        cluster_status: Collected cluster status data
        service_logs: Collected service log data
        analysis_result: Result of the issue matching analysis

    Returns:
        Dictionary with diagnosis summary, matched issues, health status,
        and top remediation candidate.
    """
    matched = analysis_result.get("matched_issues", [])
    severity = analysis_result.get("severity", "UNKNOWN")
    health = cluster_status.get("overall_health", "UNKNOWN")

    # Build summary
    summary_parts = [
        f"## Diagnosis Report",
        f"",
        f"**User-reported issue:** {user_issue_description}",
        f"**Cluster health:** {health}",
        f"**Severity assessment:** {severity}",
        f"**Error logs found:** {service_logs.get('total_errors', 0)}",
        f"**Warning logs found:** {service_logs.get('total_warnings', 0)}",
        f"**Unhealthy pods:** {len(cluster_status.get('unhealthy_pods', []))}",
        f"",
    ]

    if matched:
        summary_parts.append(f"### Matched Known Issues ({len(matched)}):")
        for i, m in enumerate(matched[:3], 1):
            summary_parts.append(
                f"{i}. **{m['title']}** (confidence: {m['confidence']:.0%}, component: {m['component']})"
            )
        summary_parts.append("")
        summary_parts.append("Proceeding with automated remediation for the top match.")
    else:
        summary_parts.append("### No known issues matched.")
        summary_parts.append("Manual investigation recommended.")

    # Determine top remediation candidate
    top_match = matched[0] if matched else None

    return {
        "diagnosis_summary": "\n".join(summary_parts),
        "matched_issues": matched,
        "cluster_health": health,
        "top_match": top_match,
        "severity": severity
    }


# --- Main flow ---

@flow(
    name="self_service_remediation_flow",
    display_name="Self-Service Remediation Flow",
    description=(
        "Diagnoses watsonx Orchestrate issues on OpenShift clusters by collecting "
        "cluster status and service logs, matching them against known issues from "
        "IBM documentation, using Jev (TypeSafe AI) to probabilistically rank matches "
        "and classify remediation safety, then executing automated remediation steps "
        "gated by Jev's confidence and safety classification."
    ),
    input_schema=RemediationFlowInput,
    output_schema=RemediationFlowOutput
)
def build_self_service_remediation_flow(aflow: Flow) -> Flow:
    """
    Build the self-service remediation agentic workflow.

    Pipeline:
      START -> fetch_known_issues -> collect_cluster_status -> collect_service_logs
            -> analyze_and_match_issues -> jev_assess_matches
            -> generate_diagnosis_report -> execute_remediation -> END

    The jev_assess_matches node sits between the keyword matcher and the diagnosis
    report. It calls Jev for each candidate match to:
      - Confirm whether the error log genuinely matches the known issue (noul)
      - Classify remediation safety: read_only_safe / requires_approval / destructive_blocked (choice)
      - Assess whether the issue will self-resolve (noul)

    The top_match and remediation_safety from jev_assess_matches replace the
    keyword-ranked top_match as inputs to execute_remediation. When TYPESAFE_API_KEY
    is not set, jev_assess_matches falls back gracefully to the keyword ranking.

    Args:
        aflow: Flow builder instance

    Returns:
        Configured flow
    """
    # Node 1: Fetch known issues from IBM docs
    fetch_issues_node = aflow.tool(
        fetch_known_issues,
        name="fetch_issues",
        display_name="Fetch Known Issues"
    )
    fetch_issues_node.map_input(
        input_variable="release_version",
        expression="flow.input.release_version"
    )

    # Node 2: Collect cluster status
    cluster_status_node = aflow.tool(
        collect_cluster_status,
        name="cluster_status",
        display_name="Collect Cluster Status"
    )
    cluster_status_node.map_input(
        input_variable="namespace",
        expression="flow.input.namespace"
    )

    # Node 3: Collect service logs
    service_logs_node = aflow.tool(
        collect_service_logs,
        name="service_logs",
        display_name="Collect Service Logs"
    )
    service_logs_node.map_input(
        input_variable="namespace",
        expression="flow.input.namespace"
    )
    service_logs_node.map_input(
        input_variable="since_minutes",
        expression="60"
    )

    # Node 4: Analyze and match issues
    analysis_node = aflow.tool(
        analyze_and_match_issues,
        name="analysis",
        display_name="Analyze & Match Issues"
    )
    analysis_node.map_input(
        input_variable="cluster_status",
        expression="flow.cluster_status.output"
    )
    analysis_node.map_input(
        input_variable="service_logs",
        expression="flow.service_logs.output"
    )
    analysis_node.map_input(
        input_variable="known_issues",
        expression="flow.fetch_issues.output"
    )

    # Node 5: Jev match assessment
    # Re-ranks keyword matches and classifies remediation safety using Jev.
    # Gracefully falls back to keyword ranking when TYPESAFE_API_KEY is not set.
    jev_node = aflow.tool(
        jev_assess_matches,
        name="jev_assessment",
        display_name="Jev Match Assessment"
    )
    jev_node.map_input(
        input_variable="analysis_result",
        expression="flow.analysis.output"
    )
    jev_node.map_input(
        input_variable="cluster_status",
        expression="flow.cluster_status.output"
    )
    jev_node.map_input(
        input_variable="service_logs",
        expression="flow.service_logs.output"
    )

    # Node 6: Generate diagnosis report
    # analysis_result now passed through jev_assessment for enriched matched_issues
    diagnosis_node = aflow.tool(
        generate_diagnosis_report,
        name="diagnosis",
        display_name="Generate Diagnosis Report"
    )
    diagnosis_node.map_input(
        input_variable="user_issue_description",
        expression="flow.input.user_issue_description"
    )
    diagnosis_node.map_input(
        input_variable="cluster_status",
        expression="flow.cluster_status.output"
    )
    diagnosis_node.map_input(
        input_variable="service_logs",
        expression="flow.service_logs.output"
    )
    # Use Jev-ranked matches when available, fall back to keyword matches
    diagnosis_node.map_input(
        input_variable="analysis_result",
        expression=(
            "{'matched_issues': flow.jev_assessment.output.jev_ranked_matches, "
            " 'unmatched_errors': flow.analysis.output.unmatched_errors, "
            " 'severity': flow.analysis.output.severity, "
            " 'summary': flow.jev_assessment.output.summary} "
            "if flow.jev_assessment.output.jev_available "
            "else flow.analysis.output"
        )
    )

    # Node 7: Execute remediation
    # Jev's top_match, remediation_safety, and match_confidence are wired in
    # so execute_remediation can enforce the Jev safety gate.
    remediation_node = aflow.tool(
        execute_remediation,
        name="remediation",
        display_name="Execute Remediation"
    )
    remediation_node.map_input(
        input_variable="issue_title",
        expression=(
            "flow.jev_assessment.output.top_match.issue_title "
            "if flow.jev_assessment.output.top_match "
            "else (flow.diagnosis.output.top_match.title if flow.diagnosis.output.top_match else 'No match')"
        )
    )
    remediation_node.map_input(
        input_variable="solution_steps",
        expression=(
            "flow.jev_assessment.output.top_match.solution_steps "
            "if flow.jev_assessment.output.top_match "
            "else (flow.diagnosis.output.top_match.solution_steps if flow.diagnosis.output.top_match else '')"
        )
    )
    remediation_node.map_input(
        input_variable="component",
        expression=(
            "flow.jev_assessment.output.top_match.component "
            "if flow.jev_assessment.output.top_match "
            "else (flow.diagnosis.output.top_match.component if flow.diagnosis.output.top_match else 'general')"
        )
    )
    remediation_node.map_input(
        input_variable="namespace",
        expression="flow.input.namespace"
    )
    remediation_node.map_input(
        input_variable="dry_run",
        expression="flow.input.dry_run"
    )
    # Pass Jev safety fields — execute_remediation uses these to gate execution
    remediation_node.map_input(
        input_variable="remediation_safety",
        expression=(
            "flow.jev_assessment.output.top_match.remediation_safety "
            "if flow.jev_assessment.output.top_match else ''"
        )
    )
    remediation_node.map_input(
        input_variable="jev_match_confidence",
        expression=(
            "flow.jev_assessment.output.top_match.match_confidence "
            "if flow.jev_assessment.output.top_match else 0.0"
        )
    )

    # Define flow sequence
    aflow.sequence(
        START,
        fetch_issues_node,
        cluster_status_node,
        service_logs_node,
        analysis_node,
        jev_node,
        diagnosis_node,
        remediation_node,
        END
    )

    # Map flow outputs
    aflow.map_output(
        output_variable="diagnosis_summary",
        expression="flow.diagnosis.output.diagnosis_summary"
    )
    aflow.map_output(
        output_variable="matched_issues",
        expression="flow.diagnosis.output.matched_issues"
    )
    aflow.map_output(
        output_variable="remediation_result",
        expression="flow.remediation.output"
    )
    aflow.map_output(
        output_variable="cluster_health",
        expression="flow.diagnosis.output.cluster_health"
    )
    aflow.map_output(
        output_variable="recommendations",
        expression="flow.remediation.output.recommendations"
    )

    return aflow

# Made with Bob

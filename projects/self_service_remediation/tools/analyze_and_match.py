"""
Tool for analyzing collected logs and cluster status against known issues.

Matches errors and problems found in the cluster against the known issues
database to identify which documented issue matches the current situation.
"""
import re
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


class MatchedIssue(BaseModel):
    """A known issue that matches the current cluster problems."""
    title: str = Field(description="Title of the matched known issue")
    confidence: float = Field(description="Confidence score 0.0-1.0")
    matching_evidence: List[str] = Field(description="Evidence from logs/cluster that matches")
    problem_description: str = Field(description="The documented problem description")
    solution_steps: str = Field(description="The documented solution steps")
    component: str = Field(description="Affected component")


class AnalysisResult(BaseModel):
    """Result of log/cluster analysis against known issues."""
    matched_issues: List[Dict[str, Any]] = Field(description="Known issues matched to current problems")
    unmatched_errors: List[str] = Field(description="Errors that did not match any known issue")
    severity: str = Field(description="Overall severity: CRITICAL, HIGH, MEDIUM, LOW")
    summary: str = Field(description="Summary of the analysis")


@tool(permission=ToolPermission.READ_ONLY)
def analyze_and_match_issues(
    cluster_status: Dict[str, Any],
    service_logs: Dict[str, Any],
    known_issues: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Analyze cluster status and service logs to match against known issues.

    Correlates errors found in the cluster and logs with the documented known
    issues to determine which problems the cluster is experiencing and what
    solutions apply.

    Args:
        cluster_status: Output from collect_cluster_status tool
        service_logs: Output from collect_service_logs tool
        known_issues: Output from fetch_known_issues tool

    Returns:
        Dictionary containing matched issues with confidence scores,
        unmatched errors, severity assessment, and analysis summary.
    """
    logger = logging.getLogger(__name__)
    logger.info("Analyzing cluster state against known issues...")

    # Collect all error signals from cluster and logs
    error_signals = _extract_error_signals(cluster_status, service_logs)

    # Get known issues list
    issues_list = known_issues.get("issues", [])

    # Match signals against known issues
    matched_issues = []
    matched_signal_indices = set()

    for issue in issues_list:
        match_result = _match_issue_to_signals(issue, error_signals)
        if match_result["confidence"] > 0.3:
            matched_issues.append(match_result)
            matched_signal_indices.update(match_result.get("_signal_indices", []))

    # Sort by confidence descending
    matched_issues.sort(key=lambda x: x["confidence"], reverse=True)

    # Remove internal tracking field
    for m in matched_issues:
        m.pop("_signal_indices", None)

    # Determine unmatched errors
    unmatched_errors = [
        sig["description"]
        for i, sig in enumerate(error_signals)
        if i not in matched_signal_indices
    ]

    # Assess severity
    severity = _assess_severity(matched_issues, unmatched_errors, cluster_status)

    # Generate summary
    summary = _generate_summary(matched_issues, unmatched_errors, severity)

    # jev_enrichment_available signals to the flow that jev_assess_matches should
    # be called next to replace keyword-confidence scores with Jev probabilities
    # and classify remediation safety before execute_remediation runs.
    jev_enrichment_available = len(matched_issues) > 0

    return {
        "matched_issues": matched_issues,
        "unmatched_errors": unmatched_errors[:20],
        "severity": severity,
        "summary": summary,
        "jev_enrichment_available": jev_enrichment_available,
        # Annotate so downstream consumers know these are keyword-based scores
        "confidence_method": "keyword_overlap" if not jev_enrichment_available else "keyword_overlap_pending_jev",
    }


def _extract_error_signals(
    cluster_status: Dict[str, Any],
    service_logs: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Extract all error signals from cluster status and service logs."""
    signals = []

    # From cluster status: unhealthy pods
    for pod in cluster_status.get("unhealthy_pods", []):
        for reason in pod.get("reasons", []):
            signals.append({
                "source": "cluster_pod",
                "description": f"Pod {pod['name']}: {reason}",
                "keywords": _extract_keywords(reason),
                "component": _detect_component_from_pod(pod["name"])
            })

    # From cluster status: node pressure
    for node, pressure in cluster_status.get("resource_pressure", {}).items():
        desc = f"Node {node}: CPU={pressure.get('cpu_percent', 0)}%, Memory={pressure.get('memory_percent', 0)}%"
        signals.append({
            "source": "cluster_node",
            "description": desc,
            "keywords": ["resource", "pressure", "memory", "cpu", "capacity"],
            "component": "openshift-cluster"
        })

    # From cluster status: warning events
    for event in cluster_status.get("recent_events", []):
        signals.append({
            "source": "cluster_event",
            "description": f"{event.get('kind', '')}/{event.get('object', '')}: "
                          f"{event.get('reason', '')} - {event.get('message', '')}",
            "keywords": _extract_keywords(
                f"{event.get('reason', '')} {event.get('message', '')}"
            ),
            "component": _detect_component_from_pod(event.get("object", ""))
        })

    # From service logs: error entries
    for error in service_logs.get("error_logs", []):
        signals.append({
            "source": "service_log",
            "description": f"{error.get('pod_name', '')}: {error.get('message', '')}",
            "keywords": _extract_keywords(error.get("message", "")),
            "component": _detect_component_from_pod(error.get("pod_name", ""))
        })

    return signals


def _match_issue_to_signals(
    issue: Dict[str, Any],
    signals: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Match a known issue against collected error signals."""
    problem_text = issue.get("problem", "").lower()
    title_text = issue.get("title", "").lower()
    issue_component = issue.get("component", "").lower()

    # Extract keywords from the known issue problem description
    issue_keywords = _extract_keywords(f"{title_text} {problem_text}")

    matching_evidence = []
    signal_indices = []
    total_score = 0.0

    for i, signal in enumerate(signals):
        signal_keywords = signal.get("keywords", [])
        signal_desc = signal.get("description", "").lower()
        signal_component = signal.get("component", "").lower()

        # Component match bonus
        component_match = (
            issue_component and signal_component and
            (issue_component in signal_component or signal_component in issue_component)
        )

        # Keyword overlap
        keyword_overlap = set(issue_keywords) & set(signal_keywords)
        overlap_ratio = len(keyword_overlap) / max(len(issue_keywords), 1)

        # Direct text matching
        text_match_score = 0
        for kw in issue_keywords:
            if kw in signal_desc:
                text_match_score += 1

        # Calculate signal match score
        signal_score = 0.0
        if component_match:
            signal_score += 0.3
        signal_score += overlap_ratio * 0.5
        signal_score += min(text_match_score / max(len(issue_keywords), 1), 0.4)

        if signal_score > 0.2:
            matching_evidence.append(signal["description"][:200])
            signal_indices.append(i)
            total_score += signal_score

    # Normalize confidence to 0-1 range
    confidence = min(total_score / max(len(signals) * 0.3, 1), 1.0)

    # Boost confidence if multiple signals match
    if len(matching_evidence) >= 3:
        confidence = min(confidence * 1.3, 1.0)

    return {
        "title": issue.get("title", "Unknown"),
        "confidence": round(confidence, 3),
        "matching_evidence": matching_evidence[:5],
        "problem_description": issue.get("problem", ""),
        "solution_steps": issue.get("solution", ""),
        "component": issue.get("component", "general"),
        "url": issue.get("url", ""),
        "_signal_indices": signal_indices
    }


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from text."""
    # Normalize
    text = text.lower()
    # Remove common noise words
    noise = {
        'the', 'is', 'at', 'which', 'on', 'a', 'an', 'and', 'or', 'but',
        'in', 'with', 'to', 'for', 'of', 'not', 'no', 'from', 'by', 'as',
        'are', 'was', 'were', 'been', 'be', 'have', 'has', 'had', 'do',
        'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
        'that', 'this', 'these', 'those', 'it', 'its', 'can'
    }
    # Extract words
    words = re.findall(r'[a-z][a-z0-9_-]+', text)
    # Filter and return unique keywords
    keywords = [w for w in words if w not in noise and len(w) > 2]
    return list(set(keywords))


def _detect_component_from_pod(pod_name: str) -> str:
    """Detect component from a pod name."""
    pod_lower = pod_name.lower()
    mappings = {
        'redis': 'redis',
        'rabbitmq': 'rabbitmq',
        'elasticsearch': 'elasticsearch',
        'elastic': 'elasticsearch',
        'etcd': 'etcd',
        'minio': 'minio',
        'postgres': 'database',
        'mongodb': 'database',
        'orchestrate': 'watsonx-orchestrate',
        'wxo': 'watsonx-orchestrate',
        'assistant': 'watsonx-assistant',
        'zen': 'zen-service',
        'nginx': 'ingress',
        'usermgmt': 'user-management',
    }
    for keyword, component in mappings.items():
        if keyword in pod_lower:
            return component
    return 'general'


def _assess_severity(
    matched: List[Dict[str, Any]],
    unmatched: List[str],
    cluster_status: Dict[str, Any]
) -> str:
    """Assess overall severity of the detected issues."""
    # Critical if high-confidence matches or many unhealthy pods
    if any(m["confidence"] > 0.7 for m in matched):
        return "CRITICAL"
    if len(cluster_status.get("unhealthy_pods", [])) > 5:
        return "CRITICAL"
    if cluster_status.get("overall_health", "").startswith("CRITICAL"):
        return "CRITICAL"

    if matched and matched[0]["confidence"] > 0.5:
        return "HIGH"
    if len(cluster_status.get("unhealthy_pods", [])) > 2:
        return "HIGH"

    if matched:
        return "MEDIUM"
    if unmatched:
        return "MEDIUM"

    return "LOW"


def _generate_summary(
    matched: List[Dict[str, Any]],
    unmatched: List[str],
    severity: str
) -> str:
    """Generate a human-readable summary of the analysis."""
    lines = [f"## Analysis Summary (Severity: {severity})\n"]

    if matched:
        lines.append(f"**{len(matched)} known issue(s) matched:**\n")
        for i, m in enumerate(matched[:5], 1):
            lines.append(
                f"{i}. **{m['title']}** (confidence: {m['confidence']:.0%})\n"
                f"   Component: {m['component']}\n"
                f"   Problem: {m['problem_description'][:150]}...\n"
            )
    else:
        lines.append("No known issues matched the current cluster state.\n")

    if unmatched:
        lines.append(f"\n**{len(unmatched)} unmatched error(s)** that may require manual investigation.\n")

    if severity in ("CRITICAL", "HIGH"):
        lines.append("\n⚠️ **Immediate action recommended.** Review matched solutions below.\n")

    return "\n".join(lines)

# Made with Bob

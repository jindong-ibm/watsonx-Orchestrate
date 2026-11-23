"""
Tool for collecting Red Hat OpenShift cluster status and information.

Connects to an OpenShift cluster via the oc CLI or Kubernetes API to gather
node status, pod health, resource utilization, and cluster events.
"""
import subprocess
import json
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


class ClusterStatusResult(BaseModel):
    """Result of cluster status collection."""
    cluster_name: str = Field(description="Name of the OpenShift cluster")
    cluster_version: str = Field(description="OpenShift cluster version")
    nodes: List[Dict[str, Any]] = Field(description="Node status information")
    unhealthy_pods: List[Dict[str, Any]] = Field(description="Pods not in Running/Completed state")
    resource_pressure: Dict[str, Any] = Field(description="Resource pressure indicators")
    recent_events: List[Dict[str, Any]] = Field(description="Recent warning/error events")
    overall_health: str = Field(description="Overall cluster health assessment")


@tool(permission=ToolPermission.READ_ONLY)
def collect_cluster_status(namespace: str = "cpd") -> Dict[str, Any]:
    """
    Collect Red Hat OpenShift cluster status and health information.

    Gathers comprehensive cluster status including node health, pod states,
    resource utilization, and recent warning events to identify problems.

    Args:
        namespace: The OpenShift namespace/project to inspect (default: 'cpd' for Cloud Pak for Data)

    Returns:
        Dictionary containing cluster version, node status, unhealthy pods,
        resource pressure indicators, recent events, and overall health assessment.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Collecting cluster status for namespace: {namespace}")

    result = {
        "cluster_name": "",
        "cluster_version": "",
        "nodes": [],
        "unhealthy_pods": [],
        "resource_pressure": {},
        "recent_events": [],
        "overall_health": "UNKNOWN"
    }

    # --- Cluster version ---
    try:
        version_output = _run_oc_command(["oc", "version", "-o", "json"])
        if version_output:
            version_data = json.loads(version_output)
            result["cluster_version"] = version_data.get("openshiftVersion", "unknown")
            result["cluster_name"] = version_data.get("serverVersion", {}).get("platform", "openshift-cluster")
    except Exception as e:
        logger.warning(f"Could not get cluster version: {e}")
        result["cluster_version"] = "unavailable"

    # --- Node status ---
    try:
        nodes_output = _run_oc_command([
            "oc", "get", "nodes", "-o", "json"
        ])
        if nodes_output:
            nodes_data = json.loads(nodes_output)
            for node in nodes_data.get("items", []):
                node_name = node["metadata"]["name"]
                conditions = node.get("status", {}).get("conditions", [])
                ready = "Unknown"
                pressure_issues = []

                for cond in conditions:
                    if cond["type"] == "Ready":
                        ready = "Ready" if cond["status"] == "True" else "NotReady"
                    elif cond["status"] == "True" and cond["type"] in (
                        "MemoryPressure", "DiskPressure", "PIDPressure"
                    ):
                        pressure_issues.append(cond["type"])

                result["nodes"].append({
                    "name": node_name,
                    "status": ready,
                    "pressure_issues": pressure_issues,
                    "roles": _get_node_roles(node)
                })
    except Exception as e:
        logger.warning(f"Could not get node status: {e}")

    # --- Unhealthy pods ---
    try:
        pods_output = _run_oc_command([
            "oc", "get", "pods", "-n", namespace, "-o", "json"
        ])
        if pods_output:
            pods_data = json.loads(pods_output)
            for pod in pods_data.get("items", []):
                pod_name = pod["metadata"]["name"]
                phase = pod.get("status", {}).get("phase", "Unknown")
                container_statuses = pod.get("status", {}).get("containerStatuses", [])

                # Check for non-healthy states
                is_unhealthy = False
                reasons = []

                if phase not in ("Running", "Succeeded", "Completed"):
                    is_unhealthy = True
                    reasons.append(f"Phase: {phase}")

                for cs in container_statuses:
                    if cs.get("state", {}).get("waiting"):
                        waiting = cs["state"]["waiting"]
                        reason = waiting.get("reason", "Unknown")
                        is_unhealthy = True
                        reasons.append(f"Container {cs['name']} waiting: {reason}")
                    if cs.get("restartCount", 0) > 5:
                        is_unhealthy = True
                        reasons.append(
                            f"Container {cs['name']} high restarts: {cs['restartCount']}"
                        )

                if is_unhealthy:
                    result["unhealthy_pods"].append({
                        "name": pod_name,
                        "namespace": namespace,
                        "phase": phase,
                        "reasons": reasons
                    })
    except Exception as e:
        logger.warning(f"Could not get pod status: {e}")

    # --- Resource pressure ---
    try:
        top_output = _run_oc_command(["oc", "adm", "top", "nodes", "--no-headers"])
        if top_output:
            for line in top_output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5:
                    node_name = parts[0]
                    cpu_pct = parts[2].replace('%', '')
                    mem_pct = parts[4].replace('%', '')
                    try:
                        if int(cpu_pct) > 85 or int(mem_pct) > 85:
                            result["resource_pressure"][node_name] = {
                                "cpu_percent": int(cpu_pct),
                                "memory_percent": int(mem_pct)
                            }
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning(f"Could not get resource usage: {e}")

    # --- Recent warning events ---
    try:
        events_output = _run_oc_command([
            "oc", "get", "events", "-n", namespace,
            "--field-selector=type!=Normal",
            "--sort-by=.lastTimestamp",
            "-o", "json"
        ])
        if events_output:
            events_data = json.loads(events_output)
            for event in events_data.get("items", [])[-20:]:  # Last 20 events
                result["recent_events"].append({
                    "type": event.get("type", ""),
                    "reason": event.get("reason", ""),
                    "message": event.get("message", ""),
                    "object": event.get("involvedObject", {}).get("name", ""),
                    "kind": event.get("involvedObject", {}).get("kind", ""),
                    "count": event.get("count", 1),
                    "last_seen": event.get("lastTimestamp", "")
                })
    except Exception as e:
        logger.warning(f"Could not get events: {e}")

    # --- Overall health assessment ---
    result["overall_health"] = _assess_health(result)

    return result


def _run_oc_command(cmd: List[str]) -> str:
    """Run an oc CLI command and return stdout."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if proc.returncode == 0:
            return proc.stdout
        return ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _get_node_roles(node: Dict[str, Any]) -> List[str]:
    """Extract node roles from labels."""
    labels = node.get("metadata", {}).get("labels", {})
    roles = []
    for label in labels:
        if label.startswith("node-role.kubernetes.io/"):
            role = label.split("/")[-1]
            if role:
                roles.append(role)
    return roles or ["worker"]


def _assess_health(status: Dict[str, Any]) -> str:
    """Assess overall cluster health from collected data."""
    issues = 0

    # Check nodes
    for node in status["nodes"]:
        if node["status"] != "Ready":
            issues += 3
        if node["pressure_issues"]:
            issues += 2

    # Check pods
    issues += len(status["unhealthy_pods"])

    # Check resource pressure
    issues += len(status["resource_pressure"]) * 2

    # Check events
    critical_events = [e for e in status["recent_events"] if e.get("type") == "Warning"]
    issues += len(critical_events)

    if issues == 0:
        return "HEALTHY"
    elif issues <= 3:
        return "DEGRADED - Minor issues detected"
    elif issues <= 8:
        return "WARNING - Multiple issues detected"
    else:
        return "CRITICAL - Significant problems detected"

# Made with Bob

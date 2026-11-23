"""
Tool for collecting watsonx Orchestrate service logs from an OpenShift cluster.

Retrieves pod logs for watsonx Orchestrate services, focusing on error and
warning messages that indicate problems requiring remediation.
"""
import subprocess
import json
import re
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


class ServiceLog(BaseModel):
    """A collected service log entry."""
    pod_name: str = Field(description="Name of the pod")
    container: str = Field(description="Container name")
    log_level: str = Field(description="Log level (ERROR, WARN, etc.)")
    message: str = Field(description="Log message content")
    timestamp: str = Field(default="", description="Timestamp of the log entry")


class ServiceLogsResult(BaseModel):
    """Result of service log collection."""
    namespace: str = Field(description="Namespace logs were collected from")
    services_checked: List[str] = Field(description="List of services whose logs were checked")
    error_logs: List[Dict[str, Any]] = Field(description="Error-level log entries")
    warning_logs: List[Dict[str, Any]] = Field(description="Warning-level log entries")
    total_errors: int = Field(description="Total number of error entries found")
    total_warnings: int = Field(description="Total number of warning entries found")


@tool(permission=ToolPermission.READ_ONLY)
def collect_service_logs(
    namespace: str = "cpd",
    since_minutes: int = 60,
    service_filter: str = ""
) -> Dict[str, Any]:
    """
    Collect watsonx Orchestrate service logs from OpenShift cluster pods.

    Retrieves recent logs from watsonx Orchestrate service pods, filtering for
    ERROR and WARNING level messages that indicate problems.

    Args:
        namespace: OpenShift namespace where watsonx Orchestrate is deployed (default: 'cpd')
        since_minutes: How far back to collect logs in minutes (default: 60)
        service_filter: Optional filter to limit log collection to specific services (e.g., 'orchestrate', 'redis')

    Returns:
        Dictionary containing namespace, services checked, error and warning logs,
        and total counts.
    """
    logger = logging.getLogger(__name__)
    logger.info(
        f"Collecting service logs from namespace={namespace}, "
        f"since={since_minutes}m, filter={service_filter or 'all'}"
    )

    result = {
        "namespace": namespace,
        "services_checked": [],
        "error_logs": [],
        "warning_logs": [],
        "total_errors": 0,
        "total_warnings": 0
    }

    # Get list of pods in the namespace
    try:
        pods_output = _run_oc(
            ["oc", "get", "pods", "-n", namespace, "-o", "json"]
        )
        if not pods_output:
            logger.error("No pods output returned")
            return result

        pods_data = json.loads(pods_output)
        pods = pods_data.get("items", [])

    except Exception as e:
        logger.error(f"Failed to list pods: {e}")
        return result

    # Filter pods related to watsonx Orchestrate services
    wxo_service_prefixes = [
        "watsonx-orchestrate",
        "wxo-",
        "wo-",
        "assistant-",
        "wa-",
        "redis",
        "rabbitmq",
        "elasticsearch",
        "etcd",
        "minio",
        "postgres",
        "zen-",
        "ibm-nginx",
        "usermgmt",
    ]

    for pod in pods:
        pod_name = pod["metadata"]["name"]
        phase = pod.get("status", {}).get("phase", "")

        # Only check running or recently failed pods
        if phase not in ("Running", "Failed", "CrashLoopBackOff", "Error"):
            continue

        # Filter by service if specified
        if service_filter:
            if service_filter.lower() not in pod_name.lower():
                continue
        else:
            # Apply default watsonx Orchestrate service filter
            if not any(pod_name.startswith(prefix) or prefix in pod_name
                       for prefix in wxo_service_prefixes):
                continue

        containers = [
            cs["name"]
            for cs in pod.get("status", {}).get("containerStatuses", [])
        ]
        if not containers:
            containers = [
                c["name"]
                for c in pod.get("spec", {}).get("containers", [])
            ]

        for container in containers:
            result["services_checked"].append(f"{pod_name}/{container}")

            try:
                log_output = _run_oc([
                    "oc", "logs", pod_name,
                    "-c", container,
                    "-n", namespace,
                    f"--since={since_minutes}m",
                    "--tail=500"
                ])

                if log_output:
                    errors, warnings = _parse_log_entries(
                        log_output, pod_name, container
                    )
                    result["error_logs"].extend(errors)
                    result["warning_logs"].extend(warnings)

            except Exception as e:
                logger.warning(f"Could not get logs for {pod_name}/{container}: {e}")
                continue

    result["total_errors"] = len(result["error_logs"])
    result["total_warnings"] = len(result["warning_logs"])

    # Limit output to most recent entries
    result["error_logs"] = result["error_logs"][-50:]
    result["warning_logs"] = result["warning_logs"][-30:]

    return result


def _run_oc(cmd: List[str]) -> str:
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


def _parse_log_entries(
    log_text: str, pod_name: str, container: str
) -> tuple:
    """
    Parse log text for ERROR and WARNING entries.

    Returns:
        Tuple of (error_entries, warning_entries)
    """
    errors = []
    warnings = []

    # Common log patterns
    error_patterns = [
        re.compile(r'.*\b(ERROR|FATAL|CRITICAL)\b.*', re.IGNORECASE),
        re.compile(r'.*\b(Exception|Traceback|panic|SIGSEGV)\b.*', re.IGNORECASE),
        re.compile(r'.*\b(OOMKilled|CrashLoopBackOff|ImagePullBackOff)\b.*', re.IGNORECASE),
        re.compile(r'.*\b(connection refused|timeout|deadline exceeded)\b.*', re.IGNORECASE),
    ]

    warning_patterns = [
        re.compile(r'.*\b(WARN|WARNING)\b.*', re.IGNORECASE),
        re.compile(r'.*\b(deprecated|retry|backoff)\b.*', re.IGNORECASE),
    ]

    # Timestamp extraction pattern
    ts_pattern = re.compile(
        r'^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*)'
    )

    for line in log_text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Extract timestamp
        ts_match = ts_pattern.match(line)
        timestamp = ts_match.group(1) if ts_match else ""

        # Check for errors
        is_error = any(p.match(line) for p in error_patterns)
        if is_error:
            errors.append({
                "pod_name": pod_name,
                "container": container,
                "log_level": "ERROR",
                "message": line[:500],
                "timestamp": timestamp
            })
            continue

        # Check for warnings
        is_warning = any(p.match(line) for p in warning_patterns)
        if is_warning:
            warnings.append({
                "pod_name": pod_name,
                "container": container,
                "log_level": "WARNING",
                "message": line[:300],
                "timestamp": timestamp
            })

    return errors, warnings

# Made with Bob

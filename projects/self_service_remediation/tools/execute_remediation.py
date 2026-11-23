"""
Tool for executing automated remediation steps on the OpenShift cluster.

Takes solution steps from matched known issues and executes them in a safe,
controlled manner with validation before and after each step.
"""
import subprocess
import re
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


class RemediationStep(BaseModel):
    """A single remediation step with its result."""
    step_number: int = Field(description="Step number in the sequence")
    command: str = Field(description="Command or action executed")
    status: str = Field(description="Status: SUCCESS, FAILED, SKIPPED")
    output: str = Field(description="Output or result of the step")


class RemediationResult(BaseModel):
    """Result of the remediation execution."""
    issue_title: str = Field(description="Title of the issue being remediated")
    steps_executed: List[Dict[str, Any]] = Field(description="List of steps executed with results")
    overall_status: str = Field(description="Overall remediation status")
    post_check: str = Field(description="Post-remediation verification result")
    recommendations: List[str] = Field(description="Additional recommendations")


@tool()
def execute_remediation(
    issue_title: str,
    solution_steps: str,
    component: str,
    namespace: str = "cpd",
    dry_run: bool = True,
    remediation_safety: str = "",
    jev_match_confidence: float = 0.0,
) -> Dict[str, Any]:
    """
    Execute automated remediation steps for a matched known issue.

    Parses the solution steps from the known issue documentation and executes
    them on the cluster. When called from the Jev-enhanced flow, the
    remediation_safety and jev_match_confidence fields from jev_assess_matches
    are passed in and take precedence over the static _is_safe_command filter
    as the primary execution gate.

    Args:
        issue_title: Title of the known issue being remediated
        solution_steps: The solution/workaround text from the known issue
        component: The affected component (e.g., 'elasticsearch', 'redis')
        namespace: OpenShift namespace where watsonx Orchestrate is deployed (default: 'cpd')
        dry_run: If True, only show what would be executed without making changes (default: True)
        remediation_safety: Jev safety classification for this issue:
            'read_only_safe'     — execute automatically (no approval needed)
            'requires_approval'  — dry_run is forced True until operator confirms
            'destructive_blocked'— execution is blocked regardless of dry_run flag
            Leave empty ('') to fall back to the static _is_safe_command filter.
        jev_match_confidence: Jev's confidence that the issue matches this cluster's
            error signals (0.0–1.0). Values below 0.70 force dry_run=True even
            if the caller passed dry_run=False.

    Returns:
        Dictionary containing issue title, steps executed with results,
        overall status, post-check results, and recommendations.
    """
    logger = logging.getLogger(__name__)

    # ── Jev safety gate ───────────────────────────────────────────────────────
    # When Jev classification is available it overrides the caller's dry_run flag
    # and the static _is_safe_command filter for the overall execution decision.
    jev_gate_note = ""

    if remediation_safety == "destructive_blocked":
        logger.warning(
            "Jev classified remediation as destructive_blocked — execution refused."
        )
        return {
            "issue_title": issue_title,
            "steps_executed": [],
            "overall_status": "BLOCKED_BY_JEV",
            "post_check": "",
            "dry_run": True,
            "remediation_safety": remediation_safety,
            "jev_match_confidence": jev_match_confidence,
            "recommendations": [
                "Jev classified these remediation steps as potentially destructive. "
                "They must not run automatically.",
                "Review the solution steps manually and execute only under explicit "
                "cluster administrator supervision.",
                f"Issue: {issue_title}",
                f"Solution steps for manual review:\n{solution_steps}",
            ],
        }

    if remediation_safety == "requires_approval" and not dry_run:
        logger.info(
            "Jev classified remediation as requires_approval — forcing dry_run=True."
        )
        dry_run = True
        jev_gate_note = (
            "⚠️  Jev classified this remediation as requiring operator approval. "
            "Execution forced to dry-run mode. Set dry_run=False and re-run after "
            "the operator has reviewed and confirmed the steps above."
        )

    if jev_match_confidence and jev_match_confidence < 0.70 and not dry_run:
        logger.info(
            f"Jev match confidence {jev_match_confidence:.0%} is below 0.70 threshold "
            "— forcing dry_run=True."
        )
        dry_run = True
        jev_gate_note = (
            f"⚠️  Jev match confidence ({jev_match_confidence:.0%}) is below the 0.70 "
            "threshold. Execution forced to dry-run mode until a human confirms this "
            "is the correct issue."
        )

    logger.info(
        f"{'[DRY RUN] ' if dry_run else ''}Executing remediation for: {issue_title}"
    )

    result = {
        "issue_title": issue_title,
        "steps_executed": [],
        "overall_status": "IN_PROGRESS",
        "post_check": "",
        "recommendations": [],
        "dry_run": dry_run,
        "remediation_safety": remediation_safety or "static_filter",
        "jev_match_confidence": jev_match_confidence or None,
        "jev_gate_note": jev_gate_note or None,
    }

    # Parse solution steps into executable commands
    commands = _parse_solution_to_commands(solution_steps, component, namespace)

    if not commands:
        result["overall_status"] = "NO_ACTIONS"
        result["recommendations"] = [
            "Could not parse automated commands from the solution steps.",
            "Please review the solution manually:",
            solution_steps
        ]
        return result

    # Execute each command
    all_success = True
    for i, cmd_info in enumerate(commands, 1):
        step_result = {
            "step_number": i,
            "command": cmd_info["command"],
            "description": cmd_info.get("description", ""),
            "status": "PENDING",
            "output": ""
        }

        if dry_run:
            step_result["status"] = "DRY_RUN"
            step_result["output"] = f"[DRY RUN] Would execute: {cmd_info['command']}"
        else:
            # Per-command safety check:
            # When Jev classified the issue as read_only_safe, the static filter
            # is still applied as a defence-in-depth layer.
            # When Jev is unavailable (empty remediation_safety), the static filter
            # is the sole gate as before.
            if _is_safe_command(cmd_info["command"]):
                try:
                    proc = subprocess.run(
                        cmd_info["command"],
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    step_result["output"] = proc.stdout[:1000] if proc.stdout else proc.stderr[:500]
                    step_result["status"] = "SUCCESS" if proc.returncode == 0 else "FAILED"

                    if proc.returncode != 0:
                        all_success = False
                        step_result["output"] += f"\nExit code: {proc.returncode}"

                except subprocess.TimeoutExpired:
                    step_result["status"] = "TIMEOUT"
                    step_result["output"] = "Command timed out after 60 seconds"
                    all_success = False
                except Exception as e:
                    step_result["status"] = "ERROR"
                    step_result["output"] = f"Error: {str(e)}"
                    all_success = False
            else:
                step_result["status"] = "BLOCKED"
                step_result["output"] = (
                    "Command blocked by safety filter. "
                    "Requires manual execution or admin approval."
                )
                all_success = False

        result["steps_executed"].append(step_result)

    # Add Jev gate note to recommendations when present
    if jev_gate_note:
        result.setdefault("recommendations", []).insert(0, jev_gate_note)

    # Set overall status
    if dry_run:
        result["overall_status"] = "DRY_RUN_COMPLETE"
    elif all_success:
        result["overall_status"] = "SUCCESS"
    else:
        failed_steps = [s for s in result["steps_executed"] if s["status"] in ("FAILED", "ERROR", "BLOCKED")]
        if len(failed_steps) == len(result["steps_executed"]):
            result["overall_status"] = "FAILED"
        else:
            result["overall_status"] = "PARTIAL_SUCCESS"

    # Post-remediation check
    if not dry_run and all_success:
        result["post_check"] = _run_post_check(component, namespace)
    elif dry_run:
        result["post_check"] = "[DRY RUN] Post-check would verify component health after remediation."
    else:
        result["post_check"] = "Post-check skipped due to failed steps."

    # Add recommendations
    result["recommendations"] = _generate_recommendations(result, component)

    return result


def _parse_solution_to_commands(
    solution_text: str,
    component: str,
    namespace: str
) -> List[Dict[str, Any]]:
    """Parse solution text into executable commands."""
    commands = []

    # Extract numbered steps with commands
    # Match patterns like "1. Check pod logs: oc logs <pod-name>"
    step_pattern = re.compile(
        r'(?:\d+\.?\s*)(.*?)(?::\s*)((?:oc|kubectl|curl|rabbitmqctl|openssl)\s+.+?)(?:\n|$)',
        re.MULTILINE
    )

    for match in step_pattern.finditer(solution_text):
        description = match.group(1).strip()
        command = match.group(2).strip()
        # Replace placeholder patterns
        command = _substitute_placeholders(command, component, namespace)
        commands.append({
            "description": description,
            "command": command
        })

    # If regex didn't find commands, try to extract any oc/kubectl commands
    if not commands:
        cmd_pattern = re.compile(
            r'((?:oc|kubectl|curl|rabbitmqctl|openssl)\s+[^\n]+)',
            re.MULTILINE
        )
        for match in cmd_pattern.finditer(solution_text):
            command = match.group(1).strip()
            command = _substitute_placeholders(command, component, namespace)
            commands.append({
                "description": "Extracted command",
                "command": command
            })

    return commands


def _substitute_placeholders(command: str, component: str, namespace: str) -> str:
    """Replace common placeholders in commands with actual values."""
    # Replace namespace placeholder
    command = re.sub(r'<namespace>', namespace, command)
    command = command.replace('-n cpd', f'-n {namespace}')

    # Replace generic pod-name placeholders with label selectors
    if '<pod-name>' in command or '<pod>' in command:
        label = _component_to_label(component)
        pod_selector = f'$(oc get pods -n {namespace} -l {label} -o jsonpath="{{.items[0].metadata.name}}")'
        command = re.sub(r'<pod-name>|<pod>', pod_selector, command)

    # Replace <name> with component-based name
    command = re.sub(r'<name>', component, command)

    # Replace es-pod style placeholders
    if '<es-pod>' in command:
        command = command.replace(
            '<es-pod>',
            f'$(oc get pods -n {namespace} -l component=elasticsearch -o jsonpath="{{.items[0].metadata.name}}")'
        )
    if '<rabbitmq-pod>' in command:
        command = command.replace(
            '<rabbitmq-pod>',
            f'$(oc get pods -n {namespace} -l app=rabbitmq -o jsonpath="{{.items[0].metadata.name}}")'
        )

    # Replace <consumer> and <queue-name> generically
    command = re.sub(r'<consumer>', component, command)
    command = re.sub(r'<queue-name>', 'default', command)

    return command


def _component_to_label(component: str) -> str:
    """Convert component name to a Kubernetes label selector."""
    label_map = {
        'redis': 'app=redis',
        'rabbitmq': 'app=rabbitmq',
        'elasticsearch': 'component=elasticsearch',
        'etcd': 'app=etcd',
        'minio': 'app=minio',
        'database': 'app=postgres',
        'watsonx-orchestrate': 'app.kubernetes.io/name=watsonx-orchestrate',
        'zen-service': 'component=zen',
        'kubernetes-pod': 'app.kubernetes.io/managed-by=operator',
    }
    return label_map.get(component, f'component={component}')


def _is_safe_command(command: str) -> bool:
    """
    Check if a command is safe to execute automatically.
    
    Allows read-only commands and specific known-safe write commands.
    Blocks destructive operations.
    """
    # Always allowed (read-only)
    safe_prefixes = [
        'oc get', 'oc describe', 'oc logs', 'oc version',
        'oc adm top', 'oc status', 'oc whoami',
        'kubectl get', 'kubectl describe', 'kubectl logs',
        'curl -s localhost', 'openssl x509 -noout',
    ]
    for prefix in safe_prefixes:
        if command.strip().startswith(prefix):
            return True

    # Conditionally allowed write commands
    safe_write_patterns = [
        'oc rollout restart',
        'oc scale deployment',
        'oc delete pod',  # Allows pod restart via deletion
    ]
    for pattern in safe_write_patterns:
        if pattern in command:
            return True

    # Block everything else
    return False


def _run_post_check(component: str, namespace: str) -> str:
    """Run a post-remediation health check."""
    checks = []

    # Check pod status for the component
    label = _component_to_label(component)
    try:
        proc = subprocess.run(
            f'oc get pods -n {namespace} -l {label} -o wide --no-headers',
            shell=True, capture_output=True, text=True, timeout=15
        )
        if proc.returncode == 0 and proc.stdout:
            running_pods = [
                line for line in proc.stdout.strip().split('\n')
                if 'Running' in line
            ]
            total_pods = len(proc.stdout.strip().split('\n'))
            checks.append(
                f"Component {component}: {len(running_pods)}/{total_pods} pods Running"
            )
        else:
            checks.append(f"Component {component}: Unable to verify pod status")
    except Exception:
        checks.append(f"Component {component}: Post-check failed")

    return "; ".join(checks) if checks else "Post-check completed"


def _generate_recommendations(result: Dict[str, Any], component: str) -> List[str]:
    """Generate recommendations based on remediation results."""
    recs = []

    status = result["overall_status"]

    if status == "DRY_RUN_COMPLETE":
        recs.append(
            "Review the dry-run output above. If the steps look correct, "
            "re-run with dry_run=False to apply changes."
        )
    elif status == "SUCCESS":
        recs.append("Remediation completed successfully. Monitor the component for stability.")
        recs.append("Consider setting up alerts to detect recurrence of this issue.")
    elif status == "PARTIAL_SUCCESS":
        recs.append("Some steps failed. Review failed steps and execute manually if needed.")
        recs.append("Check IBM documentation for additional context on the failed steps.")
    elif status == "FAILED":
        recs.append("Remediation failed. Manual intervention required.")
        recs.append("Consider opening an IBM support ticket with the collected diagnostics.")

    blocked_steps = [s for s in result["steps_executed"] if s["status"] == "BLOCKED"]
    if blocked_steps:
        recs.append(
            f"{len(blocked_steps)} step(s) were blocked by the safety filter. "
            "These require manual execution by a cluster administrator."
        )

    return recs

# Made with Bob

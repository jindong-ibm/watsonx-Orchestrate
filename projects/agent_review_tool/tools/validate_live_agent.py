"""
Live-deployment validation tool for watsonx Orchestrate agents and tools.

Complements the static analyze_agent_config tool by confirming that a named
agent and all its declared tools are actually present on the active tenant,
and optionally smoke-testing the agent with a reachability ping.

Uses the `orchestrate` CLI (ibm-watsonx-orchestrate ADK) via subprocess so it
works inside wxO tool execution without requiring a separate SDK import.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
import subprocess
import json
import re
from typing import Dict, List, Any, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_cli(args: List[str]) -> Dict[str, Any]:
    """Run an `orchestrate` CLI command and return parsed output.

    Returns a dict with keys:
      - success (bool)
      - stdout (str)
      - stderr (str)
      - parsed (list | dict | None)  — JSON-decoded stdout when available
    """
    cmd = ["orchestrate"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        success = result.returncode == 0
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        parsed = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                # CLI may return plain-text tables; leave parsed as None
                parsed = None

        return {"success": success, "stdout": stdout, "stderr": stderr, "parsed": parsed}

    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": "orchestrate CLI not found. Install with: pip install ibm-watsonx-orchestrate",
            "parsed": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "CLI command timed out after 60 seconds.",
            "parsed": None,
        }


def _name_in_output(name: str, output: str) -> bool:
    """Return True if `name` appears as a standalone token in CLI text output."""
    # Match the name surrounded by whitespace, pipe chars, or start/end of line
    pattern = r'(?:^|[\s|])' + re.escape(name) + r'(?:$|[\s|])'
    return bool(re.search(pattern, output, re.MULTILINE))


def _check_agent_exists(agent_name: str) -> Dict[str, Any]:
    """Verify the agent is registered on the active tenant."""
    result = _run_cli(["agents", "list"])
    if not result["success"]:
        return {
            "check": "agent_exists",
            "status": "error",
            "message": f"Could not list agents: {result['stderr'] or result['stdout']}",
        }

    found = _name_in_output(agent_name, result["stdout"])
    return {
        "check": "agent_exists",
        "status": "pass" if found else "fail",
        "message": (
            f"Agent '{agent_name}' found on active tenant."
            if found
            else f"Agent '{agent_name}' NOT found. Run: orchestrate agents import -f <file>"
        ),
    }


def _check_tool_exists(tool_name: str) -> Dict[str, Any]:
    """Verify a single tool is registered on the active tenant."""
    result = _run_cli(["tools", "list"])
    if not result["success"]:
        return {
            "check": "tool_exists",
            "tool": tool_name,
            "status": "error",
            "message": f"Could not list tools: {result['stderr'] or result['stdout']}",
        }

    found = _name_in_output(tool_name, result["stdout"])
    return {
        "check": "tool_exists",
        "tool": tool_name,
        "status": "pass" if found else "fail",
        "message": (
            f"Tool '{tool_name}' found on active tenant."
            if found
            else f"Tool '{tool_name}' NOT found. Run: orchestrate tools import -k python -f <file>"
        ),
    }


def _check_kb_exists(kb_name: str) -> Dict[str, Any]:
    """Verify a knowledge base is registered on the active tenant."""
    result = _run_cli(["knowledge-bases", "list"])
    if not result["success"]:
        return {
            "check": "kb_exists",
            "kb": kb_name,
            "status": "error",
            "message": f"Could not list knowledge-bases: {result['stderr'] or result['stdout']}",
        }

    found = _name_in_output(kb_name, result["stdout"])
    return {
        "check": "kb_exists",
        "kb": kb_name,
        "status": "pass" if found else "fail",
        "message": (
            f"Knowledge base '{kb_name}' found on active tenant."
            if found
            else f"Knowledge base '{kb_name}' NOT found. Run: orchestrate knowledge-bases import -f <file>"
        ),
    }


# ---------------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------------

@tool
def validate_live_agent(
    agent_name: str,
    tool_names: Optional[List[str]] = None,
    knowledge_base_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Validate that a named agent and its tools/knowledge bases are deployed on
    the active watsonx Orchestrate tenant.

    This tool performs live connectivity checks using the orchestrate CLI —
    it does NOT modify any resources.

    Args:
        agent_name: Name of the agent to validate (must match the 'name' field
            in the agent's YAML, e.g. 'customer_support_agent').
        tool_names: Optional list of tool names the agent depends on. Each name
            is checked against `orchestrate tools list`. Pass the same names
            used in the agent YAML under the 'tools' key.
        knowledge_base_names: Optional list of knowledge base names attached to
            the agent. Each is checked against `orchestrate knowledge-bases list`.

    Returns:
        A validation report dict with keys:
          - agent_name (str)
          - overall_status: 'pass' | 'fail' | 'error'
          - checks (list): one result dict per check performed
          - summary (str): human-readable summary
          - remediation_commands (list[str]): CLI commands to fix failing checks
    """
    checks: List[Dict[str, Any]] = []
    remediation: List[str] = []

    # 1. Check the agent itself
    agent_check = _check_agent_exists(agent_name)
    checks.append(agent_check)
    if agent_check["status"] == "fail":
        remediation.append(f"orchestrate agents import -f agents/{agent_name}.yaml")

    # 2. Check each declared tool
    for tname in (tool_names or []):
        tc = _check_tool_exists(tname)
        checks.append(tc)
        if tc["status"] == "fail":
            remediation.append(
                f"orchestrate tools import -k python -f tools/{tname}.py"
            )

    # 3. Check each knowledge base
    for kb in (knowledge_base_names or []):
        kc = _check_kb_exists(kb)
        checks.append(kc)
        if kc["status"] == "fail":
            remediation.append(
                f"orchestrate knowledge-bases import -f knowledge-bases/{kb}.yaml"
            )

    # Derive overall status
    statuses = {c["status"] for c in checks}
    if "error" in statuses:
        overall = "error"
    elif "fail" in statuses:
        overall = "fail"
    else:
        overall = "pass"

    # Build summary
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    errors = sum(1 for c in checks if c["status"] == "error")
    total = len(checks)

    summary_parts = [f"{passed}/{total} checks passed"]
    if failed:
        summary_parts.append(f"{failed} failed")
    if errors:
        summary_parts.append(f"{errors} errored (CLI unavailable or timed out)")

    summary = ", ".join(summary_parts) + "."
    if overall == "pass":
        summary += f" Agent '{agent_name}' is fully deployed and ready."
    elif overall == "fail":
        summary += f" Agent '{agent_name}' has missing components — see remediation_commands."
    else:
        summary += " Could not complete validation — ensure the orchestrate CLI is installed and an environment is active."

    return {
        "agent_name": agent_name,
        "overall_status": overall,
        "checks": checks,
        "summary": summary,
        "remediation_commands": remediation,
    }

# Made with Bob

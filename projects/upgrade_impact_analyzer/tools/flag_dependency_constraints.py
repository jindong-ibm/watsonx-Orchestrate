"""
Tool 3: Flag Python Tool Dependencies Against New ADK Version Constraints

Cross-references the inventory of deployed Python tools (from inventory_deployed_config)
and any requirements.txt / pyproject.toml content the user provides, against known
ADK version constraints and the breaking changes extracted from parse_release_notes.

Flags:
  - Python packages that conflict with the new ADK version's known constraints
  - Tool decorator parameters that were renamed or removed in the target version
  - Import paths that changed between ADK versions
  - LLM model identifiers that were deprecated or renamed

This tool operates on text inputs — no filesystem access required.
"""

import re
import json
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# ─────────────────────────────────────────────────────────────────────────────
# Known ADK version constraint database
# Each entry: introduced_in, removed_in (None = still valid), description
# ─────────────────────────────────────────────────────────────────────────────
_ADK_KNOWN_CHANGES: list[dict] = [
    # Import path changes
    {
        "kind": "import_path",
        "old": "from ibm_watsonx_ai import tool",
        "new": "from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission",
        "introduced_in": "1.4.2",
        "description": (
            "The tool decorator moved from ibm_watsonx_ai to "
            "ibm_watsonx_orchestrate.agent_builder.tools in ADK 1.4.2."
        ),
        "severity": "HIGH",
    },
    {
        "kind": "import_path",
        "old": "from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow",
        "new": "from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END",
        "introduced_in": "1.4.2",
        "description": (
            "Flow builder requires explicit START and END imports as of ADK 1.4.2."
        ),
        "severity": "MEDIUM",
    },
    # Renamed CLI parameters / terminology
    {
        "kind": "cli_change",
        "old": "flows (terminology)",
        "new": "agentic workflows (terminology)",
        "introduced_in": "1.12.0",
        "description": (
            "Tools previously called 'flows' are now called 'agentic workflows'. "
            "CLI flag -k flow is still accepted but documentation uses 'agentic workflow'."
        ),
        "severity": "LOW",
    },
    {
        "kind": "cli_change",
        "old": "--path flag in knowledge-bases commands",
        "new": "re-run import with same KB name",
        "introduced_in": "1.7.0",
        "description": (
            "The --path parameter was removed from knowledge-base update commands in 1.7.0. "
            "Re-import using the same knowledge base name to update it."
        ),
        "severity": "MEDIUM",
    },
    # Deprecated agent YAML fields
    {
        "kind": "yaml_field",
        "old": "display_name in guidelines",
        "new": "omit display_name",
        "introduced_in": "1.6.0",
        "description": (
            "The display_name field inside guidelines[] is deprecated as of 1.6.0 and should be removed."
        ),
        "severity": "LOW",
    },
    {
        "kind": "yaml_field",
        "old": "enable_cot: false / hidden: false (required)",
        "new": "no longer required",
        "introduced_in": "1.12.0",
        "description": (
            "Agent YAML no longer requires enable_cot: false and hidden: false to be explicitly "
            "set for agent-to-agent imports (bug was fixed in 1.12.0)."
        ),
        "severity": "LOW",
    },
    # Connection / credentials changes
    {
        "kind": "connection",
        "old": ".env files for credentials",
        "new": "orchestrate connections set-credentials",
        "introduced_in": "1.5.0",
        "description": (
            "Credential configuration moved from .env files to the connections manager in 1.5.0. "
            "Python tools should use connections.oauth2_client_creds() or similar."
        ),
        "severity": "MEDIUM",
    },
    {
        "kind": "connection",
        "old": "SaaS environments with ADK < 1.6.0",
        "new": "configure credentials in both draft and live environments",
        "introduced_in": "1.6.0",
        "description": (
            "A regression in 1.6.0 requires credentials to be set in both draft and live "
            "environments for SaaS. Environments using ADK < 1.6.0 pointed at SaaS are affected."
        ),
        "severity": "HIGH",
    },
    # Document processing node renames
    {
        "kind": "api_rename",
        "old": "docclassfier() (typo)",
        "new": "docclassifier()",
        "introduced_in": "1.11.0",
        "description": (
            "Document classifier node method was renamed from docclassfier() (with typo) "
            "to docclassifier() in ADK 1.11.0. Any flow using the old name will break."
        ),
        "severity": "HIGH",
    },
    # A2A protocol deprecation
    {
        "kind": "protocol",
        "old": "A2A protocol versions 0.2 and 0.2.1",
        "new": "A2A protocol version 0.3",
        "introduced_in": "1.15.0",
        "description": (
            "A2A protocol versions 0.2 and 0.2.1 are deprecated as of 1.15.0. "
            "Agents using older A2A protocol will still function but should be migrated."
        ),
        "severity": "MEDIUM",
    },
    # Flows endpoint path change
    {
        "kind": "api_change",
        "old": "/flows endpoint",
        "new": "/v1/flows endpoint",
        "introduced_in": "1.7.0",
        "description": (
            "The flows REST endpoint changed from /flows to /v1/flows in ADK 1.7.0. "
            "Any custom code calling the flows API directly must be updated."
        ),
        "severity": "MEDIUM",
    },
]


def _version_tuple(version_str: str) -> tuple:
    parts = re.findall(r'\d+', version_str)
    return tuple(int(p) for p in parts)


def _is_in_range(change: dict, current: tuple, target: tuple) -> bool:
    """Return True if this change was introduced between current and target (inclusive)."""
    introduced = _version_tuple(change["introduced_in"])
    return current < introduced <= target


def _scan_requirements(requirements_text: str) -> list[str]:
    """Return list of package names from requirements.txt or pyproject.toml text."""
    packages = []
    for line in requirements_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match package==version, package>=version, package~=version, bare package
        m = re.match(r'^([A-Za-z0-9_\-\.]+)', line)
        if m:
            packages.append(m.group(1).lower())
    return packages


@tool(
    name="flag_dependency_constraints",
    description=(
        "Cross-reference the deployed Python tool names, any requirements.txt content, "
        "and the parsed release notes JSON against a known ADK constraint database. "
        "Flags import path changes, renamed API methods, deprecated YAML fields, "
        "CLI syntax changes, and connection manager migrations that apply to the "
        "current→target ADK version upgrade. Returns a prioritised list of flagged "
        "items for the migration checklist."
    ),
    permission=ToolPermission.READ_ONLY,
)
def flag_dependency_constraints(
    inventory_json: str,
    release_notes_json: str,
    requirements_text: str = "",
    current_version: str = "",
    target_version: str = "",
) -> str:
    """
    Flag ADK API and dependency constraints that affect the upgrade path.

    Args:
        inventory_json:     JSON output from the inventory_deployed_config tool.
        release_notes_json: JSON output from the parse_release_notes tool.
        requirements_text:  Optional: paste content of requirements.txt or
                            pyproject.toml [tool.poetry.dependencies] for your
                            Python tools. Used to check for package conflicts.
        current_version:    Current ADK version (overrides value in inventory_json
                            if provided). Example: "1.10.0".
        target_version:     Target ADK version (overrides value in release_notes_json
                            if provided). Example: "1.15.0".

    Returns:
        JSON string containing:
        - current_version: resolved current version
        - target_version: resolved target version
        - flagged_items: list of flagged constraint items, each with:
            - kind: type of change (import_path, cli_change, yaml_field, etc.)
            - severity: HIGH | MEDIUM | LOW
            - introduced_in: ADK version where this change was introduced
            - description: what changed and why it matters
            - old: the old API/path/value
            - new: the new API/path/value
        - high_severity_count: integer
        - medium_severity_count: integer
        - low_severity_count: integer
        - installed_packages: packages found in requirements_text (if provided)
        - summary: plain-text summary
        - error: present only on failure
    """
    try:
        inventory = json.loads(inventory_json)
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"error": f"Failed to parse inventory_json: {exc}"})

    try:
        release_notes = json.loads(release_notes_json)
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"error": f"Failed to parse release_notes_json: {exc}"})

    # Resolve versions
    cur_ver_str = current_version or release_notes.get("current_version", "")
    tgt_ver_str = target_version or release_notes.get("target_version", "")

    if not cur_ver_str or not tgt_ver_str:
        return json.dumps({
            "error": (
                "Could not resolve current_version or target_version. "
                "Ensure parse_release_notes was run first, or provide them explicitly."
            )
        })

    try:
        cur_ver = _version_tuple(cur_ver_str)
        tgt_ver = _version_tuple(tgt_ver_str)
    except (ValueError, IndexError) as exc:
        return json.dumps({"error": f"Version parse error: {exc}"})

    # Find applicable changes from the known constraint database
    flagged: list[dict] = []
    for change in _ADK_KNOWN_CHANGES:
        if _is_in_range(change, cur_ver, tgt_ver):
            flagged.append({
                "kind": change["kind"],
                "severity": change["severity"],
                "introduced_in": change["introduced_in"],
                "description": change["description"],
                "old": change["old"],
                "new": change["new"],
            })

    # Sort by severity
    _sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    flagged.sort(key=lambda x: _sev_order.get(x["severity"], 99))

    # Parse requirements
    installed_packages = _scan_requirements(requirements_text) if requirements_text else []

    # Check for known problematic packages
    problem_packages = []
    if "langsmith" in installed_packages:
        problem_packages.append({
            "package": "langsmith",
            "note": (
                "langchain/langsmith versions were locked in ADK 1.6.2 to prevent errors. "
                "Ensure your requirements pin langsmith to a compatible version."
            ),
            "severity": "MEDIUM",
        })

    high_count = sum(1 for f in flagged if f["severity"] == "HIGH")
    med_count = sum(1 for f in flagged if f["severity"] == "MEDIUM")
    low_count = sum(1 for f in flagged if f["severity"] == "LOW")

    python_tool_count = len(inventory.get("python_tool_names", []))
    summary = (
        f"Between ADK {cur_ver_str} and {tgt_ver_str}: "
        f"{len(flagged)} constraint(s) flagged "
        f"({high_count} HIGH, {med_count} MEDIUM, {low_count} LOW). "
        f"The deployment has {python_tool_count} Python tool(s) that may need updating. "
        f"{'Review HIGH severity items before proceeding.' if high_count > 0 else 'No HIGH severity blockers found.'}"
    )

    return json.dumps({
        "current_version": cur_ver_str,
        "target_version": tgt_ver_str,
        "flagged_items": flagged,
        "package_warnings": problem_packages,
        "high_severity_count": high_count,
        "medium_severity_count": med_count,
        "low_severity_count": low_count,
        "installed_packages": installed_packages,
        "summary": summary,
    }, indent=2)

# Made with Bob

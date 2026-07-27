"""
Tool 4: Build Ordered Migration Checklist with Owner Assignments

Synthesises the outputs of parse_release_notes, inventory_deployed_config,
and flag_dependency_constraints into an ordered, human-actionable migration
checklist.  Each checklist item includes:
  - An ordered step number
  - A concise action title
  - Detailed instructions
  - Suggested owner role (Admin, Developer, DevOps, SRE)
  - Estimated effort (Low/Medium/High)
  - Priority (P0-Critical → P3-Low)
  - Status field (pre-filled as "TODO")
"""

import json
import re
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


_PRIORITY_MAP = {
    "HIGH": "P0-Critical",
    "MEDIUM": "P1-High",
    "LOW": "P2-Medium",
}

_OWNER_MAP = {
    "import_path": "Developer",
    "api_rename": "Developer",
    "api_change": "Developer",
    "cli_change": "DevOps",
    "yaml_field": "Developer",
    "connection": "Admin",
    "protocol": "Developer",
    "breaking_change": "Developer",
    "deprecation": "Developer",
    "migration_step": "DevOps",
    "new_required_config": "Admin",
}

_EFFORT_MAP = {
    "P0-Critical": "High",
    "P1-High": "Medium",
    "P2-Medium": "Low",
    "P3-Low": "Low",
}


def _make_item(
    step: int,
    title: str,
    instructions: str,
    owner: str,
    priority: str,
    effort: str = "",
    component: str = "",
    source: str = "",
) -> dict:
    return {
        "step": step,
        "title": title,
        "instructions": instructions,
        "owner": owner,
        "priority": priority,
        "effort": effort or _EFFORT_MAP.get(priority, "Medium"),
        "component": component,
        "source": source,
        "status": "TODO",
    }


@tool(
    name="build_migration_checklist",
    description=(
        "Synthesise parse_release_notes, inventory_deployed_config, and "
        "flag_dependency_constraints outputs into a numbered, owner-assigned "
        "migration checklist. Each item has a title, detailed instructions, "
        "owner role (Admin/Developer/DevOps/SRE), priority (P0–P3), effort "
        "estimate, and a TODO status field. Ordered from pre-upgrade prerequisites "
        "through post-upgrade validation. Returns a JSON checklist and a "
        "Markdown-formatted checklist for copy-paste into a runbook or ticket."
    ),
    permission=ToolPermission.READ_ONLY,
)
def build_migration_checklist(
    release_notes_json: str,
    inventory_json: str,
    constraints_json: str,
    assigned_admin: str = "Platform Admin",
    assigned_developer: str = "Tool Developer",
    assigned_devops: str = "DevOps Engineer",
    assigned_sre: str = "SRE",
) -> str:
    """
    Build a complete, ordered migration checklist for the wxO upgrade.

    Args:
        release_notes_json:  JSON output from parse_release_notes tool.
        inventory_json:      JSON output from inventory_deployed_config tool.
        constraints_json:    JSON output from flag_dependency_constraints tool.
        assigned_admin:      Name or team for Admin-owned checklist items.
                             Defaults to "Platform Admin".
        assigned_developer:  Name or team for Developer-owned items.
                             Defaults to "Tool Developer".
        assigned_devops:     Name or team for DevOps-owned items.
                             Defaults to "DevOps Engineer".
        assigned_sre:        Name or team for SRE-owned items.
                             Defaults to "SRE".

    Returns:
        JSON string containing:
        - checklist: ordered list of checklist item objects
        - total_items: integer
        - p0_count: count of P0-Critical items
        - p1_count: count of P1-High items
        - markdown_checklist: full Markdown-formatted checklist for copy-paste
        - summary: plain-text summary
        - error: present only on failure
    """
    owner_name_map = {
        "Admin": assigned_admin,
        "Developer": assigned_developer,
        "DevOps": assigned_devops,
        "SRE": assigned_sre,
    }

    try:
        release_notes = json.loads(release_notes_json)
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"error": f"Failed to parse release_notes_json: {exc}"})

    try:
        inventory = json.loads(inventory_json)
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"error": f"Failed to parse inventory_json: {exc}"})

    try:
        constraints = json.loads(constraints_json)
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"error": f"Failed to parse constraints_json: {exc}"})

    current_version = release_notes.get("current_version", "current")
    target_version = release_notes.get("target_version", "target")
    risk_level = release_notes.get("risk_level", "MEDIUM")

    checklist: list[dict] = []
    step = 1

    # ── Phase 0: Pre-upgrade prerequisites ──────────────────────────────────
    checklist.append(_make_item(
        step=step, title="Create a full environment backup",
        instructions=(
            "Before any upgrade actions, run the Backup & Restore Automation Notebook or "
            "manually export all agents and tools:\n"
            "  orchestrate agents export -n <agent_name> -o ./backup/\n"
            "  orchestrate tools export -n <tool_name> -o ./backup/\n"
            "  orchestrate knowledge-bases export -n <kb_name> -o ./backup/\n"
            "Snapshot all data volumes (Postgres, Elasticsearch, Milvus).\n"
            "Verify backups are complete before proceeding."
        ),
        owner="SRE", priority="P0-Critical", component="Infrastructure",
        source="pre-upgrade prerequisite",
    ))
    step += 1

    checklist.append(_make_item(
        step=step, title=f"Verify ADK upgrade path from {current_version} to {target_version}",
        instructions=(
            f"Confirm the pip install target version:\n"
            f"  pip install --upgrade ibm-watsonx-orchestrate=={target_version}\n"
            f"Check Python version compatibility (ADK requires Python 3.11+).\n"
            f"Verify the wxO server version matches the ADK target version.\n"
            f"Review the full release notes at: "
            f"https://developer.watson-orchestrate.ibm.com/release/release"
        ),
        owner="DevOps", priority="P0-Critical", component="ADK",
        source="pre-upgrade prerequisite",
    ))
    step += 1

    # ── Phase 1: Breaking changes from release notes ─────────────────────────
    breaking = release_notes.get("breaking_changes", [])
    for bc in breaking:
        checklist.append(_make_item(
            step=step,
            title=f"Resolve breaking change: {bc[:80]}{'…' if len(bc) > 80 else ''}",
            instructions=(
                f"Breaking change detected in changelog:\n\n  {bc}\n\n"
                "Review this change against your deployed agents and tools. "
                "Update any affected agent YAML files, Python tool code, or flow definitions. "
                "Test in a non-production environment before applying to production."
            ),
            owner="Developer", priority="P0-Critical", component="Agent/Tool",
            source="changelog breaking change",
        ))
        step += 1

    # ── Phase 2: HIGH severity constraint flags ───────────────────────────────
    flagged = constraints.get("flagged_items", [])
    for item in flagged:
        if item["severity"] != "HIGH":
            continue
        priority = _PRIORITY_MAP[item["severity"]]
        owner = _OWNER_MAP.get(item["kind"], "Developer")
        checklist.append(_make_item(
            step=step,
            title=f"[{item['kind'].replace('_',' ').title()}] {item['description'][:80]}",
            instructions=(
                f"{item['description']}\n\n"
                f"Old: {item['old']}\n"
                f"New: {item['new']}\n\n"
                f"Introduced in ADK {item['introduced_in']}. "
                "Update all affected Python tools, agent YAMLs, or flow definitions."
            ),
            owner=owner, priority=priority,
            component=item["kind"].replace("_", " ").title(),
            source=f"ADK {item['introduced_in']} constraint",
        ))
        step += 1

    # ── Phase 3: Deprecation notices ─────────────────────────────────────────
    deprecations = release_notes.get("deprecations", [])
    for dep in deprecations:
        checklist.append(_make_item(
            step=step,
            title=f"Migrate deprecated API: {dep[:80]}{'…' if len(dep) > 80 else ''}",
            instructions=(
                f"Deprecation found in changelog:\n\n  {dep}\n\n"
                "Update affected code before the deprecated item is removed in a future version. "
                "Check all Python tools for usage of the deprecated API."
            ),
            owner="Developer", priority="P1-High", component="Python Tools",
            source="changelog deprecation",
        ))
        step += 1

    # ── Phase 4: MEDIUM severity constraint flags ─────────────────────────────
    for item in flagged:
        if item["severity"] != "MEDIUM":
            continue
        priority = _PRIORITY_MAP[item["severity"]]
        owner = _OWNER_MAP.get(item["kind"], "Developer")
        checklist.append(_make_item(
            step=step,
            title=f"[{item['kind'].replace('_',' ').title()}] {item['description'][:80]}",
            instructions=(
                f"{item['description']}\n\n"
                f"Old: {item['old']}\n"
                f"New: {item['new']}\n\n"
                f"Introduced in ADK {item['introduced_in']}."
            ),
            owner=owner, priority=priority,
            component=item["kind"].replace("_", " ").title(),
            source=f"ADK {item['introduced_in']} constraint",
        ))
        step += 1

    # ── Phase 5: Migration steps from release notes ───────────────────────────
    migration_steps = release_notes.get("migration_steps", [])
    for ms in migration_steps:
        checklist.append(_make_item(
            step=step,
            title=f"Migration action: {ms[:80]}{'…' if len(ms) > 80 else ''}",
            instructions=(
                f"Migration step from release notes:\n\n  {ms}\n\n"
                "Apply this change to all relevant components in your deployment."
            ),
            owner="Developer", priority="P1-High", component="Configuration",
            source="changelog migration step",
        ))
        step += 1

    # ── Phase 6: New required configurations ─────────────────────────────────
    new_configs = release_notes.get("new_required_configs", [])
    for nc in new_configs:
        checklist.append(_make_item(
            step=step,
            title=f"Configure new required field: {nc[:80]}{'…' if len(nc) > 80 else ''}",
            instructions=(
                f"New required configuration introduced:\n\n  {nc}\n\n"
                "Add this field to all relevant agent YAML files or tool configurations. "
                "Refer to the ADK documentation for the exact field format."
            ),
            owner="Admin", priority="P1-High", component="Agent YAML / Config",
            source="changelog new config",
        ))
        step += 1

    # ── Phase 7: LOW severity flags ───────────────────────────────────────────
    for item in flagged:
        if item["severity"] != "LOW":
            continue
        priority = _PRIORITY_MAP[item["severity"]]
        owner = _OWNER_MAP.get(item["kind"], "Developer")
        checklist.append(_make_item(
            step=step,
            title=f"[{item['kind'].replace('_',' ').title()}] {item['description'][:80]}",
            instructions=(
                f"{item['description']}\n\n"
                f"Old: {item['old']}\nNew: {item['new']}\n"
                f"Introduced in ADK {item['introduced_in']}."
            ),
            owner=owner, priority=priority,
            component=item["kind"].replace("_", " ").title(),
            source=f"ADK {item['introduced_in']} constraint",
        ))
        step += 1

    # ── Phase 8: Apply ADK upgrade ────────────────────────────────────────────
    checklist.append(_make_item(
        step=step, title=f"Apply ADK upgrade to {target_version}",
        instructions=(
            f"After completing all preceding steps, apply the upgrade:\n"
            f"  pip install --upgrade ibm-watsonx-orchestrate=={target_version}\n"
            f"Verify: orchestrate --version\n"
            f"Re-import all updated agents and tools:\n"
            f"  ./import-all.sh"
        ),
        owner="DevOps", priority="P0-Critical", component="ADK",
        source="upgrade execution",
    ))
    step += 1

    # ── Phase 9: Post-upgrade validation ─────────────────────────────────────
    agent_count = inventory.get("agent_count", 0)
    tool_count = inventory.get("tool_count", 0)
    checklist.append(_make_item(
        step=step, title="Run post-upgrade validation",
        instructions=(
            f"Validate all {agent_count} agent(s) and {tool_count} tool(s) are healthy:\n"
            f"  orchestrate agents list\n"
            f"  orchestrate tools list\n"
            f"Run smoke tests for each agent.\n"
            "Use the Agent & Tool Validation Suite if available.\n"
            "Confirm no tools show import errors."
        ),
        owner="SRE", priority="P0-Critical", component="All",
        source="post-upgrade validation",
    ))
    step += 1

    # Resolve owner names
    for item in checklist:
        item["assigned_to"] = owner_name_map.get(item["owner"], item["owner"])

    # Counts
    p0 = sum(1 for i in checklist if i["priority"] == "P0-Critical")
    p1 = sum(1 for i in checklist if i["priority"] == "P1-High")
    p2 = sum(1 for i in checklist if i["priority"] == "P2-Medium")
    p3 = sum(1 for i in checklist if i["priority"] == "P3-Low")

    # Build Markdown
    md_lines = [
        f"# Migration Checklist: wxO {current_version} → {target_version}",
        f"**Risk Level:** {risk_level}  |  **Total Items:** {len(checklist)}  "
        f"|  **P0:** {p0}  |  **P1:** {p1}  |  **P2:** {p2}",
        "",
        "| Step | Priority | Title | Owner | Effort | Status |",
        "|------|----------|-------|-------|--------|--------|",
    ]
    for item in checklist:
        md_lines.append(
            f"| {item['step']:02d} | {item['priority']} | {item['title'][:60]} "
            f"| {item['assigned_to']} | {item['effort']} | {item['status']} |"
        )
    md_lines.append("")
    md_lines.append("## Detailed Steps")
    for item in checklist:
        md_lines.append(f"\n### Step {item['step']:02d} [{item['priority']}]: {item['title']}")
        md_lines.append(f"**Owner:** {item['assigned_to']}  |  **Effort:** {item['effort']}  |  **Component:** {item['component']}")
        md_lines.append(f"\n{item['instructions']}")
        md_lines.append(f"\n- [ ] Complete  *(Source: {item['source']})*")

    summary = (
        f"Migration checklist for {current_version} → {target_version} "
        f"contains {len(checklist)} items: {p0} P0-Critical, {p1} P1-High, "
        f"{p2} P2-Medium, {p3} P3-Low. "
        f"Estimated effort is {'HIGH' if p0 >= 3 else 'MEDIUM' if p0 >= 1 else 'LOW'}."
    )

    return json.dumps({
        "checklist": checklist,
        "total_items": len(checklist),
        "p0_count": p0,
        "p1_count": p1,
        "p2_count": p2,
        "p3_count": p3,
        "markdown_checklist": "\n".join(md_lines),
        "summary": summary,
    }, indent=2)

# Made with Bob

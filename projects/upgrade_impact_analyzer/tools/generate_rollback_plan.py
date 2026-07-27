"""
Tool 5: Generate Rollback Plan with Specific CLI Commands

Uses the deployment inventory and version information to produce a
stage-by-stage rollback plan.  Each stage includes:
  - Stage name and trigger condition (when to execute this stage)
  - Ordered list of exact CLI commands to run
  - Expected outcome / verification step
  - Estimated time to execute
  - Rollback risk (data loss / service interruption warnings)

Rollback stages follow the reverse order of the upgrade phases:
  Stage 1: Immediately halt the upgrade (pre-change)
  Stage 2: Revert ADK pip package
  Stage 3: Restore agents and tools from backup exports
  Stage 4: Restore knowledge bases
  Stage 5: Restore data volumes (operator action)
  Stage 6: Verify full rollback
"""

import json
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


_ROLLBACK_STAGE_TEMPLATE = {
    "stage_number": 0,
    "stage_name": "",
    "trigger_condition": "",
    "commands": [],
    "expected_outcome": "",
    "estimated_minutes": 0,
    "data_loss_risk": "NONE",
    "service_interruption": False,
    "notes": "",
}


def _make_stage(
    number: int,
    name: str,
    trigger: str,
    commands: list[str],
    outcome: str,
    minutes: int,
    data_loss_risk: str = "NONE",
    service_interruption: bool = False,
    notes: str = "",
) -> dict:
    return {
        "stage_number": number,
        "stage_name": name,
        "trigger_condition": trigger,
        "commands": commands,
        "expected_outcome": outcome,
        "estimated_minutes": minutes,
        "data_loss_risk": data_loss_risk,
        "service_interruption": service_interruption,
        "notes": notes,
    }


@tool(
    name="generate_rollback_plan",
    description=(
        "Generate a stage-by-stage rollback plan for a wxO upgrade. Each stage "
        "includes the exact orchestrate CLI commands to execute, the trigger "
        "condition (when this stage activates), expected outcome, estimated "
        "execution time, and data-loss risk level. The plan covers ADK reversion, "
        "agent/tool restoration from backup exports, knowledge base restoration, "
        "and full post-rollback verification. Returns both a structured JSON plan "
        "and a Markdown runbook."
    ),
    permission=ToolPermission.READ_ONLY,
)
def generate_rollback_plan(
    inventory_json: str,
    release_notes_json: str,
    backup_directory: str = "./backup",
    environment_name: str = "production",
    on_prem: bool = True,
) -> str:
    """
    Generate a complete, stage-by-stage rollback plan for the wxO upgrade.

    Args:
        inventory_json:     JSON output from inventory_deployed_config tool.
                            Used to enumerate agents, tools, and KBs to restore.
        release_notes_json: JSON output from parse_release_notes tool.
                            Used to determine the version being reverted from/to.
        backup_directory:   File system path where backup exports were stored.
                            Defaults to "./backup". Use absolute path recommended.
        environment_name:   Name of the wxO environment being rolled back.
                            Defaults to "production".
        on_prem:            Set True for on-premises wxO deployments (adds
                            OpenShift/operator rollback commands). Defaults to True.

    Returns:
        JSON string containing:
        - current_version: version being reverted TO (the pre-upgrade version)
        - target_version: version being reverted FROM
        - environment_name: as provided
        - total_stages: number of rollback stages
        - estimated_total_minutes: sum of all stage estimates
        - stages: ordered list of rollback stage objects, each with:
            - stage_number, stage_name, trigger_condition
            - commands: list of exact CLI commands
            - expected_outcome, estimated_minutes
            - data_loss_risk: NONE | LOW | MEDIUM | HIGH
            - service_interruption: boolean
            - notes
        - rollback_decision_tree: guidance on which stages to execute based on failure point
        - markdown_runbook: full Markdown rollback runbook
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

    current_version = release_notes.get("current_version", "PREVIOUS")
    target_version = release_notes.get("target_version", "TARGET")
    bd = backup_directory.rstrip("/")

    agents = [a.get("name", "unknown") for a in inventory.get("agents", [])]
    tools_list = [t.get("name", "unknown") for t in inventory.get("tools", [])]
    python_tools = inventory.get("python_tool_names", [])
    flow_tools = inventory.get("flow_tool_names", [])
    openapi_tools = inventory.get("openapi_tool_names", [])
    kbs = [k.get("name", "unknown") for k in inventory.get("knowledge_bases", [])]

    stages: list[dict] = []

    # ── Stage 1: Decision Gate — Halt Upgrade ────────────────────────────────
    stages.append(_make_stage(
        number=1,
        name="Halt Upgrade (Decision Gate)",
        trigger="Triggered immediately when a critical failure is detected during any upgrade step "
                "or when the operator decides to abort.",
        commands=[
            "# Stop all in-progress import operations (Ctrl+C if still running)",
            f"# Document the exact step that failed before proceeding",
            f"echo 'ROLLBACK INITIATED at $(date)' >> {bd}/rollback.log",
            f"orchestrate agents list    # Capture current state",
            f"orchestrate tools list     # Capture current state",
        ],
        outcome="Upgrade halted. Current deployment state documented before any rollback commands run.",
        minutes=5,
        data_loss_risk="NONE",
        service_interruption=False,
        notes="Do NOT proceed to Stage 2 until you have captured the current state output.",
    ))

    # ── Stage 2: Revert ADK pip package ──────────────────────────────────────
    stages.append(_make_stage(
        number=2,
        name="Revert ADK pip Package",
        trigger="Triggered after Stage 1 if the ADK was already upgraded before the failure.",
        commands=[
            f"pip install ibm-watsonx-orchestrate=={current_version}",
            "orchestrate --version   # Verify revert succeeded",
            f"# Expected output: {current_version}",
        ],
        outcome=f"ADK downgraded back to {current_version}. "
                "CLI commands now use the previous API version.",
        minutes=5,
        data_loss_risk="NONE",
        service_interruption=False,
        notes=(
            f"If {current_version} is no longer available on PyPI, "
            "use the closest prior available version. "
            "Check: pip index versions ibm-watsonx-orchestrate"
        ),
    ))

    # ── Stage 3: Delete broken agent/tool imports ─────────────────────────────
    delete_agent_cmds = [
        f"orchestrate agents delete -n {name}    # Remove broken import"
        for name in agents
    ]
    delete_tool_cmds = [
        f"orchestrate tools delete -n {name}    # Remove broken import"
        for name in tools_list
    ]
    stages.append(_make_stage(
        number=3,
        name="Remove Partially-Upgraded Agents and Tools",
        trigger=(
            "Triggered after Stage 2. Execute ONLY if agents or tools were partially "
            "re-imported with the new ADK version before the failure."
        ),
        commands=(
            ["# Delete agents that may have been partially re-imported:"]
            + delete_agent_cmds
            + ["", "# Delete tools that may have been partially re-imported:"]
            + delete_tool_cmds
        ),
        outcome="All partially-upgraded agents and tools removed. Environment is clean for restoration.",
        minutes=max(5, (len(agents) + len(tools_list)) * 1),
        data_loss_risk="LOW",
        service_interruption=True,
        notes=(
            "Service will be unavailable during this stage. "
            "If a delete command fails (agent not found), that component was not yet imported — skip it."
        ),
    ))

    # ── Stage 4: Restore agents from backup exports ───────────────────────────
    restore_agent_cmds = [
        f"orchestrate agents import -f {bd}/{name}.yaml    # Restore agent"
        for name in agents
    ]
    if not restore_agent_cmds:
        restore_agent_cmds = [
            f"# No agents found in inventory.",
            f"# Manually import agents from: {bd}/",
        ]
    stages.append(_make_stage(
        number=4,
        name="Restore Agents from Backup",
        trigger="Triggered after Stage 3. Restores all agents from the pre-upgrade backup exports.",
        commands=(
            [f"ls {bd}/    # Verify backup files are present", ""]
            + restore_agent_cmds
            + [
                "",
                "orchestrate agents list    # Verify all agents restored",
            ]
        ),
        outcome=f"All {len(agents)} agent(s) restored from backup exports.",
        minutes=max(5, len(agents) * 2),
        data_loss_risk="NONE",
        service_interruption=False,
        notes=(
            f"Backup exports expected at: {bd}/<agent_name>.yaml\n"
            "If backup files are missing, restore from the Backup & Restore Notebook snapshot."
        ),
    ))

    # ── Stage 5: Restore tools from backup exports ────────────────────────────
    restore_tool_cmds: list[str] = []
    for name in python_tools:
        restore_tool_cmds.append(f"orchestrate tools import -k python -f {bd}/{name}.zip    # Python tool")
    for name in flow_tools:
        restore_tool_cmds.append(f"orchestrate tools import -k flow -f {bd}/{name}.zip    # Flow tool")
    for name in openapi_tools:
        restore_tool_cmds.append(f"orchestrate tools import -k openapi -f {bd}/{name}.zip    # OpenAPI tool")
    if not restore_tool_cmds:
        restore_tool_cmds = [
            f"# No tools found in inventory.",
            f"# Manually import tools from: {bd}/",
        ]
    stages.append(_make_stage(
        number=5,
        name="Restore Tools from Backup",
        trigger="Triggered after Stage 4. Restores all tools from pre-upgrade backup exports.",
        commands=(
            restore_tool_cmds
            + [
                "",
                "orchestrate tools list    # Verify all tools restored",
            ]
        ),
        outcome=f"All {len(tools_list)} tool(s) restored from backup exports.",
        minutes=max(5, len(tools_list) * 2),
        data_loss_risk="NONE",
        service_interruption=False,
        notes=(
            f"Tools were exported using: orchestrate tools export -n <tool> -o {bd}/<tool>.zip\n"
            "Python tools may also be restored directly from source .py files."
        ),
    ))

    # ── Stage 6: Restore knowledge bases ─────────────────────────────────────
    if kbs:
        restore_kb_cmds = [
            f"orchestrate knowledge-bases import -f {bd}/{kb}.yaml    # Restore KB"
            for kb in kbs
        ]
    else:
        restore_kb_cmds = ["# No knowledge bases in inventory — skip this stage."]
    stages.append(_make_stage(
        number=6,
        name="Restore Knowledge Bases",
        trigger="Triggered if knowledge bases were affected or deleted during the upgrade.",
        commands=(
            restore_kb_cmds
            + ["", "# Knowledge base documents will re-index automatically after import"]
        ),
        outcome=f"All {len(kbs)} knowledge base(s) restored and re-indexing initiated.",
        minutes=max(5, len(kbs) * 10),  # KB indexing takes longer
        data_loss_risk="LOW",
        service_interruption=False,
        notes=(
            "Knowledge base re-indexing may take several minutes per KB. "
            "Agents using the KB will not return accurate results until indexing completes."
        ),
    ))

    # ── Stage 7: On-premises operator rollback ────────────────────────────────
    if on_prem:
        stages.append(_make_stage(
            number=7,
            name="On-Premises Operator Rollback (if server was upgraded)",
            trigger=(
                "Triggered ONLY if the wxO on-premises server/operator was upgraded "
                "in addition to the ADK pip package."
            ),
            commands=[
                "# Rollback the wxO operator on OpenShift:",
                f"oc rollout undo deployment/wxo-operator -n watsonx-orchestrate",
                f"oc rollout status deployment/wxo-operator -n watsonx-orchestrate",
                "",
                "# Rollback wxO service deployments:",
                f"oc rollout undo deployment/wxo-api-server -n watsonx-orchestrate",
                f"oc rollout status deployment/wxo-api-server -n watsonx-orchestrate",
                "",
                "# Verify all pods are running on previous image:",
                "oc get pods -n watsonx-orchestrate",
                "oc describe deployment/wxo-operator -n watsonx-orchestrate | grep Image",
                "",
                "# If data volumes were migrated, restore from snapshot:",
                "# Consult your storage administrator for volume snapshot restoration.",
            ],
            outcome="wxO server reverted to the previous version. All pods running on previous image.",
            minutes=30,
            data_loss_risk="MEDIUM",
            service_interruption=True,
            notes=(
                "This stage requires cluster-admin OpenShift permissions. "
                "Data written after the server upgrade but before rollback may be lost. "
                "Coordinate with your storage team for volume snapshot restoration."
            ),
        ))

    # ── Stage 8: Post-rollback verification ──────────────────────────────────
    stages.append(_make_stage(
        number=len(stages) + 1,
        name="Post-Rollback Verification",
        trigger="Always execute as the final stage after all rollback steps complete.",
        commands=[
            "orchestrate --version           # Confirm ADK version",
            f"# Expected: {current_version}",
            "",
            "orchestrate agents list          # Verify all agents present",
            "orchestrate tools list           # Verify all tools present",
            "",
            "# Run a smoke test for each critical agent:",
            *[f"# orchestrate chat start          # Select '{name}' and test" for name in agents[:3]],
            "",
            f"echo 'ROLLBACK COMPLETE at $(date)' >> {bd}/rollback.log",
            "# File a post-mortem ticket to document root cause and prevention steps",
        ],
        outcome=(
            f"All agents and tools confirmed operational on ADK {current_version}. "
            "Rollback log updated."
        ),
        minutes=15,
        data_loss_risk="NONE",
        service_interruption=False,
        notes=(
            "If any agent or tool is still missing after Stage 4/5, "
            "check the rollback log and re-run the specific restore command. "
            "Document the incident and open a support ticket with IBM if issues persist."
        ),
    ))

    # Decision tree
    decision_tree = {
        "failure_before_any_changes": "Execute Stage 1 only. No rollback required.",
        "failure_during_adk_pip_upgrade": "Execute Stages 1 → 2.",
        "failure_during_agent_import": "Execute Stages 1 → 2 → 3 → 4.",
        "failure_during_tool_import": "Execute Stages 1 → 2 → 3 → 4 → 5.",
        "failure_during_kb_import": "Execute Stages 1 → 2 → 3 → 4 → 5 → 6.",
        "failure_after_server_upgrade": "Execute ALL stages including Stage 7.",
        "post_upgrade_instability": "Execute Stages 1 → 7 (on-prem server rollback) → 8.",
    }

    total_minutes = sum(s["estimated_minutes"] for s in stages)

    # Build Markdown runbook
    md_lines = [
        f"# Rollback Runbook: wxO {target_version} → {current_version}",
        f"**Environment:** {environment_name}  |  "
        f"**Estimated Total Time:** {total_minutes} minutes  |  "
        f"**Backup Location:** {bd}",
        "",
        "## Decision Tree — Which Stages to Execute",
        "",
    ]
    for condition, action in decision_tree.items():
        md_lines.append(f"- **{condition.replace('_', ' ').title()}:** {action}")
    md_lines.append("")
    md_lines.append("---")

    for stage in stages:
        interrupt_flag = "⚠️ Service interruption" if stage["service_interruption"] else "✅ No service interruption"
        risk_flag = f"🔴 {stage['data_loss_risk']} data loss risk" if stage["data_loss_risk"] != "NONE" else "✅ No data loss risk"
        md_lines.append(f"\n## Stage {stage['stage_number']}: {stage['stage_name']}")
        md_lines.append(f"**Trigger:** {stage['trigger_condition']}")
        md_lines.append(f"**Est. time:** {stage['estimated_minutes']} min  |  {interrupt_flag}  |  {risk_flag}")
        md_lines.append("\n```bash")
        for cmd in stage["commands"]:
            md_lines.append(cmd)
        md_lines.append("```")
        md_lines.append(f"\n**Expected outcome:** {stage['expected_outcome']}")
        if stage["notes"]:
            md_lines.append(f"\n> **Note:** {stage['notes']}")
        md_lines.append("\n- [ ] Complete")

    summary = (
        f"Rollback plan for {target_version} → {current_version} contains "
        f"{len(stages)} stages covering ADK reversion, restoration of "
        f"{len(agents)} agent(s), {len(tools_list)} tool(s), and {len(kbs)} KB(s). "
        f"Estimated total rollback time: {total_minutes} minutes. "
        f"{'Includes on-premises operator rollback steps.' if on_prem else ''}"
    )

    return json.dumps({
        "current_version": current_version,
        "target_version": target_version,
        "environment_name": environment_name,
        "total_stages": len(stages),
        "estimated_total_minutes": total_minutes,
        "stages": stages,
        "rollback_decision_tree": decision_tree,
        "markdown_runbook": "\n".join(md_lines),
        "summary": summary,
    }, indent=2)

# Made with Bob

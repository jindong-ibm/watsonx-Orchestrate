"""
Tool 2: Inventory Deployed wxO Configuration

Accepts the raw CLI output (or structured JSON) produced by running:
  orchestrate agents list -v
  orchestrate tools list -v
  orchestrate knowledge-bases list (if supported)

Then parses and inventories:
  - Installed agents with their LLM model, style, collaborators, and tool list
  - Installed tools with their kind (python, flow, openapi, langflow, mcp)
  - LLM/model configurations referenced by agents
  - Knowledge bases and their embedding models

Returns a unified deployment inventory JSON consumed by later pipeline tools.
"""

import re
import json
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# ─────────────────────────────────────────────────────────────────────────────
# Known ADK-managed tool kinds and their import CLI flag
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_KIND_MAP = {
    "python": "python",
    "flow": "flow",
    "agentic_workflow": "flow",
    "openapi": "openapi",
    "langflow": "langflow",
    "mcp": "mcp",
}


def _parse_table_output(raw_text: str) -> list[dict]:
    """
    Parse the tabular output produced by `orchestrate * list`.
    Handles pipe-separated and space-aligned table formats.
    Returns a list of dicts (one per row).
    """
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not lines:
        return []

    # Find the header line — contains at least two uppercase words or "Name"
    header_idx = None
    for i, line in enumerate(lines):
        if re.search(r'\b(Name|KIND|LLM|MODEL|ID|TYPE)\b', line, re.IGNORECASE):
            header_idx = i
            break
    if header_idx is None:
        return [{"raw": line} for line in lines]

    header_line = lines[header_idx]

    # Detect separator style
    if "|" in header_line:
        headers = [h.strip() for h in header_line.split("|") if h.strip()]
        rows = []
        for line in lines[header_idx + 1:]:
            if re.match(r'^[-+| ]+$', line):
                continue  # separator row
            parts = [p.strip() for p in line.split("|") if p.strip() or True]
            # Align by splitting on | same way
            cell_parts = line.split("|")
            # drop first/last empty from leading/trailing |
            cells = [c.strip() for c in cell_parts[1:-1]] if line.startswith("|") else [c.strip() for c in cell_parts]
            if len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
        return rows
    else:
        # Space-aligned: detect column positions from header
        col_starts = [m.start() for m in re.finditer(r'\S+', header_line)]
        col_names = [header_line[s:].split()[0] for s in col_starts]
        col_ends = col_starts[1:] + [None]
        rows = []
        for line in lines[header_idx + 1:]:
            if re.match(r'^[-=]+$', line):
                continue
            row = {}
            for name, start, end in zip(col_names, col_starts, col_ends):
                val = line[start:end].strip() if end else line[start:].strip()
                row[name] = val
            rows.append(row)
        return rows


def _extract_agents(agents_output: str) -> list[dict]:
    """Parse agents list output into structured agent records."""
    if not agents_output.strip():
        return []
    rows = _parse_table_output(agents_output)
    agents = []
    for row in rows:
        # Normalise key names — CLI uses Name/LLM/Style
        name = row.get("Name") or row.get("name") or row.get("raw", "unknown")
        llm = row.get("LLM") or row.get("llm") or row.get("Model") or ""
        style = row.get("Style") or row.get("style") or "default"
        agents.append({
            "name": name,
            "llm": llm,
            "style": style,
            "raw_row": row,
        })
    return agents


def _extract_tools(tools_output: str) -> list[dict]:
    """Parse tools list output into structured tool records."""
    if not tools_output.strip():
        return []
    rows = _parse_table_output(tools_output)
    tools_list = []
    for row in rows:
        name = row.get("Name") or row.get("name") or row.get("raw", "unknown")
        kind = row.get("Kind") or row.get("kind") or row.get("Type") or row.get("type") or "unknown"
        kind_normalised = _TOOL_KIND_MAP.get(kind.lower(), kind.lower())
        tools_list.append({
            "name": name,
            "kind": kind_normalised,
            "raw_row": row,
        })
    return tools_list


def _extract_knowledge_bases(kb_output: str) -> list[dict]:
    """Parse knowledge-bases list output into structured KB records."""
    if not kb_output.strip():
        return []
    rows = _parse_table_output(kb_output)
    kbs = []
    for row in rows:
        name = row.get("Name") or row.get("name") or row.get("raw", "unknown")
        kbs.append({
            "name": name,
            "raw_row": row,
        })
    return kbs


@tool(
    name="inventory_deployed_config",
    description=(
        "Inventory the watsonx Orchestrate deployment by parsing the output of "
        "'orchestrate agents list -v', 'orchestrate tools list -v', and optionally "
        "'orchestrate knowledge-bases list'. Returns a structured JSON inventory of "
        "all deployed agents, tools (with kind), knowledge bases, and LLM models "
        "referenced — used as input by flag_dependency_constraints and "
        "build_migration_checklist."
    ),
    permission=ToolPermission.READ_ONLY,
)
def inventory_deployed_config(
    agents_list_output: str,
    tools_list_output: str,
    knowledge_bases_list_output: str = "",
    environment_name: str = "production",
) -> str:
    """
    Parse CLI list outputs and produce a full deployment inventory.

    Run the following commands on your wxO environment and paste their output:
      orchestrate agents list -v
      orchestrate tools list -v
      orchestrate knowledge-bases list   (optional)

    Args:
        agents_list_output:         Full text output from `orchestrate agents list -v`.
        tools_list_output:          Full text output from `orchestrate tools list -v`.
        knowledge_bases_list_output: Full text output from `orchestrate knowledge-bases list`
                                     (optional, pass empty string if unavailable).
        environment_name:           Label for the target environment (e.g. "production",
                                    "staging"). Defaults to "production".

    Returns:
        JSON string containing:
        - environment_name: as provided
        - agents: list of agent objects with name, llm, style
        - tools: list of tool objects with name and kind
        - knowledge_bases: list of KB objects with name
        - llm_models_in_use: deduplicated list of LLM identifiers referenced by agents
        - python_tool_names: list of tool names whose kind is "python"
        - flow_tool_names: list of tool names whose kind is "flow"
        - openapi_tool_names: list of tool names whose kind is "openapi"
        - agent_count: integer
        - tool_count: integer
        - kb_count: integer
        - inventory_warnings: list of parse warnings (e.g. empty sections)
        - summary: plain-text summary paragraph
    """
    warnings: list[str] = []

    if not agents_list_output.strip():
        warnings.append("agents_list_output is empty — agent inventory will be incomplete.")
    if not tools_list_output.strip():
        warnings.append("tools_list_output is empty — tool inventory will be incomplete.")

    agents = _extract_agents(agents_list_output)
    tools_list = _extract_tools(tools_list_output)
    knowledge_bases = _extract_knowledge_bases(knowledge_bases_list_output)

    # Deduplicate LLM models referenced by agents
    llm_models = list({a["llm"] for a in agents if a["llm"]})

    # Partition tools by kind
    python_tools = [t["name"] for t in tools_list if t["kind"] == "python"]
    flow_tools = [t["name"] for t in tools_list if t["kind"] in ("flow", "agentic_workflow")]
    openapi_tools = [t["name"] for t in tools_list if t["kind"] == "openapi"]

    summary = (
        f"Environment '{environment_name}' has {len(agents)} agent(s), "
        f"{len(tools_list)} tool(s) ({len(python_tools)} Python, "
        f"{len(flow_tools)} flow, {len(openapi_tools)} OpenAPI), "
        f"and {len(knowledge_bases)} knowledge base(s). "
        f"LLM models in use: {', '.join(llm_models) if llm_models else 'none detected'}."
    )

    return json.dumps({
        "environment_name": environment_name,
        "agents": agents,
        "tools": tools_list,
        "knowledge_bases": knowledge_bases,
        "llm_models_in_use": llm_models,
        "python_tool_names": python_tools,
        "flow_tool_names": flow_tools,
        "openapi_tool_names": openapi_tools,
        "agent_count": len(agents),
        "tool_count": len(tools_list),
        "kb_count": len(knowledge_bases),
        "inventory_warnings": warnings,
        "summary": summary,
    }, indent=2)

# Made with Bob

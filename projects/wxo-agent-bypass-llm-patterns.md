# wxO Agent: Bypassing LLM Invocation Patterns

> Discussions on how to return results directly to end users, skipping model re-invocation, in IBM watsonx Orchestrate.

---

## 1. Tool-Level Bypass (Single Agent)

### Problem
By default, when a tool returns a result, the agent's LLM re-invokes to process and summarize the tool output before sending it to the user. This adds latency and may alter the exact content.

### Solution: `audience=["user"]` annotation

When a tool returns a `ToolResult` with content annotated as `audience=["user"]`, the text is passed through directly — no agent reasoning is triggered.

| Property | Behavior |
|---|---|
| Agent reasoning | ❌ Not triggered |
| Message to context | ✅ Passed as AI message (prevents hallucinations) |
| User output | ✅ Exact text, as-is |

```python
from ibm_watsonx_orchestrate.run import ToolResult, TextContent, Annotations, Role

return ToolResult(
    content=[
        TextContent(
            text="Account status retrieved successfully",
            annotations=Annotations(audience=[Role.USER])
        )
    ]
)
```

### Bonus: Widget always bypasses LLM

When any tool response includes a **widget**, the agent runtime unconditionally skips LLM reasoning — the response is treated as final regardless of audience:

```python
from ibm_watsonx_orchestrate.run.forms import FormWidget, TextInput

return ToolResult(
    content=[TextContent(text="...", annotations=Annotations(audience=[Role.USER]))],
    widget=FormWidget(title="Update Account", inputs=[TextInput(name="email", title="Email")])
)
```

### Audience Summary

| Audience | Widget present? | Skips LLM? |
|---|---|---|
| `["user"]` | No | ✅ Yes |
| `["assistant"]` | No | ❌ No |
| `["user", "assistant"]` | No | ❌ No |
| Any | Yes | ✅ Always |

**Reference:** [Tool response structure — Audience behavior](https://developer.watson-orchestrate.ibm.com/tools/tool_response_structure#audience-behavior)

---

## 2. Multi-Agent: Bypassing the Supervisor/Orchestrator LLM

### Problem

In a multi-agent setup, the default flow is:

```
User → Supervisor LLM → calls Collaborator → Collaborator responds → Supervisor LLM re-invokes → User
```

There is no built-in flag to say "forward the collaborator result as-is." The supervisor's LLM always gets a turn to re-synthesize before responding to the user.

---

### Workaround 1: `audience=["user"]` inside the Collaborator's Tool

The collaborator's tools can return `audience=["user"]`, which bypasses reasoning **within the collaborator**. However, the collaborator's final answer still flows back to the supervisor, which will re-invoke its own LLM.

> ⚠️ **Limitation:** This only skips reasoning inside the collaborator agent, not across the supervisor boundary.

---

### Workaround 2: `planner` Style + `custom_join_tool` — ⚠️ DEPRECATED

> **Deprecation notice (ADK v2.13.0):** The `planner` agent style (along with `default` and `react`) is **officially deprecated** as of ADK v2.13.0 (July 2026) and will be removed in a future release. The `custom_join_tool` mechanism only works with `style: planner`, so it is deprecated by extension. **Migrate to `react_core` + `audience=["user"]` in a regular tool instead.** See the [agent style migration guide](https://developer.watson-orchestrate.ibm.com/agents/agent_styles_migration).

The `planner` agent style supports a `custom_join_tool` — a Python tool that **replaces the supervisor LLM's final synthesis step**. The join tool receives all collaborator/tool results and can pass them through verbatim using `audience=["user"]`.

**Agent YAML (deprecated — do not use for new projects):**
```yaml
spec_version: v1
style: planner          # ⚠️ deprecated — will be removed in a future release
custom_join_tool: passthrough_join
name: supervisor_agent
llm: groq/openai/gpt-oss-120b
collaborators:
  - my_collaborator_agent
tools:
  - some_tool
```

**Join tool (deprecated pattern):**
```python
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.agent_builder.tools.types import PythonToolKind
from typing import Dict, List, Any

@tool(kind=PythonToolKind.JOIN_TOOL)  # PythonToolKind.JOIN_TOOL is also deprecated
def passthrough_join(
    original_query: str,
    task_results: Dict[str, Any],
    messages: List[Dict[str, Any]]
) -> dict:
    """Pass collaborator results directly to the user without LLM synthesis."""
    result = next(iter(task_results.values()))
    return {
        "content": [{
            "type": "text",
            "text": result,
            "annotations": {"audience": ["user"]}
        }]
    }
```

**Recommended migration — `react_core` + regular tool with `audience=["user"]`:**
```yaml
style: react_core
instructions: |
  After calling the required tools to answer a user's query,
  call my_formatting_tool to consolidate results and format the response.
```
```python
from ibm_watsonx_orchestrate.agent_builder.tools import tool

@tool()
def my_formatting_tool(original_query: str, task_results: dict) -> dict:
    """Format and return results directly to the user."""
    output = f"## Results for: {original_query}\n\n"
    for name, result in task_results.items():
        output += f"### {name}\n{result}\n\n"
    return {
        "content": [{"type": "text", "text": output, "annotations": {"audience": ["user"]}}]
    }
```

> See [Migrating custom join tools](https://developer.watson-orchestrate.ibm.com/agents/agent_styles_migration#migrating-custom-join-tools) for the full migration guide.

---

### Workaround 3: Agentic Flow as General Solution ⭐

The most general and scalable approach. A Flow tool provides **deterministic orchestration** — agents run as nodes in a defined order (or in parallel), results are mapped explicitly, and the supervisor never needs to re-invoke its LLM.

#### Two mechanisms work together

| Mechanism | Where it applies | Effect |
|---|---|---|
| `suppress_agent_summarization=True` | `@flow` decorator | Supervisor skips post-flow LLM summarization |
| `audience=["user"]` in merge tool | Final tool node in the flow | Flow output bypasses any in-flow LLM re-processing |

#### Architecture

```
User
 └─► Supervisor Agent (no LLM re-invocation — suppress_agent_summarization=True)
       └─► Flow Tool
             ├─► Agent Node A ──┐
             │                  ├─► Parallel Node
             ├─► Agent Node B ──┘
             │
             └─► Merge Tool Node  (audience=["user"]) → END
```

#### Complete Code Example

**Merge tool (reusable for any N collaborators):**
```python
from ibm_watsonx_orchestrate.agent_builder.tools import tool

@tool()
def merge_agent_results(result_a: str, result_b: str) -> dict:
    """Merge results from multiple collaborator agents and return directly to the user.

    Args:
        result_a (str): Output from agent A.
        result_b (str): Output from agent B.

    Returns:
        dict: ToolResult with audience=user to bypass supervisor LLM.
    """
    return {
        "content": [{
            "type": "text",
            "text": f"## Result from Agent A\n{result_a}\n\n## Result from Agent B\n{result_b}",
            "annotations": {"audience": ["user"]}
        }]
    }
```

**Flow definition:**
```python
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END

class FlowInput(BaseModel):
    query: str = Field(description="User query")

class AgentOutput(BaseModel):
    answer: str = Field(description="Agent's answer")

@flow(
    name="multi_agent_passthrough_flow",
    input_schema=FlowInput,
    suppress_agent_summarization=True,  # ← skips supervisor post-flow LLM call
)
def build_flow(aflow: Flow) -> Flow:
    """Run two specialist agents in parallel and merge results directly to the user."""

    agent_a_node = aflow.agent(
        name="agent_a_node",
        agent="agent_a",
        message="Answer the query using your domain knowledge.",
        output_schema=AgentOutput,
    )
    agent_b_node = aflow.agent(
        name="agent_b_node",
        agent="agent_b",
        message="Answer the query using your domain knowledge.",
        output_schema=AgentOutput,
    )

    # Run both agents concurrently
    parallel = aflow.parallel()
    parallel.branch(agent_a_node)
    parallel.branch(agent_b_node)

    # Merge node collects outputs via explicit mapping
    merge_node = aflow.tool(merge_agent_results)
    merge_node.map_input("result_a", "flow.agent_a_node.output.answer")
    merge_node.map_input("result_b", "flow.agent_b_node.output.answer")

    aflow.sequence(START, parallel, merge_node, END)
    return aflow
```

**Add the flow as a tool to the supervisor agent:**
```yaml
spec_version: v1
kind: native
name: supervisor_agent
style: react_core
llm: watsonx/ibm/granite-3-8b-instruct
tools:
  - multi_agent_passthrough_flow
```

#### Why this is the general solution

| Requirement | How it's solved |
|---|---|
| Multiple collaborator agents | Agent Nodes (sequential or Parallel Node) |
| Merge all results in one place | Tool Node at the end with `map_input()` |
| Skip supervisor LLM re-invocation | `suppress_agent_summarization=True` on `@flow` |
| Skip within-flow LLM re-processing | `audience=["user"]` in merge tool's return |
| Works for any N collaborators | Add more Agent Nodes + parameters to merge tool |
| No agent-style restriction | Works with any supervisor style (`react_core`, `default`, etc.) |

---

## Comparison of All Approaches

| Approach | Skips Supervisor LLM? | Works With Any Supervisor Style? | Scalable to N Agents? | Status |
|---|---|---|---|---|
| `audience=["user"]` in collaborator tool | ❌ Partial (within collaborator only) | ✅ Yes | N/A | ✅ Supported |
| `planner` + `custom_join_tool` | ✅ Yes | ❌ No (planner only) | ⚠️ Manual | ⚠️ Deprecated (v2.13.0) |
| **Flow + `suppress_agent_summarization` + `audience=["user"]`** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Recommended |

---

## References

- [Tool response structure — Audience behavior](https://developer.watson-orchestrate.ibm.com/tools/tool_response_structure#audience-behavior)
- [Plan-Act style & custom_join_tool](https://developer.watson-orchestrate.ibm.com/agents/build_agent#plan-act-style)
- [Migrating custom join tools](https://developer.watson-orchestrate.ibm.com/agents/agent_styles_migration#migrating-custom-join-tools)
- [Building agentic workflows — @flow decorator](https://developer.watson-orchestrate.ibm.com/tools/flows/building_flow)
- [Agent node in flows](https://developer.watson-orchestrate.ibm.com/tools/flows/agent_node)
- [Mapping inputs and outputs](https://developer.watson-orchestrate.ibm.com/tools/flows/data_map)

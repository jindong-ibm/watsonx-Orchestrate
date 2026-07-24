---
name: create-wxo-project
description: Use when the user wants to create a new watsonx Orchestrate project — guides through scaffolding the directory structure, writing Python tools, building flows with the @flow decorator, configuring YAML agents, knowledge bases, guidelines, model policies, channels, and generating the import-all.sh deployment script.
---

# Create a watsonx Orchestrate Project

Always check `wxo-implementation-guide.md` before writing any file — it is the authoritative reference for patterns, code examples, and naming conventions.

Follow these steps in order.

---

## Step 1 — Understand the Use Case

Use `ask_followup_question` to clarify:
- What does the project do? (e.g., document processing, user activity form, multi-agent collaboration)
- Does it need a **flow**, standalone **Python tools**, or both?
- Does it involve document upload / extraction (DocProc pattern)?
- Will it need multiple agents collaborating?
- Does it need a **knowledge base** (documents the agent should search)?
- Does it need **guidelines** (rule-based agent behaviour conditions)?
- Does it need a **model policy** (load-balancing or fallback across LLMs)?
- Does it need a **channel** deployment (Slack, WhatsApp, Teams, web chat, etc.)?

Map the answer to one of the four patterns in the guide:
| Pattern | Use Case |
|---|---|
| 1. Simple Tool Flow | Basic data retrieval or processing |
| 2. Document Processing Flow | Extract structured data from documents |
| 3. User Activity Flow | Interactive multi-step input collection |
| 4. Multi-Agent Collaboration | Complex tasks with specialised agents |

---

## Step 2 — Choose a Project Name and Root Directory

- Use `snake_case` for the root directory name (e.g., `expense_report_agent`).
- Place it at the **workspace root** unless the user specifies otherwise.
- Confirm the name with the user before creating files.

---

## Step 3 — Scaffold the Directory Structure

Use `execute_command` to create the skeleton:

```bash
mkdir -p <project_name>/{tools,agents,generated,knowledge-bases,channels}
touch <project_name>/__init__.py
touch <project_name>/tools/__init__.py
touch <project_name>/README.md
touch <project_name>/import-all.sh
chmod +x <project_name>/import-all.sh
```

Only create `main_flow.py` if the project contains at least one flow.
Only keep `knowledge-bases/` and `channels/` directories if the project uses them.

---

## Step 4 — Write the Python Tool (if needed)

Create `tools/<tool_name>.py`. Always use:
- `@tool` decorator from `ibm_watsonx_orchestrate.agent_builder.tools`
- `ToolPermission.READ_ONLY` for read-only operations, `ToolPermission.READ_WRITE` otherwise
- Type hints on all parameters and return type
- A clear docstring (this becomes the tool description in WxO)

```python
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

@tool(permission=ToolPermission.READ_ONLY)
def my_tool(param: str) -> dict:
    """One-sentence description of what the tool does."""
    return {"result": param}
```

---

## Step 5 — Write the Flow (if needed)

Create `tools/<flow_name>.py`. Key rules:
- Define a Pydantic `BaseModel` for `input_schema`
- Use `@flow` decorator from `ibm_watsonx_orchestrate.flow_builder.flows`
- Connect nodes with `aflow.sequence(START, node1, ..., END)`
- For document processing: use `aflow.docproc(...)` node — **do not** ask the agent to upload documents; the flow handles that itself

```python
from pydantic import BaseModel
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END
from .my_tool import my_tool

class MyFlowInput(BaseModel):
    input_param: str

@flow(
    name="my_flow",
    display_name="My Flow",
    description="Flow description",
    input_schema=MyFlowInput
)
def build_my_flow(aflow: Flow) -> Flow:
    tool_node = aflow.tool(my_tool)
    aflow.sequence(START, tool_node, END)
    return aflow
```

---

## Step 6 — Create the Knowledge Base (if needed)

Create `knowledge-bases/<kb_name>.yaml`. Key rules:
- Each file must have a unique name; max 100 files per YAML.
- Default embedding model is `ibm/slate-125m-english-rtrvr-v2`; override with `vector_index.embeddings_model_name`.
- Default mode is **dynamic** (agent decides how to use retrieved content). Switch to classic mode by setting `conversational_search_tool.query_source: SessionHistory`.
- **Only one knowledge base per agent is currently supported.**

```yaml
spec_version: v1
kind: knowledge_base
name: my_knowledge_base
description: |
  Describe what domain knowledge this base provides.
documents:
  - path: docs/policy.pdf
    url: https://optional-source-url.com/policy
  - path: docs/faq.pdf
vector_index:
  embeddings_model_name: ibm/slate-125m-english-rtrvr-v2   # default, can omit
conversational_search_tool:
  query_source: Agent     # dynamic mode (default); use SessionHistory for classic mode
  generation:
    enabled: true         # set false to disable KB-generated answers (pure retrieval)
```

Import it before importing the agent:
```bash
orchestrate knowledge-bases import -f ${SCRIPT_DIR}/knowledge-bases/my_knowledge_base.yaml
```

Add the knowledge base name to the agent YAML:
```yaml
knowledge_base:
  - my_knowledge_base
```

---

## Step 7 — Write the Agent YAML

Create `agents/<agent_name>.yaml`. Required fields and optional advanced fields:

```yaml
spec_version: v1
kind: native
name: my_agent
description: One-sentence description shown to users and used by supervisor agents for routing.
instructions: |
  When the user wants to <task>, invoke the <tool_or_flow> tool and return the result.
llm: groq/openai/gpt-oss-120b
style: default              # options: default | react | react_intrinsic
hide_reasoning: false
memory_enabled: false
tools:
  - my_flow
knowledge_base:
  - my_knowledge_base       # omit if not used; only one supported
collaborators: []           # list collaborator agent names if multi-agent
```

⚠️ DocProc agents: instructions must say "immediately invoke the flow — the flow will prompt the user to upload the document." Never instruct the agent to ask for the document upload itself.

### Adding Guidelines (if needed)

Guidelines are rule-based behaviours stronger than free-form instructions. Each follows the pattern: **When** `condition` **then** `action` (and/or invoke a `tool`). They execute in priority order (top to bottom).

Add a `guidelines:` block to the agent YAML:

```yaml
guidelines:
  - condition: "The user expresses dissatisfaction with the response."
    action: "Acknowledge their frustration and ask for details."
  - condition: "The user asks to check their account status."
    action: "Look up their account using the get_account_status tool."
    tool: "get_account_status"
```

Rules:
- `condition` is required; provide at least one of `action` or `tool`.
- `display_name` is deprecated — omit it.
- Keep conditions specific; broad conditions fire too often and increase LLM complexity.

---

## Step 8 — Create the Model Policy (if needed)

Model policies let one named "virtual model" route across multiple real models using load-balancing or fallback strategies. Use them when reliability or cost-balancing across models is required.

Create `models/<policy_name>.yaml`:

```yaml
spec_version: v1
kind: model
name: my_model_policy
description: Fallback across two models on 503
display_name: My Model Policy
policy:
  strategy:
    mode: fallback          # options: fallback | loadbalance | single
    on_status_codes: [503]
  retry:
    attempts: 2
    on_status_codes: [503]
  targets:
    - model_name: virtual-model/google/gemini-2.0-flash
    - model_name: virtual-model/google/gemini-2.0-flash-lite
```

Import it and then reference the policy name as the `llm` value in your agent YAML:

```bash
orchestrate models policy import --file ${SCRIPT_DIR}/models/my_model_policy.yaml
```

```yaml
# in agents/my_agent.yaml
llm: my_model_policy
```

⚠️ Only **virtual models** (`virtual-model/<provider>/<model_id>`) are supported as targets. Direct provider references (e.g. `groq/openai/gpt-oss-120b`) are not allowed inside policies.

---

## Step 9 — Write main_flow.py (flows only)

Only needed if the project contains flows:

```python
import asyncio
from pathlib import Path
from <project_name>.tools.<flow_name> import build_my_flow

async def main():
    flow_def = await build_my_flow().compile_deploy()
    generated_folder = f"{Path(__file__).resolve().parent}/generated"
    flow_def.dump_spec(f"{generated_folder}/my_flow.json")
    await flow_def.invoke({"input_param": "test"}, debug=True)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Step 10 — Write import-all.sh

Import order matters: knowledge bases and model policies must be imported **before** agents.

```bash
#!/usr/bin/env bash

# orchestrate env activate local   # uncomment to target local Developer Edition
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# 1. Model policies (if any)
for policy in my_model_policy.yaml; do
  orchestrate models policy import --file ${SCRIPT_DIR}/models/${policy}
done

# 2. Knowledge bases (if any)
for kb in my_knowledge_base.yaml; do
  orchestrate knowledge-bases import -f ${SCRIPT_DIR}/knowledge-bases/${kb}
done

# 3. Python tools
for tool in my_tool.py; do
  orchestrate tools import -k python -f ${SCRIPT_DIR}/tools/${tool}
done

# 4. Flow tools
for flow in my_flow.py; do
  orchestrate tools import -k flow -f ${SCRIPT_DIR}/tools/${flow}
done

# 5. Agents
for agent in my_agent.yaml; do
  orchestrate agents import -f ${SCRIPT_DIR}/agents/${agent}
done
```

Then run: `chmod +x <project_name>/import-all.sh`

---

## Step 11 — Configure Channels (if needed)

Channels connect the agent to external messaging platforms. Each channel type requires its own credentials.

**Supported channel types:** `twilio_whatsapp`, `twilio_sms`, `byo_slack`, `webchat`, Microsoft Teams, Facebook Messenger, Genesys Bot Connector.

Create `channels/<channel_name>.yaml`:

```yaml
spec_version: v1
kind: channel
name: "WhatsApp Support"
description: "Customer support via WhatsApp"
channel: twilio_whatsapp
account_sid: "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
twilio_authentication_token: "${TWILIO_AUTH_TOKEN}"   # use env vars for secrets
```

Import against a specific agent and environment (`draft` or `live`):

```bash
orchestrate channels import \
  --agent-name my_agent \
  --env draft \
  --file ${SCRIPT_DIR}/channels/my_channel.yaml
```

Rules:
- One channel type per environment per agent (you can have WhatsApp + Slack, but not two WhatsApp channels).
- YAML/JSON files support **one** channel spec per file; Python files support multiple.
- Web chat uses a separate workflow — see `/webchat/overview` in the ADK docs.
- Never hard-code credentials; use environment variables.

---

## Step 12 — Write README.md

The README must include:
1. **Overview** — one paragraph describing the project
2. **Architecture Diagram** — `mermaid graph TB` showing Agent → Flow → Tool relationships, with coloured nodes
3. **Workflow Diagram** — `mermaid flowchart TD` showing the step-by-step data flow
4. **Usage** section — how to run `import-all.sh` and interact via Chat UI

---

## Step 13 — Validate

Run a quick sanity check:
```bash
cd <project_name> && python -c "from tools.<flow_name> import build_my_flow; print('OK')"
```

If the import fails, diagnose and fix before reporting completion.

# Role-Based Knowledge Visibility in watsonx Orchestrate

## Background

In watsonx Orchestrate, knowledge bases are workspace-level resources with **no built-in per-user or per-role document filtering**. Any user who can reach an agent gets the same knowledge corpus. Role-based knowledge segmentation requires an architectural workaround.

---

## Current WXO Knowledge Access Model

| Layer | What's available | Role support? |
|---|---|---|
| **Workspace membership** | Owner / Editor roles | ✅ Yes — but coarse (workspace in/out) |
| **Agent access** | Who can invoke the agent | ✅ Partial — via pre-invoke plug-ins |
| **Knowledge base content** | Documents returned from RAG retrieval | ❌ No — all users see the same corpus |
| **Collaborator agent access** | Which sub-agents the LLM can route to | ✅ Yes — via `RBAC_ONLY` pre-invoke plug-in |

---

## Approaches for Role-Based Knowledge Visibility in a Single Agent

### Option 1 — ✅ Best fit: External KB with `input_schema` + Dynamic Filtering

External knowledge bases (Elasticsearch, Milvus, OpenSearch, AstraDB) support `input_schema` with runtime `{placeholder}` substitution in filters. If an `input_schema` field name matches a context variable (e.g., injected via JWT), the context variable value is automatically injected at query time.

**How it works:**

```
JWT → injects user_role as context variable
       ↓
KB input_schema declares user_role field
       ↓
filter: { "term": { "doc_role": "{user_role}" } }  ← runtime substitution
       ↓
Only documents tagged for that role are retrieved
```

**YAML example (Elasticsearch):**

```yaml
spec_version: v1
kind: knowledge_base
name: role_filtered_kb
description: Company docs filtered by caller role
conversational_search_tool:
  query_source: Agent         # dynamic mode required
  input_schema:
    type: object
    properties:
      user_role:
        type: string
        description: "The user's role — manager, employee, or executive"
  index_config:
    - elastic_search:
        url: https://your-es.example.com
        index: company_docs
        result_filter:
          - term:
              metadata.allowed_role: '{user_role}'
        field_mapping:
          title: title
          body: body
```

**Requirements:**
- Documents must be tagged with `allowed_role` metadata at ingest time
- `query_source: Agent` (dynamic mode) is required for `input_schema` to work
- Only works with **external** KBs (Milvus, Elasticsearch, OpenSearch, AstraDB, CustomSearch)
- The built-in Milvus KB does **not** support `input_schema` / dynamic filtering

---

### Option 2 — ✅ Viable: MCP Tool as a Knowledge Proxy

A custom MCP server acts as a role-aware retrieval gateway. The agent calls a tool instead of a KB. IBM has a published tutorial for exactly this pattern: [Secure RBAC for MCP server access using context variables and OBO flow](https://developer.ibm.com/tutorials/secure-rbac-mcp-context-variables-obo-watsonx-orchestrate/).

**How it works:**

```
JWT → user_role injected as context variable
       ↓
Agent calls MCP tool: search_knowledge(query, user_role)
       ↓
MCP server enforces ACL, queries your vector store filtered by role
       ↓
Returns only permitted documents
```

**Pros:**
- Full code-level control over access logic (OBO flow, JWT validation, ACL checks)
- Works with any backend (your own vector DB, SharePoint, etc.)
- Auditable and extensible

**Cons:**
- You lose WXO's built-in RAG pipeline (query rewrite, confidence thresholds, citation handling)
- You build and host the MCP server yourself
- MCP tool calls don't benefit from `conversational_search_tool` generation quality improvements

---

### Option 3 — ✅ Pragmatic: `@tool` / `@flow` as a Knowledge Proxy

Same concept as MCP, but implemented as a WXO native Python `@tool`. The tool accepts `user_role` from context, queries an external vector DB or API, and returns filtered results.

```python
@tool
def search_company_docs(query: str, user_role: str) -> str:
    """Search company knowledge filtered by the caller's role.

    Args:
        query: The user's question.
        user_role: The caller's role (from JWT context).
    """
    results = my_vector_db.search(query, filter={"role": user_role})
    return format_results(results)
```

**Pros:**
- No external server to host — runs inside WXO
- Simpler than MCP for straightforward use cases

**Cons:**
- Same loss of built-in KB RAG pipeline
- Role enforcement is in Python code, not a data-layer filter

---

### Option 4 — ✅ Clean Isolation: Separate Agents per Role

Build distinct agents (e.g., `agent-hr-manager`, `agent-hr-employee`), each with its own scoped knowledge base. Use workspace membership or pre-invoke plug-ins to route users to the correct agent.

**Pros:**
- Clean separation — each role gets exactly its corpus
- No custom code required; uses native WXO KB pipeline fully

**Cons:**
- Agent proliferation at scale (N roles × M domains = many agents)
- Harder to maintain when knowledge overlaps between roles

---

## Decision Matrix

| Approach | Role filtering quality | Build effort | Stays in WXO KB pipeline | Requires external infra |
|---|---|---|---|---|
| **External KB + `input_schema`** | ✅ Native, filter at query time | Low | ✅ Yes | ✅ Yes (ES/Milvus/etc.) |
| **MCP server as proxy** | ✅ Full code control + auditable | High | ❌ No | ✅ Yes |
| **`@tool` / `@flow` proxy** | ✅ Full code control | Medium | ❌ No | Optional |
| **Separate agents per role** | ✅ Clean isolation | Medium | ✅ Yes | ❌ No |

---

## Recommendation

| Situation | Recommended approach |
|---|---|
| You can run Elasticsearch / Milvus / OpenSearch | **Option 1** — External KB + `input_schema` filter |
| You need full auditable RBAC with OBO / JWT enforcement | **Option 2** — MCP server proxy |
| Simple role split, few roles, low maintenance overhead | **Option 4** — Separate agents per role |
| You want WXO-native code, no external server | **Option 3** — `@tool` / `@flow` proxy |

> **Key principle:** Tag documents with `allowed_role` metadata at ingest time regardless of approach. Role enforcement at the data layer (vector filter) is always more reliable than relying on LLM behavioral guardrails.

---

## References

- [WXO ADK: Configuring dynamic input for external knowledge bases](https://developer.watson-orchestrate.ibm.com/knowledge_base/build_kb#configuring-dynamic-input-and-output-for-external-knowledge-bases)
- [WXO ADK: External knowledge base overview](https://developer.watson-orchestrate.ibm.com/knowledge_base/overview)
- [WXO ADK: Collaborator access control via pre-invoke plug-ins](https://developer.watson-orchestrate.ibm.com/plugins/plugins#collaborator-access-control)
- [WXO ADK: Context variables for embedded webchat (JWT)](https://developer.watson-orchestrate.ibm.com/webchat/context_variables)
- [IBM Tutorial: Secure RBAC for MCP server access using context variables and OBO flow](https://developer.ibm.com/tutorials/secure-rbac-mcp-context-variables-obo-watsonx-orchestrate/)
- [IBM Tutorial: Agent guardrails with watsonx Orchestrate plug-ins](https://developer.ibm.com/tutorials/ai-agents-guardrails-watsonx-orchestrate-plugins/)

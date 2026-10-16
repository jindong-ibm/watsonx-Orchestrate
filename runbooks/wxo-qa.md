# wxO Q&A

Sources: watsonx Orchestrate ADK docs, IBM Docs (watsonx Orchestrate base), and IBM support defects.

## 1. Is there a theoretical or observed ceiling to the number of simultaneous agents that Orchestrate can manage?

**No documented number.** I searched the ADK docs and the IBM Docs base product for a maximum count of concurrent agents, collaborators per supervisor, or concurrent runs per tenant. I found none.

### Documented limits

| Limit | Value | Scope | Configurable | Source |
|---|---|---|---|---|
| Agent loop model calls | 12 | Per agent turn | No, hard limit | [Understanding billing and usage tracking](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=entitlements-understanding-billing-usage-tracking) |
| LangGraph recursion traversals | 30 | Per agent turn | No, hard limit | Same page |
| Collaborator step counting | Restarts from 0 | Per collaborator invocation | No | Same page |

### Other relevant points

- **Collaborators are not capped, but there is a design guideline.** The [agent guidelines](https://developer.watson-orchestrate.ibm.com/agents/descriptions#guidelines-for-agents) say agents on LLaMA-based LLMs perform best with 10 or fewer tools or collaborators. They add that the figure "may vary for more powerful models."
- **Nesting depth is a recommendation, not a limit.** The [performance guide](https://developer.watson-orchestrate.ibm.com/tutorials/performance/performance-guide-v2-agent#4a-avoid-deep-agent-hierarchies) advises keeping hierarchies to 2-3 levels because each level adds its own reasoning loop.
- **Collaborators do not run in parallel.** An open IBM support defect, [DT456088](https://www.ibm.com/mysupport/s/defect/aCIgJ0000007WuPWAU/dt456088), says watsonx Orchestrate "does not support parallel execution of collaborators/tools" and that no configuration switches this on. That defect is still open and was filed against an IBM Developer article that implied otherwise. If it is accurate, the number of simultaneously active collaborators within one run is effectively one.
- **Concurrency across users is a platform matter.** The ADK scalability guide only advises multi-user load testing, noting that concurrency issues appear with 10+ concurrent users. There is no published per-tenant concurrency quota. The only rate controls I found are for MCP tool calls: 30 per minute per tool and 3000 per minute per tenant by default, on the AWS and IBM Cloud deployments ([Limiting MCP tool call rates](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=controls-limiting-mcp-tool-call-rates)).

**Bottom line:** For a firm number, the documentation doesn't answer it. You would need to ask IBM, or load-test your own tenant. Raise the open defect above with IBM at the same time.

## 2. Is there any method by which a supervisor agent can kill its own subagent process if it determines it no longer needs its results?

**No. I found no documented way for a supervisor agent to cancel or terminate a collaborator mid-run.**

- **No cancel feature in the agent spec.** The native agent schema (`collaborators`, `tools`, `style`, `llm_config` and so on) has no cancel, abort or stop-collaborator setting. The ReAct Core and Plan-Act style descriptions don't mention one either.
- **Cancel exists only as an outside API call.** There is a `POST /v1/orchestrate/runs/cancel/{run_id}` endpoint ([Cancel An Orchestrate Assistant Run](https://developer.watson-orchestrate.ibm.com/apis/orchestrate-agent/cancel-an-orchestrate-assistant-run)). It is a developer-facing API for the run you start from outside. The docs don't say it can stop an individual collaborator's sub-execution or that an agent can call it on a child.
- **Flows have a cancel, but only for the caller.** The [MCP workflows page](https://developer.watson-orchestrate.ibm.com/tools/flows/mcp_workflows#authorization-model) lists `cancel_flow`. The initiator of a flow instance can cancel it. That is again an outside-in control, not a supervisor-to-subagent one.
- **The step counter resets per collaborator.** Collaborator steps restart from 0 on each invocation. The supervisor's own 12-call and 30-traversal ceilings are the only built-in way a run ends, and they don't cancel anything on demand.

### Workarounds (none documented as a supported pattern)

1. **Use a flow instead of a collaborator agent.** Where you control the logic, a Branch node can skip downstream work once a result is no longer needed. The performance guide recommends this "Agent -> Flow -> Tools" shape for deterministic orchestration.
2. **Use a cancellable external agent or tool.** Put a tool in front of the long-running work that checks a shared flag and exits early. The supervisor sets the flag through another tool call. This is a custom cooperative-cancel pattern.
3. **Cancel from the client.** If the caller starts the run through the API, it can use the run-cancel endpoint. The supervisor can't trigger that itself.
4. **Use a plug-in.** Pre-invoke plug-ins can stop a collaborator from continuing (`continue_processing = False`). I only found this documented for access control ([Collaborator access control](https://developer.watson-orchestrate.ibm.com/plugins/plugins#collaborator-access-control)), so I would not rely on it for cancellation.

**Bottom line:** Ask IBM product management or support to confirm both points. In particular, ask whether a supervisor-initiated cancel of a collaborator is on the roadmap, and whether any tenant-level concurrency quotas exist.

## 3. Do wxO agents support async tool calls? (Flows are known to support async calls.)

**Short answer:** Yes, but the async support belongs to the tool type, not to the agent. The agent itself still waits for the result. Flows being async is confirmed.

### Flows: confirmed async

- The [flow overview](https://developer.watson-orchestrate.ibm.com/tools/flows/overview) says flows "run asynchronously" because they can take several seconds.
- You can start one asynchronously through the API (`POST /v1/orchestrate/flows/{flow_id}/run/async`). It returns an `instance_id` right away, and you poll for status or pass a `callbackUrl` header ([API reference](https://developer.watson-orchestrate.ibm.com/apis/flows/asynchronously-run-the-latest-flow-version)).
- Flows exposed as MCP tools have a `run_flow_async__<flow_name>` variant that returns an `instance_id` immediately. You then call `query_flow__<flow_name>` for status ([MCP workflows](https://developer.watson-orchestrate.ibm.com/tools/flows/mcp_workflows#asynchronous-claim‑check)).

### Agents: async tool calls through specific tool types

The [OpenAPI tool docs](https://developer.watson-orchestrate.ibm.com/tools/create_openapi_tool#asynchronous-tools-with-callbacks) call OpenAPI tools "one of the two tool types that support asynchronous operations." The other type isn't named on that page. The tool API schemas include `acknowledgement` and `is_async` fields only for the OpenAPI and flow bindings, so I infer it is flows.

| Tool type | Async support | Notes |
|---|---|---|
| **OpenAPI tool** | Yes | Your spec must have a header parameter named exactly `callbackUrl`, plus a `callbacks` block. The callback response must be `application/json`. Async tools can exceed the **40-second** timeout that synchronous tools have in the UI. |
| **Flow (agentic workflow)** | Yes | An agent can call a flow as a tool. |
| **Python tool** | No platform async | You can use `async def` and `asyncio.gather()` inside the tool, but that only runs I/O concurrently within the call. The tool still has a hard **2-minute** timeout (about 90 seconds in practice). IBM's guidance is to use an OpenAPI tool for long-running work. |
| **Langflow tool** | No | Langflow "does not support asynchronous execution." The agent returns an error if it takes longer than 120 seconds. |

### What "async" means for the agent

- **The agent doesn't carry on with other work while an async tool runs.** The docs show that an async flow pauses the conversation.
  - The stream emits a `flow.slot.listen` event and then ends.
  - The thread status becomes `async_wait`, or `async_slot_request` if the flow needs user input.
  - When the flow finishes, new messages are added and the status returns to `ready`.
  - Your application has to poll the thread during this time. The embedded chat widget does that for you. See [Handling async flows in API-driven chat](https://developer.watson-orchestrate.ibm.com/tutorials/tutorial_api_async_flow).
- **Run statuses include `async_wait` and `async_completed`**, so the platform tracks the async state separately from `running`.
- **Callback endpoint.** The async tool posts its result to `POST /v1/tools/{tenant_id}/callback/{correlation_id}` ([reference](https://developer.watson-orchestrate.ibm.com/apis/tools/post-tool-response-from-the-async-tool)).
- **Developer Edition limitation.** Local async tools can't reach a callback URL, so you must set `CALLBACK_HOST_URL` to a public endpoint such as ngrok ([known issues](https://developer.watson-orchestrate.ibm.com/release/knownissues)).
- **Callback flows.** Flows used as callbacks can't contain user-activity nodes. IBM recommends OpenAPI tools as the callback mechanism.

### Agent-to-agent async (separate feature)

External agents using the A2A protocol can send asynchronous updates by push notification (`pushNotifications: true`), for tasks that run for minutes, hours or days. This is marked **technical preview** in the [connect agent docs](https://developer.watson-orchestrate.ibm.com/agents/connect_agent).

### What I couldn't confirm

I found no documentation saying the supervisor can fire an async tool and keep reasoning or calling other tools until the result returns. The documented behavior is that the thread waits. Combined with sections 1 and 2 (no parallel collaborators, no cancel for a running subagent), the supervisor stays blocked until the async tool completes.

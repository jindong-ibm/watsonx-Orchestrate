# wxO Agent Review Tool

An intelligent agent review system for watsonx Orchestrate that analyzes AI agent configurations, validates live deployments, and enforces quality standards in CI/CD pipelines.

---

## Overview

This tool helps identify anti-patterns and optimization opportunities in AI agent implementations across six critical areas:

1. **Prompt Design** — Avoiding monolithic mega-prompts and under-specified instructions
2. **System Architecture** — Separating agent reasoning from deterministic business logic
3. **Knowledge Management** — Ensuring RAG systems have clean, structured knowledge
4. **Testing & Resilience** — Moving beyond happy-path testing to real-world scenarios
5. **Performance Design** — Treating latency as an architecture constraint
6. **Context Management** — Optimizing token usage and avoiding context bloat

---

## Tools (7 total)

| Tool | Description |
|---|---|
| `analyze_agent_config` | Deep static analysis of agent YAML — detects 23+ anti-patterns and produces a scored report |
| `generate_recommendations` | Converts analysis results into phased, prioritized action plans |
| `compare_agents` | Compares multiple agent configs side-by-side; finds common issues and best-practice leaders |
| `validate_live_agent` | Validates a deployed agent against a live wxO environment using the `orchestrate` CLI |
| `validate_tool_schemas` | AST-based static analysis of Python `@tool` functions — checks annotations, docstrings, bare excepts |
| `analyze_flow` | AST-based static analysis of `@flow` functions — checks missing schemas, error handlers, deep chains |
| `export_report` | Renders any analysis result as `json`, `markdown`, or `html`; writes to disk; stamps a unique report ID |

---

## Installation

### Prerequisites

- Python 3.9+
- watsonx Orchestrate ADK (`ibm-watsonx-orchestrate` ≥ 2.10.0)
- `orchestrate` CLI authenticated against your wxO environment

### Deploy to wxO

```bash
cd agent_review_tool
./import-all.sh
```

`import-all.sh` imports all 7 tools and the agent configuration into the currently authenticated wxO environment.

---

## Usage

### 1 · Analyze a single agent (static)

```python
from tools.analyze_agent_config import analyze_agent_config

# From file
result = analyze_agent_config(config_path="path/to/agent.yaml")

# From inline YAML string
with open("agent.yaml") as f:
    content = f.read()
result = analyze_agent_config(config_content=content)

print(f"Score: {result['overall_score']}/100  Grade: {result['grade']}")
print(f"Critical: {result['critical_issues']}  High: {result['high_priority']}")
```

### 2 · Generate recommendations

```python
from tools.generate_recommendations import generate_recommendations

recs = generate_recommendations(analysis_results=result)

print(f"Immediate actions: {recs['summary']['immediate_actions']}")
for action in recs['priority_actions'][:3]:
    print(f"  [{action['category']}] {action['anti_pattern']}: {action['action'][:80]}…")
```

### 3 · Compare multiple agents

```python
from tools.compare_agents import compare_agents

comparison = compare_agents(agent_configs=[
    "agents/agent_a.yaml",
    "agents/agent_b.yaml",
    "agents/agent_c.yaml",
])

print(f"Leader: {comparison['best_practices_leader']['name']}  "
      f"Score: {comparison['best_practices_leader']['score']}/100")
for issue in comparison['common_issues']:
    print(f"  Shared: {issue['anti_pattern']} ({issue['occurrences']} agents)")
```

### 4 · Validate a live deployment

```python
from tools.validate_live_agent import validate_live_agent

status = validate_live_agent(agent_name="my-support-agent")

print(f"Status: {status['overall_status']}")
for check in status['checks']:
    icon = "✅" if check['status'] == 'pass' else "❌"
    print(f"  {icon} {check['check']}: {check['message']}")
```

### 5 · Validate Python @tool schemas

```python
from tools.validate_tool_schemas import validate_tool_schemas

result = validate_tool_schemas(tools_directory="tools/")
# or a single file:
result = validate_tool_schemas(tools_file="tools/my_tool.py")

print(f"Status: {result['overall_status']}  Tools found: {result['tools_found']}")
for finding in result['findings']:
    print(f"  [{finding['severity'].upper()}] {finding['function']}:{finding['line']} — {finding['issue']}")
```

### 6 · Analyze @flow agentic workflows

```python
from tools.analyze_flow import analyze_flow

result = analyze_flow(flows_directory="tools/")

print(f"Status: {result['overall_status']}  Flows found: {result['flows_found']}")
for finding in result['findings']:
    print(f"  [{finding['severity'].upper()}] {finding['function']} — {finding['issue']}")
```

### 7 · Export a shareable report

```python
from tools.export_report import export_report

# Render as markdown and write to disk
report = export_report(
    analysis=result,
    report_format="markdown",     # 'json' | 'markdown' | 'html'
    output_path="reports/review.md",
)

print(f"Report ID: {report['report_id']}")
print(f"Written to: {report['output_path']}")
```

Report formats:

| Format | Best for |
|---|---|
| `json` | CI artifact storage, programmatic consumption |
| `markdown` | GitHub/GitLab MRs, wikis, pull request comments |
| `html` | Browser viewing, email distribution, IBM Support attachments |

Every report is stamped with a `report_id` (ISO timestamp + content hash) for correlation with IBM Support tickets.

---

## CI/CD Gate — `ci_gate.py`

`ci_gate.py` is a **standalone script** (zero ADK runtime dependency beyond PyYAML) that enforces agent quality thresholds in CI/CD pipelines.

### Usage

```bash
python ci_gate.py <agent_yaml_path> [options]
```

### Options

| Option | Default | Description |
|---|---|---|
| `--min-score INT` | `70` | Minimum acceptable overall score |
| `--max-critical INT` | `0` | Maximum critical findings allowed |
| `--max-high INT` | `3` | Maximum high-severity findings allowed |
| `--format json\|markdown\|html` | `markdown` | Report format written on gate failure |
| `--report-dir DIR` | `.` | Directory to write the report into |
| `--strict` | off | Fail on **any** finding (ignores other limits) |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All thresholds met — safe to deploy |
| `1` | One or more thresholds exceeded — block deployment |
| `2` | Input error (file not found, parse failure) |

### Examples

```bash
# Basic quality gate (default thresholds: score ≥ 70, critical = 0, high ≤ 3)
python ci_gate.py agents/my_agent.yaml

# Strict production gate
python ci_gate.py agents/my_agent.yaml --min-score 85 --max-critical 0 --max-high 1

# Zero-tolerance gate for critical agents
python ci_gate.py agents/my_agent.yaml --strict --format html --report-dir reports/

# Generate a JSON report for artifact upload
python ci_gate.py agents/my_agent.yaml --format json --report-dir $CI_ARTIFACTS_DIR
```

### GitHub Actions integration

```yaml
- name: Agent quality gate
  run: python agent_review_tool/ci_gate.py agents/my_agent.yaml --min-score 80 --max-critical 0

- name: Upload review report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: agent-review-report
    path: agent-review-*.md
```

### GitLab CI integration

```yaml
agent-quality-gate:
  script:
    - python ci_gate.py agents/my_agent.yaml --min-score 80 --format html --report-dir reports/
  artifacts:
    paths:
      - reports/
    when: always
```

---

## Scoring Model

Scores are computed from 100 by deducting points per finding, with per-category and global caps, then partially offset by bonuses for good practices.

### Deductions

| Severity | Points deducted |
|---|---|
| Critical | 15 |
| High | 10 |
| Medium | 3 |
| Low | 0 |

- **Per-category cap**: at most 20 points deducted per category
- **Global deduction cap**: at most 70 points deducted in total
- **Net score**: `max(0, min(100, 100 − (total_deductions − bonuses)))`

### Bonuses (reduce deductions, do not inflate above 100)

| Condition | Bonus points |
|---|---|
| `error_handling` config key present | +5 |
| `validation` config key present | +5 |
| `guardrails` config key present | +5 |
| `retry` or `fallback` config key present | +5 |
| Tool count in 3–8 range | +5 |
| Prompt length in 100–1000 chars | +5 |
| Maximum total bonus | +15 |

### Grade table

| Score | Grade |
|---|---|
| 90–100 | A (Excellent) |
| 80–89 | B (Good) |
| 70–79 | C (Fair) |
| 60–69 | D (Needs Improvement) |
| 0–59 | F (Critical Issues) |

---

## Anti-Patterns Detected (23+)

### Prompt Design
- **Monolithic Mega-Prompt** — instructions > 2 000 characters
- **Over-Constrained Prompting** — > 10 constraint keywords in prompt
- **Under-Specified Prompt** — < 100 chars with > 3 tools
- **Over-Specialized Agent** — > 10 tools attached

### System Architecture
- **Agent-as-Business-Process Fallacy** — business logic (approvals, compliance rules) in prompt
- **Tool Soup** — > 15 tools, degrading selection accuracy
- **Tool Data Overload** — tool definition payload > 5 000 characters

### Knowledge Management
- **Unstructured Data Assumption** — KB missing `description`
- **Empty Knowledge Base** — KB has no `documents`, `path`, or `urls`
- **RAG Will Fix Disorganized Knowledge** — prompt implies RAG to handle messy data
- **Over-Retrieved Knowledge** — `top_k` > 10

### Testing & Resilience
- **Happy Path Engineering** — no `error_handling`, `retry`, or `fallback` config
- **Demo-Grade Agent in Production** — no `validation` or `guardrails`

### Performance
- **Responsiveness Afterthought** — ≥ 3 planning keywords in prompt
- **Excessive Iterations** — `max_iterations` > 10
- **Firehose Effect** — `max_tokens` or `context_window` > 8 000

### Context Management
- **Unbounded Execution Cost** — instructions > 3 000 chars or tool schemas > 10 000 chars
- **Give the Model Everything** — "all information" / "everything" in prompt
- **Over-Retrieved Knowledge** — excessive KB retrieval

### @tool Schema (via `validate_tool_schemas`)
- Missing type annotations
- `Any` typed parameters
- Multiple `AgentRun` parameters
- Bare `except:` clauses
- Missing docstring

### @flow Analysis (via `analyze_flow`)
- Missing `name` or `input_schema` on flow
- No `return` statement
- Tool/prompt nodes without `error_handler_config`
- Deep sequential chains (> 10 nodes)
- `foreach` without `.policy()`
- Document nodes missing `enable_review`

---

## Project Structure

```
agent_review_tool/
├── import-all.sh                      # Deploy all 7 tools + agent to wxO
├── ci_gate.py                         # Standalone CI/CD quality gate script
├── agents/
│   └── agent_review_agent.yaml        # wxO agent configuration
├── knowledge-bases/
│   └── agent_antipatterns_kb.yaml     # Anti-patterns knowledge base
├── examples/
│   ├── example_agent_good.yaml        # Well-designed reference agent
│   ├── example_agent_bad.yaml         # Poorly-designed reference agent
│   └── test_review.py                 # End-to-end test suite
└── tools/
    ├── __init__.py
    ├── analyze_agent_config.py        # Core analysis engine (Gap #2, #4, #5)
    ├── generate_recommendations.py    # Phased recommendation generator
    ├── compare_agents.py              # Multi-agent comparison (Gap #8)
    ├── validate_live_agent.py         # Live deployment validator (Gap #3)
    ├── validate_tool_schemas.py       # @tool AST analysis (Gap #6)
    ├── analyze_flow.py                # @flow AST analysis (Gap #7)
    └── export_report.py               # Multi-format report exporter (Gap #9)
```

---

## Natural Language Queries (wxO Chat)

Once deployed, interact with the agent through chat:

- *"Analyze my agent configuration for anti-patterns"*
- *"What are the top issues in this agent YAML?"*
- *"Compare these three agent configurations and tell me the best practices leader"*
- *"Validate that my customer-support agent is correctly deployed"*
- *"Check the tool schemas in my tools/ directory for type annotation issues"*
- *"Export my analysis as an HTML report for IBM Support"*

---

## References

- [AI Agent Anti-Patterns: Six Hard-Won Lessons from Production](https://achan2013.medium.com/ai-agent-anti-patterns-six-hard-won-lessons-e9de592fd7d6)
- [AI Agent Anti-Patterns Part 1: Architectural Pitfalls](https://achan2013.medium.com/ai-agent-anti-patterns-part-1-architectural-pitfalls-that-break-enterprise-agents-before-they-32d211dded43)
- [AI Agent Anti-Patterns Part 2: Tooling, Observability and Scale Traps](https://achan2013.medium.com/ai-agent-anti-patterns-part-2-tooling-observability-and-scale-traps-in-enterprise-agents-42a451ea84ec)
- [AI Agent Anti-Patterns Part 3: Knowledge & Document Processing](https://achan2013.medium.com/ai-agent-anti-patterns-part-3-knowledge-document-processing-0caf472856ff)

---

## Contributing

1. Add detection logic to the appropriate `_analyze_*` function in [`tools/analyze_agent_config.py`](tools/analyze_agent_config.py)
2. Update the knowledge base in [`knowledge-bases/agent_antipatterns_kb.yaml`](knowledge-bases/agent_antipatterns_kb.yaml)
3. Add corresponding recommendations in [`tools/generate_recommendations.py`](tools/generate_recommendations.py)
4. Run `examples/test_review.py` to validate

---

*Made with IBM Bob — wxO Agent Review Tool*

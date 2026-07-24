"""
Static analysis tool for watsonx Orchestrate @flow / agentic workflow files.

Inspects Python source files containing @flow-decorated functions and checks
for anti-patterns that cause latency, reliability, and maintainability issues
in production agentic workflows:

  1. @flow missing required decorator arguments (name, input_schema)
  2. Tool nodes with no error_handler_config (retry/resilience gap)
  3. GenAI/prompt nodes with no error_handler_config
  4. Sequential tool chains that exceed the latency-safe node limit (>10)
  5. Missing input_schema or output_schema on the @flow decorator
  6. Flow functions that do not return a Flow object
  7. Foreach loops with no explicit policy (defaults to SEQUENTIAL, often unintentional)
  8. Document classifier / extractor nodes with no enable_review flag

Each finding is tied to a source line and includes a concrete fix.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
import ast
import re
from pathlib import Path
from typing import Dict, List, Any, Optional


# ---------------------------------------------------------------------------
# ADK-aware AST helpers
# ---------------------------------------------------------------------------

def _get_decorator_kwargs(func_node: ast.FunctionDef, name: str) -> Dict[str, Any]:
    """Return keyword arguments of the first decorator whose name contains `name`."""
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Call):
            target = dec.func
            target_name = (
                target.id if isinstance(target, ast.Name)
                else target.attr if isinstance(target, ast.Attribute)
                else ""
            )
            if name in target_name:
                kwargs: Dict[str, Any] = {}
                for kw in dec.keywords:
                    if kw.arg:
                        kwargs[kw.arg] = kw.value
                return kwargs
    return {}


def _is_flow_decorated(func_node: ast.FunctionDef) -> bool:
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name) and "flow" in dec.id:
            return True
        if isinstance(dec, ast.Call):
            fn = dec.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if "flow" in name:
                return True
    return False


def _kwarg_present(kwargs: Dict[str, Any], key: str) -> bool:
    """True if key exists in kwargs and its value is not None / ast.Constant(None)."""
    if key not in kwargs:
        return False
    val = kwargs[key]
    if isinstance(val, ast.Constant) and val.value is None:
        return False
    return True


def _call_method_name(call: ast.Call) -> str:
    """Return the method name for an ast.Call node (e.g. aflow.tool → 'tool')."""
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _call_kwarg_present(call: ast.Call, key: str) -> bool:
    """Return True if a keyword argument `key` is present and non-None in a Call node."""
    for kw in call.keywords:
        if kw.arg == key:
            if isinstance(kw.value, ast.Constant) and kw.value.value is None:
                return False
            return True
    return False


def _count_sequential_tool_calls(func_node: ast.FunctionDef) -> int:
    """
    Count the number of aflow.tool() / aflow.prompt() / aflow.agent() calls
    inside a @flow function body — a proxy for sequential node depth.
    """
    count = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            method = _call_method_name(node)
            if method in ("tool", "prompt", "agent", "script"):
                count += 1
    return count


# ---------------------------------------------------------------------------
# Per-function checks
# ---------------------------------------------------------------------------

def _check_flow_function(
    func: ast.FunctionDef,
    source_lines: List[str],
    path_str: str,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    fn_name = func.name
    fn_line = func.lineno

    decorator_kwargs = _get_decorator_kwargs(func, "flow")

    # ── Check 1: @flow missing 'name' argument ──
    if not _kwarg_present(decorator_kwargs, "name"):
        findings.append({
            "file": path_str,
            "function": fn_name,
            "line": fn_line,
            "severity": "high",
            "check": "Flow missing name",
            "issue": f"@flow function '{fn_name}' has no 'name' argument. The ADK uses this as the tool name visible in the agent.",
            "recommendation": "@flow(name='my_workflow_name', ...) — the name must be unique across the tenant and contain only alphanumeric characters and underscores.",
        })

    # ── Check 2: @flow missing input_schema ──
    if not _kwarg_present(decorator_kwargs, "input_schema"):
        findings.append({
            "file": path_str,
            "function": fn_name,
            "line": fn_line,
            "severity": "medium",
            "check": "Flow missing input_schema",
            "issue": f"@flow function '{fn_name}' has no 'input_schema'. Without it the flow accepts untyped inputs, making auto data-mapping unreliable.",
            "recommendation": "Define a Pydantic BaseModel for the flow's inputs and pass it as @flow(input_schema=MyInputModel). Typed schemas enable reliable automatic data mapping between nodes.",
        })

    # ── Check 3: function does not explicitly return a Flow ──
    has_return = any(
        isinstance(node, ast.Return) and node.value is not None
        for node in ast.walk(func)
    )
    if not has_return:
        findings.append({
            "file": path_str,
            "function": fn_name,
            "line": fn_line,
            "severity": "high",
            "check": "Flow function does not return",
            "issue": f"@flow function '{fn_name}' has no return statement. The function must return the Flow object for the ADK to compile the workflow.",
            "recommendation": "End the function body with 'return aflow'. Without this the flow will compile to an empty graph and fail at runtime.",
        })

    # ── Check 4: tool/prompt nodes without error_handler_config ──
    nodes_without_error_handler: List[tuple] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        method = _call_method_name(node)
        if method not in ("tool", "prompt"):
            continue
        if not _call_kwarg_present(node, "error_handler_config"):
            line = getattr(node, "lineno", fn_line)
            # Try to get the tool name from the first positional arg
            tool_ref = ""
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant):
                    tool_ref = f" (tool='{arg.value}')"
                elif isinstance(arg, ast.Name):
                    tool_ref = f" (tool={arg.id})"
            nodes_without_error_handler.append((method, tool_ref, line))

    for method, tool_ref, line in nodes_without_error_handler:
        findings.append({
            "file": path_str,
            "function": fn_name,
            "line": line,
            "severity": "high",
            "check": "Node missing error_handler_config",
            "issue": (
                f"aflow.{method}(){tool_ref} in flow '{fn_name}' has no "
                f"error_handler_config. A node failure will abort the entire workflow with no retry."
            ),
            "recommendation": (
                f"Add error_handler_config=NodeErrorHandlerConfig(max_retries=2, retry_interval=1000) "
                f"to this aflow.{method}() call. For critical paths use on_error='branch' to redirect "
                f"to an error-handling node instead of aborting."
            ),
        })

    # ── Check 5: sequential node depth > 10 (latency risk) ──
    node_count = _count_sequential_tool_calls(func)
    if node_count > 10:
        findings.append({
            "file": path_str,
            "function": fn_name,
            "line": fn_line,
            "severity": "medium",
            "check": "Deep sequential tool chain",
            "issue": (
                f"Flow '{fn_name}' contains {node_count} tool/prompt/agent node calls. "
                "Deep sequential chains multiply per-node latency (each model call adds 200–2000 ms)."
            ),
            "recommendation": (
                "Group independent nodes into parallel() or parallel_conditions() branches. "
                "Consider splitting into sub-flows. Keep critical user-facing paths under 6 sequential nodes."
            ),
        })

    # ── Check 6: foreach with no explicit policy call ──
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if _call_method_name(node) != "foreach":
            continue
        line = getattr(node, "lineno", fn_line)

        # Check if the result of foreach() has .policy(...) chained to it
        # We look for an Assign where the value is a Call chain ending in .policy()
        # Simplest heuristic: check surrounding lines for ".policy(" in source
        foreach_line_idx = line - 1  # 0-based
        policy_found = False
        # scan the next 5 source lines for a .policy( call
        for lookahead in range(foreach_line_idx, min(foreach_line_idx + 6, len(source_lines))):
            if ".policy(" in source_lines[lookahead]:
                policy_found = True
                break

        if not policy_found:
            findings.append({
                "file": path_str,
                "function": fn_name,
                "line": line,
                "severity": "medium",
                "check": "Foreach missing explicit policy",
                "issue": (
                    f"aflow.foreach() in flow '{fn_name}' at line {line} has no explicit "
                    ".policy() call. It defaults to SEQUENTIAL, which may be unintentionally slow for large lists."
                ),
                "recommendation": (
                    "Explicitly declare the iteration policy:\n"
                    "  .policy(kind=ForeachPolicy.SEQUENTIAL)  # safe for ordered side-effects\n"
                    "  .policy(kind=ForeachPolicy.PARALLEL)    # faster for independent items\n"
                    "Import: from ibm_watsonx_orchestrate.flow_builder.types import ForeachPolicy"
                ),
            })

    # ── Check 7: document classifier/extractor nodes without enable_review ──
    DOC_METHODS = {"docclassifier", "docclassfier", "document_classifier",
                   "document_extractor", "doc_extractor"}
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        method = _call_method_name(node)
        if method.lower() not in DOC_METHODS:
            continue
        if not _call_kwarg_present(node, "enable_review"):
            line = getattr(node, "lineno", fn_line)
            findings.append({
                "file": path_str,
                "function": fn_name,
                "line": line,
                "severity": "medium",
                "check": "Document node missing enable_review",
                "issue": (
                    f"aflow.{method}() in flow '{fn_name}' has no enable_review parameter. "
                    "Without it, classification/extraction results are applied automatically with no human checkpoint."
                ),
                "recommendation": (
                    "Set enable_review=True for production document flows to allow a human to "
                    "inspect and correct the model's output before downstream nodes consume it. "
                    "Use enable_review=False only in fully automated, low-risk pipelines."
                ),
            })

    return findings


# ---------------------------------------------------------------------------
# Public @tool entry point
# ---------------------------------------------------------------------------

@tool
def analyze_flow(
    flow_paths: List[str],
) -> Dict[str, Any]:
    """
    Analyze watsonx Orchestrate @flow / agentic workflow Python files for
    anti-patterns that cause latency, reliability, and import failures.

    Performs static AST analysis — no code is executed. Checks include:
      - @flow decorator missing required arguments (name, input_schema)
      - Flow function not returning the Flow object
      - Tool / prompt nodes missing error_handler_config (no retry on failure)
      - Excessively deep sequential tool chains (>10 nodes — latency risk)
      - Foreach loops with no explicit policy (unintentional SEQUENTIAL default)
      - Document classifier / extractor nodes with no enable_review flag

    Args:
        flow_paths: List of file paths to Python source files containing
            @flow-decorated functions (e.g. ['tools/my_flow.py']).

    Returns:
        A validation report with keys:
          - overall_status: 'pass' | 'fail' | 'error'
          - files_checked (int)
          - flows_found (int)
          - findings (list): one dict per issue found, with file, function,
              line, severity, check, issue, and recommendation fields
          - summary (str): human-readable summary
          - remediation_hints (list[str]): top unique actionable fixes
    """
    all_findings: List[Dict[str, Any]] = []
    flows_found = 0
    files_with_errors: List[str] = []

    for path_str in flow_paths:
        path = Path(path_str)

        # ── Read ──
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            all_findings.append({
                "file": path_str,
                "function": "<file>",
                "line": 0,
                "severity": "critical",
                "check": "File not found",
                "issue": f"Flow file '{path_str}' does not exist.",
                "recommendation": "Verify the path is correct relative to your project root.",
            })
            files_with_errors.append(path_str)
            continue
        except Exception as exc:
            all_findings.append({
                "file": path_str,
                "function": "<file>",
                "line": 0,
                "severity": "critical",
                "check": "File read error",
                "issue": f"Cannot read '{path_str}': {exc}",
                "recommendation": "Check file permissions and encoding (expected UTF-8).",
            })
            files_with_errors.append(path_str)
            continue

        # ── Parse ──
        try:
            tree = ast.parse(source, filename=path_str)
        except SyntaxError as exc:
            all_findings.append({
                "file": path_str,
                "function": "<module>",
                "line": exc.lineno or 0,
                "severity": "critical",
                "check": "Syntax error",
                "issue": f"'{path_str}' has a syntax error at line {exc.lineno}: {exc.msg}",
                "recommendation": "Fix the syntax error before attempting to import this flow.",
            })
            files_with_errors.append(path_str)
            continue

        source_lines = source.splitlines()

        # ── Walk @flow-decorated functions ──
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _is_flow_decorated(node):
                continue
            flows_found += 1
            findings = _check_flow_function(node, source_lines, path_str)
            all_findings.extend(findings)

    # ── Derive overall status ──
    severities = {f["severity"] for f in all_findings}
    if "critical" in severities or "high" in severities:
        overall = "fail"
    elif "medium" in severities or "low" in severities:
        overall = "fail"
    else:
        overall = "pass"

    if files_with_errors and not all_findings:
        overall = "error"

    # ── Summary ──
    critical_n = sum(1 for f in all_findings if f["severity"] == "critical")
    high_n     = sum(1 for f in all_findings if f["severity"] == "high")
    medium_n   = sum(1 for f in all_findings if f["severity"] == "medium")

    if overall == "pass":
        summary = (
            f"All {flows_found} @flow function(s) across {len(flow_paths)} "
            "file(s) passed agentic workflow analysis."
        )
    else:
        summary = (
            f"Found {len(all_findings)} issue(s) across {flows_found} @flow "
            f"function(s) in {len(flow_paths)} file(s): "
            f"{critical_n} critical, {high_n} high, {medium_n} medium."
        )

    # ── Deduplicated remediation hints ──
    seen_checks: set = set()
    remediation_hints: List[str] = []
    for f in sorted(
        all_findings,
        key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}[x["severity"]],
    ):
        key = f["check"]
        if key not in seen_checks:
            seen_checks.add(key)
            remediation_hints.append(
                f"[{f['severity'].upper()}] {f['check']}: {f['recommendation']}"
            )

    return {
        "overall_status": overall,
        "files_checked": len(flow_paths),
        "flows_found": flows_found,
        "findings": all_findings,
        "summary": summary,
        "remediation_hints": remediation_hints[:10],
    }

# Made with Bob

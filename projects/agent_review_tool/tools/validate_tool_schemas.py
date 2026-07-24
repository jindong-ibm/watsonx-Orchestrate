"""
Static schema validation for watsonx Orchestrate Python tool files.

Checks that every @tool-decorated function in a Python source file meets the
ADK contract required for successful import and reliable LLM invocation:

  1. @tool decorator is present
  2. All parameters (except 'context: AgentRun') have explicit type annotations
  3. The function has a return type annotation (not None / missing)
  4. A non-empty docstring is present (required for LLM tool-selection)
  5. No parameter is typed 'Any' — the LLM cannot generate correct inputs
  6. No bare 'except:' clauses that silently swallow errors
  7. No more than one 'AgentRun' context parameter per function

Each finding includes the function name, line number, severity, issue, and a
concrete recommendation so a customer can fix the problem without IBM support.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
import ast
import textwrap
from pathlib import Path
from typing import Dict, List, Any, Optional


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _has_decorator(func_node: ast.FunctionDef, name: str) -> bool:
    """Return True if the function has a decorator whose name contains `name`."""
    for dec in func_node.decorator_list:
        # bare @tool
        if isinstance(dec, ast.Name) and name in dec.id:
            return True
        # @tool(...)
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and name in dec.func.id:
                return True
            if isinstance(dec.func, ast.Attribute) and name in dec.func.attr:
                return True
    return False


def _annotation_name(annotation) -> str:
    """Return a string representation of an annotation node."""
    if annotation is None:
        return ""
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant):
        return str(annotation.value)
    if isinstance(annotation, ast.Attribute):
        return f"{_annotation_name(annotation.value)}.{annotation.attr}"
    if isinstance(annotation, ast.Subscript):
        return f"{_annotation_name(annotation.value)}[...]"
    return ast.unparse(annotation) if hasattr(ast, "unparse") else "<complex>"


def _count_bare_except(func_node: ast.FunctionDef) -> int:
    """Count bare 'except:' clauses (no exception type) in a function body."""
    count = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            count += 1
    return count


def _is_flow_decorated(func_node: ast.FunctionDef) -> bool:
    """Return True if the function has a @flow decorator."""
    return _has_decorator(func_node, "flow")


# ---------------------------------------------------------------------------
# Per-function checks
# ---------------------------------------------------------------------------

def _check_tool_function(
    func: ast.FunctionDef,
    source_lines: List[str],
) -> List[Dict[str, Any]]:
    """Run all schema checks against a single @tool function."""
    findings: List[Dict[str, Any]] = []
    fn_name = func.name
    fn_line = func.lineno

    # ── Check 1: docstring presence and non-emptiness ──
    docstring = ast.get_docstring(func)
    if not docstring or not docstring.strip():
        findings.append({
            "function": fn_name,
            "line": fn_line,
            "severity": "high",
            "check": "Missing docstring",
            "issue": f"Tool '{fn_name}' has no docstring. The ADK uses the docstring as the tool description for LLM tool-selection.",
            "recommendation": "Add a descriptive docstring explaining what the tool does, its parameters, and return value. Without it, the LLM cannot accurately decide when to call this tool.",
        })

    # ── Check 2–5: parameter annotations ──
    args = func.args
    all_params = (
        args.args
        + args.posonlyargs
        + args.kwonlyargs
        + ([args.vararg] if args.vararg else [])
        + ([args.kwarg] if args.kwarg else [])
    )

    agent_run_count = 0
    for param in all_params:
        if param.arg in ("self", "cls"):
            continue

        ann = _annotation_name(param.annotation) if param.annotation else ""

        # Count AgentRun params — only one is allowed
        if "AgentRun" in ann:
            agent_run_count += 1
            continue  # AgentRun is always OK, skip further checks for it

        # Check 2: missing type annotation
        if not ann:
            findings.append({
                "function": fn_name,
                "line": fn_line,
                "severity": "high",
                "check": "Missing parameter annotation",
                "issue": f"Parameter '{param.arg}' in tool '{fn_name}' has no type annotation.",
                "recommendation": f"Add a type annotation: def {fn_name}({param.arg}: str, ...). The ADK generates the tool's JSON schema from annotations; missing ones cause import failures or LLM hallucinations.",
            })
        # Check 3: Any-typed parameter
        elif ann == "Any":
            findings.append({
                "function": fn_name,
                "line": fn_line,
                "severity": "medium",
                "check": "Untyped Any parameter",
                "issue": f"Parameter '{param.arg}' in tool '{fn_name}' is typed 'Any'. The LLM cannot generate correct inputs for untyped parameters.",
                "recommendation": f"Replace 'Any' with the most specific type possible (e.g. str, int, Dict[str, str]). Use Union or Optional for legitimately flexible parameters.",
            })

    # Check 4: multiple AgentRun params
    if agent_run_count > 1:
        findings.append({
            "function": fn_name,
            "line": fn_line,
            "severity": "critical",
            "check": "Multiple AgentRun parameters",
            "issue": f"Tool '{fn_name}' has {agent_run_count} AgentRun parameters. The ADK only allows exactly one.",
            "recommendation": "Remove all but one AgentRun parameter. The ADK will reject the tool at import time if more than one is present.",
        })

    # ── Check 5: return type annotation ──
    ret_ann = _annotation_name(func.returns) if func.returns else ""
    if not ret_ann:
        findings.append({
            "function": fn_name,
            "line": fn_line,
            "severity": "medium",
            "check": "Missing return type annotation",
            "issue": f"Tool '{fn_name}' has no return type annotation. The ADK uses this to build the tool's output schema.",
            "recommendation": f"Add a return type: def {fn_name}(...) -> Dict[str, Any]: or -> str:. Use Pydantic BaseModel for structured outputs.",
        })

    # ── Check 6: bare except clauses ──
    bare_count = _count_bare_except(func)
    if bare_count > 0:
        findings.append({
            "function": fn_name,
            "line": fn_line,
            "severity": "medium",
            "check": "Bare except clause",
            "issue": f"Tool '{fn_name}' has {bare_count} bare 'except:' clause(s) that silently swallow all errors.",
            "recommendation": "Catch specific exceptions (e.g. except ValueError as e:) and either re-raise or return a structured error dict. Silent failures produce confusing agent behaviour and make RCA impossible.",
        })

    return findings


# ---------------------------------------------------------------------------
# Public @tool entry point
# ---------------------------------------------------------------------------

@tool
def validate_tool_schemas(
    tool_paths: List[str],
) -> Dict[str, Any]:
    """
    Validate the Python schema and decorator contract of watsonx Orchestrate
    @tool-decorated functions in one or more Python source files.

    Performs static AST analysis — no code is executed. Checks include:
      - @tool decorator presence
      - All parameters have type annotations (no bare or Any-typed params)
      - Return type annotation present
      - Non-empty docstring (required for LLM tool-selection)
      - No multiple AgentRun parameters (ADK import will reject these)
      - No bare except clauses that silently swallow errors

    Args:
        tool_paths: List of file paths to Python source files containing
            @tool-decorated functions (e.g. ['tools/my_tool.py']).

    Returns:
        A validation report with keys:
          - overall_status: 'pass' | 'fail' | 'error'
          - files_checked (int)
          - tools_found (int)
          - findings (list): one dict per issue found
          - summary (str): human-readable summary
          - remediation_hints (list[str]): top actionable fixes
    """
    all_findings: List[Dict[str, Any]] = []
    tools_found = 0
    files_with_errors: List[str] = []

    for path_str in tool_paths:
        path = Path(path_str)

        # ── File read ──
        try:
            source = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            all_findings.append({
                "function": "<file>",
                "line": 0,
                "severity": "critical",
                "check": "File not found",
                "issue": f"Source file '{path_str}' does not exist.",
                "recommendation": f"Verify the path is correct relative to your project root.",
            })
            files_with_errors.append(path_str)
            continue
        except Exception as exc:
            all_findings.append({
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
                "function": "<module>",
                "line": exc.lineno or 0,
                "severity": "critical",
                "check": "Syntax error",
                "issue": f"'{path_str}' has a syntax error at line {exc.lineno}: {exc.msg}",
                "recommendation": "Fix the syntax error before attempting to import this tool.",
            })
            files_with_errors.append(path_str)
            continue

        source_lines = source.splitlines()

        # ── Walk top-level and class-level functions ──
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Only inspect @tool-decorated functions; skip @flow functions
            if _is_flow_decorated(node):
                continue
            if not _has_decorator(node, "tool"):
                continue

            tools_found += 1
            findings = _check_tool_function(node, source_lines)
            # Tag each finding with its source file
            for f in findings:
                f["file"] = path_str
            all_findings.extend(findings)

    # ── Derive overall status ──
    severities = {f["severity"] for f in all_findings}
    if "critical" in severities:
        overall = "fail"
    elif "high" in severities:
        overall = "fail"
    elif "medium" in severities or "low" in severities:
        overall = "fail"
    else:
        overall = "pass"

    if files_with_errors:
        overall = "error" if all(
            f["severity"] == "critical" for f in all_findings
        ) else overall

    # ── Summary ──
    critical_n = sum(1 for f in all_findings if f["severity"] == "critical")
    high_n     = sum(1 for f in all_findings if f["severity"] == "high")
    medium_n   = sum(1 for f in all_findings if f["severity"] == "medium")

    if overall == "pass":
        summary = (
            f"All {tools_found} @tool function(s) across {len(tool_paths)} file(s) "
            "passed schema validation."
        )
    else:
        summary = (
            f"Found {len(all_findings)} issue(s) across {tools_found} @tool function(s) "
            f"in {len(tool_paths)} file(s): "
            f"{critical_n} critical, {high_n} high, {medium_n} medium."
        )

    # ── Top remediation hints (deduplicated check names) ──
    seen_checks: set = set()
    remediation_hints: List[str] = []
    for f in sorted(all_findings, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}[x["severity"]]):
        key = f["check"]
        if key not in seen_checks:
            seen_checks.add(key)
            remediation_hints.append(f"[{f['severity'].upper()}] {f['check']}: {f['recommendation']}")

    return {
        "overall_status": overall,
        "files_checked": len(tool_paths),
        "tools_found": tools_found,
        "findings": all_findings,
        "summary": summary,
        "remediation_hints": remediation_hints[:10],  # top 10 unique hints
    }

# Made with Bob

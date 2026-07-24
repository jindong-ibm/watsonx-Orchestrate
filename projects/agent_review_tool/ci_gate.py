#!/usr/bin/env python3
"""
wxO Agent Review CI Gate
========================
Standalone script — no ADK runtime required.

Analyse an agent YAML configuration and exit with a non-zero status code when
the result falls below configurable quality thresholds.  Drop this script into
any CI/CD pipeline (GitHub Actions, GitLab CI, Jenkins, Tekton …) to enforce
agent quality standards before deployment.

Usage
-----
    python ci_gate.py <agent_yaml_path> [options]

Options
-------
    --min-score INT      Minimum acceptable overall score (default: 70)
    --max-critical INT   Maximum allowed critical findings (default: 0)
    --max-high INT       Maximum allowed high-severity findings (default: 3)
    --format FORMAT      Report format written on failure: json|markdown|html
                         (default: markdown)
    --report-dir DIR     Directory to write the report into (default: .)
    --strict             Treat ANY finding as a failure (ignores other limits)

Exit codes
----------
    0   All thresholds met — safe to deploy
    1   One or more thresholds exceeded — block deployment
    2   Input error (file not found, parse failure, etc.)

Example (GitHub Actions)
------------------------
    - name: Agent quality gate
      run: python ci_gate.py agents/my_agent.yaml --min-score 80 --max-critical 0
"""

import argparse
import hashlib
import html as html_module
import json
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Inline copies of the analysis + report logic so this script has zero
# dependencies on the ADK or any pip package beyond PyYAML (which the ADK
# already installs).  Changes to analyze_agent_config.py or export_report.py
# should be reflected here when they affect scoring thresholds.
# ---------------------------------------------------------------------------

def _get_prompt(config):
    return config.get('instructions', config.get('system_prompt', config.get('prompt', '')))

def _has_prompt(config):
    return any(k in config for k in ('instructions', 'system_prompt', 'prompt'))

def _get_kb_entries(config):
    raw = config.get('knowledge_bases', config.get('rag', config.get('retrieval', None)))
    if raw is None: return []
    if isinstance(raw, list): return raw
    if isinstance(raw, dict): return [raw]
    return []

# ── Scoring constants (must stay in sync with analyze_agent_config.py) ──
_SEV_DED = {"critical": 15, "high": 10, "medium": 3, "low": 0}
_CAT_CAP = 20
_TOT_CAP = 70
_BONUS_KEYS = ["error_handling", "validation", "guardrails", "retry", "fallback"]
_BONUS_VAL  = 5
_MAX_BONUS  = 15

def _calculate_score(findings, config):
    cat_ded = {}
    for f in findings:
        cat = f.get("category", "General")
        cat_ded[cat] = cat_ded.get(cat, 0) + _SEV_DED.get(f.get("severity", "low"), 0)
    total = min(sum(min(d, _CAT_CAP) for d in cat_ded.values()), _TOT_CAP)
    bonus = 0
    for key in _BONUS_KEYS:
        if key in config and config[key]:
            bonus += _BONUS_VAL
    bonus = min(bonus, _MAX_BONUS)
    if 3 <= len(config.get("tools", [])) <= 8:
        bonus = min(bonus + _BONUS_VAL, _MAX_BONUS)
    prompt = _get_prompt(config)
    if 100 <= len(prompt) <= 1000:
        bonus = min(bonus + _BONUS_VAL, _MAX_BONUS)
    net = max(0, total - bonus)
    return max(0, min(100, 100 - net))

def _get_grade(score):
    if score >= 90: return "A (Excellent)"
    if score >= 80: return "B (Good)"
    if score >= 70: return "C (Fair)"
    if score >= 60: return "D (Needs Improvement)"
    return "F (Critical Issues)"

# ── Simplified inline analysis (same checks as analyze_agent_config.py) ──
def _analyze(config):
    findings = []
    prompt = _get_prompt(config)

    # Prompt design
    if _has_prompt(config):
        if len(prompt) > 2000:
            findings.append({"category": "Prompt Design", "severity": "high",
                "anti_pattern": "Monolithic Mega-Prompt",
                "issue": f"Instructions are {len(prompt)} chars.",
                "recommendation": "Right-size the agent prompt."})
        constraint_count = sum(prompt.lower().count(kw) for kw in ['must','always','never','only','exactly','strictly'])
        if constraint_count > 10:
            findings.append({"category": "Prompt Design", "severity": "medium",
                "anti_pattern": "Over-Constrained Prompting",
                "issue": f"{constraint_count} constraint keywords in instructions.",
                "recommendation": "Use system design to enforce behavior instead of constraints."})
        if len(prompt) < 100 and len(config.get('tools', [])) > 3:
            findings.append({"category": "Prompt Design", "severity": "medium",
                "anti_pattern": "Under-Specified Prompt",
                "issue": "Very short instructions with many tools.",
                "recommendation": "Add a clear, focused instruction set."})

    if len(config.get('tools', [])) > 10:
        findings.append({"category": "Prompt Design", "severity": "high",
            "anti_pattern": "Over-Specialized Agent",
            "issue": f"{len(config['tools'])} tools.",
            "recommendation": "Reduce tool count to 3-10."})

    # System design
    if _has_prompt(config):
        biz_kws = ['approval','validate','check if','verify','compliance','rule','policy','must be','threshold','limit']
        if sum(1 for kw in biz_kws if kw in prompt.lower()) >= 3:
            findings.append({"category": "System Design", "severity": "critical",
                "anti_pattern": "Agent-as-Business-Process Fallacy",
                "issue": "Business logic in prompt.",
                "recommendation": "Move logic to workflows."})
    tools = config.get('tools', [])
    if len(tools) > 15:
        findings.append({"category": "System Design", "severity": "high",
            "anti_pattern": "Tool Soup", "issue": f"{len(tools)} tools.",
            "recommendation": "Curate tools aggressively."})
    if len(str(tools)) > 5000:
        findings.append({"category": "System Design", "severity": "medium",
            "anti_pattern": "Tool Data Overload", "issue": "Large tool definitions.",
            "recommendation": "Keep tool definitions concise."})

    # Knowledge management
    for kb in _get_kb_entries(config):
        if not isinstance(kb, dict): continue
        kb_name = kb.get('name', '<unnamed>')
        if not kb.get('description', '').strip():
            findings.append({"category": "Knowledge Management", "severity": "high",
                "anti_pattern": "Unstructured Data Assumption",
                "issue": f"KB '{kb_name}' has no description.",
                "recommendation": "Add description and curate content."})
        if not (kb.get('documents') or kb.get('path') or kb.get('urls')):
            findings.append({"category": "Knowledge Management", "severity": "medium",
                "anti_pattern": "Empty Knowledge Base",
                "issue": f"KB '{kb_name}' has no documents.",
                "recommendation": "Populate the KB before attaching."})
        top_k = kb.get('top_k', kb.get('max_results', kb.get('max_docs_passed_to_llm', 0)))
        if isinstance(top_k, int) and top_k > 10:
            findings.append({"category": "Context Management", "severity": "medium",
                "anti_pattern": "Over-Retrieved Knowledge",
                "issue": f"KB '{kb_name}' retrieves {top_k} passages.",
                "recommendation": "Reduce top_k."})

    if _has_prompt(config):
        if 'knowledge' in prompt.lower() and ('messy' in prompt.lower() or 'outdated' in prompt.lower()):
            findings.append({"category": "Knowledge Management", "severity": "critical",
                "anti_pattern": "RAG Will Fix Disorganized Knowledge",
                "issue": "Prompt implies RAG to handle messy knowledge.",
                "recommendation": "Clean knowledge before using RAG."})

    # Testing
    if not any(k in config for k in ('error_handling','retry','fallback','recovery')):
        findings.append({"category": "Testing & Resilience", "severity": "high",
            "anti_pattern": "Happy Path Engineering",
            "issue": "No error handling configured.",
            "recommendation": "Add retry and fallback configuration."})
    if not any(k in config for k in ('validation','guardrails','constraints')):
        findings.append({"category": "Testing & Resilience", "severity": "medium",
            "anti_pattern": "Demo-Grade Agent in Production",
            "issue": "No validation or guardrails.",
            "recommendation": "Add input/output validation."})

    # Performance
    if _has_prompt(config):
        plan_count = sum(1 for kw in ['plan','think','reason','analyze','consider'] if kw in prompt.lower())
        if plan_count >= 3:
            findings.append({"category": "Performance", "severity": "high",
                "anti_pattern": "Responsiveness Afterthought",
                "issue": f"{plan_count} planning keywords in prompt.",
                "recommendation": "Reduce nested planning steps."})
    if config.get('max_iterations', 0) > 10:
        findings.append({"category": "Performance", "severity": "medium",
            "anti_pattern": "Excessive Iterations",
            "issue": f"max_iterations={config['max_iterations']}.",
            "recommendation": "Reduce max iterations."})
    if config.get('max_tokens', config.get('context_window', 0)) > 8000:
        findings.append({"category": "Performance", "severity": "medium",
            "anti_pattern": "Firehose Effect",
            "issue": "Large context window.",
            "recommendation": "Filter data before it reaches the model."})

    # Context
    if _has_prompt(config):
        if len(prompt) > 3000:
            findings.append({"category": "Context Management", "severity": "high",
                "anti_pattern": "Unbounded Execution Cost",
                "issue": f"Instructions are {len(prompt)} chars.",
                "recommendation": "Shorten instructions."})
        if 'all information' in prompt.lower() or 'everything' in prompt.lower():
            findings.append({"category": "Context Management", "severity": "critical",
                "anti_pattern": "Give the Model Everything",
                "issue": "Prompt suggests max-context strategy.",
                "recommendation": "Design for precision, not volume."})

    if len(str(config.get('tools', []))) > 10000:
        findings.append({"category": "Context Management", "severity": "high",
            "anti_pattern": "Unbounded Execution Cost",
            "issue": "Large tool schemas.",
            "recommendation": "Curate tool definitions."})

    score = _calculate_score(findings, config)
    return {
        "overall_score": score,
        "grade": _get_grade(score),
        "total_findings": len(findings),
        "critical_issues": sum(1 for f in findings if f['severity'] == 'critical'),
        "high_priority":   sum(1 for f in findings if f['severity'] == 'high'),
        "medium_priority": sum(1 for f in findings if f['severity'] == 'medium'),
        "low_priority":    sum(1 for f in findings if f['severity'] == 'low'),
        "findings": findings,
        "summary": (
            "Agent configuration follows best practices." if score >= 90
            else "Agent has some optimization opportunities." if score >= 70
            else "Agent has significant issues — address before production." if score >= 50
            else "Agent has critical issues that will cause production failures."
        ),
    }


# ---------------------------------------------------------------------------
# Report rendering (inline copy — no import from export_report.py)
# ---------------------------------------------------------------------------

def _report_id(analysis):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h  = hashlib.sha1(json.dumps(analysis, sort_keys=True, default=str).encode()).hexdigest()[:8]
    return f"wxo-ci-gate-{ts}-{h}"

def _render_markdown(analysis, report_id, agent_path, thresholds, gate_passed=True):
    result_label = "✅ GATE PASSED" if gate_passed else "❌ GATE FAILED"
    lines = [
        "# wxO CI Gate Report",
        "",
        f"| | |",
        f"|---|---|",
        f"| Report ID | `{report_id}` |",
        f"| Agent file | `{agent_path}` |",
        f"| Generated  | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} |",
        f"| Result | **{result_label}** |",
        f"| Score | **{analysis['overall_score']}/100** ({analysis['grade']}) |",
        f"| Critical | {analysis['critical_issues']} |",
        f"| High     | {analysis['high_priority']} |",
        "",
        f"> {analysis['summary']}",
        "",
        "## Threshold Check",
        "",
        f"| Threshold | Limit | Actual | Result |",
        "|---|---|---|---|",
        f"| Min score   | ≥ {thresholds['min_score']}  | {analysis['overall_score']} | {'✅ PASS' if analysis['overall_score'] >= thresholds['min_score'] else '❌ FAIL'} |",
        f"| Max critical | ≤ {thresholds['max_critical']} | {analysis['critical_issues']} | {'✅ PASS' if analysis['critical_issues'] <= thresholds['max_critical'] else '❌ FAIL'} |",
        f"| Max high     | ≤ {thresholds['max_high']}    | {analysis['high_priority']} | {'✅ PASS' if analysis['high_priority'] <= thresholds['max_high'] else '❌ FAIL'} |",
        "",
    ]
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings = sorted(analysis["findings"], key=lambda f: sev_order.get(f.get("severity","low"),9))
    if findings:
        lines += ["## Findings", "", "| Severity | Category | Issue |", "|---|---|---|"]
        for f in findings:
            lines.append(f"| {f['severity'].upper()} | {f.get('category','')} | {f.get('issue','').replace(chr(10),' ')} |")
    lines += ["", "---", "*Made with IBM Bob — wxO CI Gate*"]
    return "\n".join(lines)

def _render_json_report(analysis, report_id, agent_path, thresholds, gate_passed):
    return json.dumps({
        "report_id": report_id,
        "agent_file": str(agent_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_passed": gate_passed,
        "thresholds": thresholds,
        **analysis,
    }, indent=2, default=str)

def _render_html_report(analysis, report_id, agent_path, thresholds, gate_passed):
    e = html_module.escape
    score = analysis['overall_score']
    color = "#27ae60" if gate_passed else "#c0392b"
    sev_color = {"critical":"#c0392b","high":"#e67e22","medium":"#f1c40f","low":"#3498db"}
    sev_order = {"critical":0,"high":1,"medium":2,"low":3}
    rows = ""
    for f in sorted(analysis["findings"], key=lambda x: sev_order.get(x.get("severity","low"),9)):
        sv = f.get("severity","low")
        rows += (f"<tr><td style='color:{sev_color.get(sv,'#888')};font-weight:700'>{e(sv.upper())}</td>"
                 f"<td>{e(f.get('category',''))}</td>"
                 f"<td>{e(f.get('issue',''))}</td>"
                 f"<td style='font-size:12px'>{e(f.get('recommendation','')[:120])}</td></tr>\n")
    if not rows:
        rows = "<tr><td colspan='4' style='text-align:center;color:#27ae60'>✅ No issues found</td></tr>"
    result_text = "✅ GATE PASSED" if gate_passed else "❌ GATE FAILED"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>wxO CI Gate — {e(str(agent_path))}</title>
<style>body{{font-family:-apple-system,sans-serif;font-size:14px;color:#1f2328;padding:32px 16px}}
.c{{max-width:760px;margin:0 auto}}h1{{font-size:20px;margin-bottom:4px}}
.meta{{font-size:12px;color:#57606a;border-bottom:1px solid #e5e7eb;padding-bottom:12px;margin-bottom:20px}}
.result{{display:inline-block;padding:6px 18px;border-radius:4px;font-size:16px;font-weight:700;color:#fff;background:{color};margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f7f8fa;border:1px solid #e5e7eb;padding:8px 10px;text-align:left}}
td{{border:1px solid #e5e7eb;padding:7px 10px;vertical-align:top}}
tr:nth-child(even) td{{background:#f7f8fa}}
.footer{{margin-top:32px;padding-top:12px;border-top:1px solid #e5e7eb;text-align:center;font-size:12px;color:#57606a}}</style>
</head><body><div class="c">
<h1>wxO CI Gate Report</h1>
<div class="meta">Report ID: <code>{e(report_id)}</code> &nbsp;·&nbsp; Agent: <code>{e(str(agent_path))}</code></div>
<div class="result">{result_text}</div>
<p style="margin-bottom:16px">Score: <strong>{score}/100</strong> ({e(analysis['grade'])}) &nbsp;·&nbsp;
Critical: {analysis['critical_issues']} &nbsp;·&nbsp; High: {analysis['high_priority']}</p>
<h2 style="font-size:13px;font-weight:600;text-transform:uppercase;color:#57606a;margin-bottom:8px">Findings</h2>
<table><thead><tr><th>Severity</th><th>Category</th><th>Issue</th><th>Recommendation</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="footer">Made with IBM Bob — wxO CI Gate</div>
</div></body></html>"""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="wxO Agent Review CI Gate — blocks deployment when quality thresholds are not met.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("agent_yaml", help="Path to the agent YAML file to analyze")
    parser.add_argument("--min-score",    type=int, default=70,  help="Minimum acceptable overall score (default: 70)")
    parser.add_argument("--max-critical", type=int, default=0,   help="Maximum critical findings allowed (default: 0)")
    parser.add_argument("--max-high",     type=int, default=3,   help="Maximum high-severity findings allowed (default: 3)")
    parser.add_argument("--format",       choices=["json","markdown","html"], default="markdown",
                        help="Report format written on failure (default: markdown)")
    parser.add_argument("--report-dir",   default=".",           help="Directory to write the report (default: .)")
    parser.add_argument("--strict",       action="store_true",   help="Fail on ANY finding")
    args = parser.parse_args()

    agent_path = Path(args.agent_yaml)

    # ── Load ──
    try:
        raw = agent_path.read_text(encoding="utf-8")
        config = yaml.safe_load(raw)
        if not isinstance(config, dict):
            raise ValueError("YAML did not parse to a dict")
    except FileNotFoundError:
        print(f"ERROR: File not found: {agent_path}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: Cannot parse {agent_path}: {exc}", file=sys.stderr)
        return 2

    # ── Analyse ──
    analysis = _analyze(config)
    rid      = _report_id(analysis)

    thresholds = {
        "min_score":    args.min_score,
        "max_critical": args.max_critical,
        "max_high":     args.max_high,
        "strict":       args.strict,
    }

    # ── Gate decision ──
    violations = []
    if args.strict and analysis["total_findings"] > 0:
        violations.append(f"--strict: {analysis['total_findings']} finding(s) found")
    else:
        if analysis["overall_score"] < args.min_score:
            violations.append(f"Score {analysis['overall_score']} < minimum {args.min_score}")
        if analysis["critical_issues"] > args.max_critical:
            violations.append(f"Critical issues {analysis['critical_issues']} > maximum {args.max_critical}")
        if analysis["high_priority"] > args.max_high:
            violations.append(f"High issues {analysis['high_priority']} > maximum {args.max_high}")

    gate_passed = len(violations) == 0

    # ── Console summary ──
    status_icon = "✅" if gate_passed else "❌"
    print(f"\n{status_icon} {'GATE PASSED' if gate_passed else 'GATE FAILED'}")
    print(f"   Agent  : {agent_path}")
    print(f"   Score  : {analysis['overall_score']}/100  ({analysis['grade']})")
    print(f"   Issues : {analysis['critical_issues']} critical / {analysis['high_priority']} high / {analysis['medium_priority']} medium")
    print(f"   Report : {rid}")

    if violations:
        print("\nThreshold violations:")
        for v in violations:
            print(f"  ✗ {v}")

    if analysis["findings"]:
        print("\nTop findings:")
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for f in sorted(analysis["findings"], key=lambda x: sev_order.get(x.get("severity","low"),9))[:5]:
            print(f"  [{f['severity'].upper()}] {f.get('anti_pattern','')} — {f.get('issue','')[:80]}")

    # ── Write report ──
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    ext = {"json": ".json", "markdown": ".md", "html": ".html"}[args.format]
    report_file = report_dir / f"agent-review-{rid}{ext}"

    if args.format == "json":
        content = _render_json_report(analysis, rid, agent_path, thresholds, gate_passed)
    elif args.format == "html":
        content = _render_html_report(analysis, rid, agent_path, thresholds, gate_passed)
    else:
        content = _render_markdown(analysis, rid, agent_path, thresholds, gate_passed)

    report_file.write_text(content, encoding="utf-8")
    print(f"\n   Report written → {report_file}")

    return 0 if gate_passed else 1


if __name__ == "__main__":
    sys.exit(main())

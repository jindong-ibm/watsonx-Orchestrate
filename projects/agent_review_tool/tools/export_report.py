"""
Export analysis results from any agent_review_tool tool to a shareable report.

Supports three output formats:
  - json     : machine-readable, suitable for CI artifact storage
  - markdown : human-readable, renders in GitHub / GitLab MRs and wikis
  - html     : self-contained single-file report for browser viewing or email

Every report is stamped with a unique report_id (ISO timestamp + content hash)
so IBM Support can correlate reports across conversations and over time.

The tool returns the rendered report as a string.  Pass output_path to also
write it to disk — useful when called from CI pipelines or notebooks.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
import json
import hashlib
import html as html_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
_SEVERITY_COLOR = {
    "critical": "#c0392b",
    "high":     "#e67e22",
    "medium":   "#f1c40f",
    "low":      "#3498db",
}


def _make_report_id(analysis: Dict[str, Any]) -> str:
    """Generate a stable, unique report identifier."""
    ts  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = json.dumps(analysis, sort_keys=True, default=str)
    h   = hashlib.sha1(key.encode()).hexdigest()[:8]
    return f"wxo-review-{ts}-{h}"


def _detect_tool(analysis: Dict[str, Any]) -> str:
    """Guess which tool produced the analysis dict."""
    if "overall_score" in analysis and "grade" in analysis:
        return "analyze_agent_config"
    if "best_practices_leader" in analysis:
        return "compare_agents"
    if "overall_status" in analysis and "checks" in analysis:
        return "validate_live_agent"
    if "tools_found" in analysis and "findings" in analysis:
        return "validate_tool_schemas"
    if "flows_found" in analysis and "findings" in analysis:
        return "analyze_flow"
    if "priority_actions" in analysis:
        return "generate_recommendations"
    return "unknown"


def _findings_from(analysis: Dict[str, Any], tool_name: str) -> List[Dict]:
    """Normalize findings to a common list regardless of source tool."""
    if tool_name in ("analyze_agent_config", "validate_tool_schemas", "analyze_flow"):
        return analysis.get("findings", [])
    if tool_name == "validate_live_agent":
        # Each 'check' dict has status/message — convert to finding shape
        return [
            {
                "severity": "high" if c.get("status") in ("fail", "error") else "low",
                "category": "Live Validation",
                "anti_pattern": c.get("check", ""),
                "issue": c.get("message", ""),
                "recommendation": "",
            }
            for c in analysis.get("checks", [])
        ]
    if tool_name == "compare_agents":
        # Flatten all per-agent findings, tagging with agent name
        flat = []
        for agent in analysis.get("agents", []):
            for f in agent.get("findings", []):
                flat.append({**f, "agent": agent["name"]})
        return flat
    return []


# ---------------------------------------------------------------------------
# Format renderers
# ---------------------------------------------------------------------------

def _render_json(analysis: Dict[str, Any], report_id: str) -> str:
    stamped = {"report_id": report_id, "generated_at": datetime.now(timezone.utc).isoformat(), **analysis}
    return json.dumps(stamped, indent=2, default=str)


def _render_markdown(analysis: Dict[str, Any], report_id: str, tool_name: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: List[str] = []

    lines += [
        f"# wxO Agent Review Report",
        f"",
        f"| Field | Value |",
        f"|---|---|",
        f"| Report ID | `{report_id}` |",
        f"| Generated | {now} |",
        f"| Source tool | `{tool_name}` |",
    ]

    # ── Scorecard (analyze_agent_config) ──
    if tool_name == "analyze_agent_config":
        score = analysis.get("overall_score", "–")
        grade = analysis.get("grade", "–")
        lines += [
            f"| Overall score | **{score}/100** |",
            f"| Grade | **{grade}** |",
            f"| Critical | {analysis.get('critical_issues', 0)} |",
            f"| High | {analysis.get('high_priority', 0)} |",
            f"| Medium | {analysis.get('medium_priority', 0)} |",
            f"",
            f"> {analysis.get('summary', '')}",
        ]

    # ── Status badge (validate_live_agent / validate_tool_schemas / analyze_flow) ──
    elif "overall_status" in analysis:
        status = analysis["overall_status"].upper()
        lines += [
            f"| Status | **{status}** |",
            f"| Files checked | {analysis.get('files_checked', analysis.get('tools_found', '–'))} |",
            f"",
            f"> {analysis.get('summary', '')}",
        ]

    # ── Compare agents ──
    elif tool_name == "compare_agents":
        agents = analysis.get("agents", [])
        lines += [f"", f"## Agent Scores", f"", f"| Agent | Score | Grade |", f"|---|---|---|"]
        for a in agents:
            lines.append(f"| {a['name']} | {a['score']}/100 | {a['grade']} |")

    lines += ["", "---", ""]

    # ── Findings table ──
    findings = _findings_from(analysis, tool_name)
    if findings:
        sorted_findings = sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "low"), 9))
        lines += [f"## Findings ({len(findings)})", "", "| Severity | Category | Anti-Pattern / Check | Issue | Recommendation |", "|---|---|---|---|---|"]
        for f in sorted_findings:
            sev      = f.get("severity", "low")
            cat      = f.get("category", f.get("check", ""))
            pattern  = f.get("anti_pattern", f.get("check", "")).replace("|", "\\|")
            issue    = f.get("issue", f.get("message", "")).replace("|", "\\|").replace("\n", " ")
            rec      = f.get("recommendation", "").replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(f"| {_SEVERITY_EMOJI.get(sev, '')} {sev.upper()} | {cat} | **{pattern}** | {issue} | {rec} |")
    else:
        lines += ["## Findings", "", "✅ No issues found."]

    # ── Remediation hints ──
    hints = analysis.get("remediation_hints", [])
    if hints:
        lines += ["", "## Top Remediation Hints", ""]
        for h in hints:
            lines.append(f"- {h}")

    lines += ["", "---", f"*Made with IBM Bob — wxO Agent Review Tool*"]
    return "\n".join(lines)


def _render_html(analysis: Dict[str, Any], report_id: str, tool_name: str) -> str:
    """Produce a self-contained single-file HTML report."""
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    e       = html_module.escape     # alias for readability
    findings = _findings_from(analysis, tool_name)
    sorted_findings = sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.get("severity","low"), 9))

    # Summary bar values
    score  = analysis.get("overall_score", "–")
    grade  = analysis.get("grade", analysis.get("overall_status", "–"))
    status = analysis.get("overall_status", "")

    badge_color = "#27ae60"   # green = pass / A/B
    if isinstance(score, int):
        if score < 60: badge_color = "#c0392b"
        elif score < 80: badge_color = "#e67e22"
    if status in ("fail", "error"):
        badge_color = "#c0392b"

    # Build findings rows
    rows_html = ""
    if sorted_findings:
        for f in sorted_findings:
            sev        = f.get("severity", "low")
            color      = _SEVERITY_COLOR.get(sev, "#888")
            cat        = e(f.get("category", f.get("check", "")))
            pattern    = e(f.get("anti_pattern", f.get("check", "")))
            fn         = e(f.get("function", f.get("agent", "")))
            ln         = f.get("line", "")
            loc        = f"{fn}{(' :' + str(ln)) if ln else ''}" if fn else ""
            issue      = e(f.get("issue", f.get("message", "")))
            rec        = e(f.get("recommendation", ""))
            rows_html += (
                f'<tr>'
                f'<td><span style="color:{color};font-weight:700">{e(sev.upper())}</span></td>'
                f'<td>{cat}</td>'
                f'<td style="font-weight:600">{pattern}</td>'
                f'<td style="font-size:12px;color:#555">{loc}</td>'
                f'<td>{issue}</td>'
                f'<td style="font-size:12px;color:#444">{rec}</td>'
                f'</tr>\n'
            )
    else:
        rows_html = '<tr><td colspan="6" style="text-align:center;color:#27ae60;padding:16px">✅ No issues found</td></tr>'

    # Hints section
    hints     = analysis.get("remediation_hints", [])
    hints_html = ""
    if hints:
        items = "".join(f"<li style='margin-bottom:6px'>{e(h)}</li>" for h in hints)
        hints_html = f"<h2 style='margin-top:28px'>Top Remediation Hints</h2><ul>{items}</ul>"

    # Agent scores table (compare_agents)
    agents_html = ""
    if tool_name == "compare_agents":
        rows = ""
        for a in analysis.get("agents", []):
            sc = a.get("score", 0)
            clr = "#27ae60" if sc >= 80 else ("#e67e22" if sc >= 60 else "#c0392b")
            rows += f"<tr><td>{e(a['name'])}</td><td style='color:{clr};font-weight:700'>{sc}/100</td><td>{e(a.get('grade',''))}</td></tr>"
        agents_html = f"<h2>Agent Scores</h2><table><thead><tr><th>Agent</th><th>Score</th><th>Grade</th></tr></thead><tbody>{rows}</tbody></table>"

    summary_text = e(str(analysis.get("summary", "")))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>wxO Agent Review — {e(report_id)}</title>
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,"Segoe UI",system-ui,sans-serif;font-size:14px;
        line-height:1.6;color:#1f2328;background:#fff;padding:32px 16px 48px}}
  .container{{max-width:860px;margin:0 auto}}
  h1{{font-size:20px;font-weight:700;margin-bottom:4px}}
  h2{{font-size:14px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
      color:#57606a;margin:24px 0 10px}}
  .meta{{font-size:12px;color:#57606a;border-bottom:1px solid #e5e7eb;
         padding-bottom:12px;margin-bottom:20px}}
  .badge{{display:inline-block;padding:4px 14px;border-radius:4px;font-size:15px;
          font-weight:700;color:#fff;background:{badge_color}}}
  .scorecard{{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px}}
  .sc-box{{border:1px solid #e5e7eb;border-radius:6px;padding:12px 18px;min-width:120px}}
  .sc-box .label{{font-size:11px;color:#57606a;text-transform:uppercase;letter-spacing:.05em}}
  .sc-box .val{{font-size:20px;font-weight:700}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{background:#f7f8fa;border:1px solid #e5e7eb;padding:8px 10px;text-align:left;font-weight:600}}
  td{{border:1px solid #e5e7eb;padding:7px 10px;vertical-align:top}}
  tr:nth-child(even) td{{background:#f7f8fa}}
  .summary{{background:#f7f8fa;border:1px solid #e5e7eb;border-radius:6px;
             padding:12px 16px;font-size:13px;margin-bottom:20px;white-space:pre-wrap}}
  .footer{{margin-top:40px;padding-top:12px;border-top:1px solid #e5e7eb;
            text-align:center;font-size:12px;color:#57606a}}
</style>
</head>
<body>
<div class="container">
  <h1>wxO Agent Review Report</h1>
  <div class="meta">
    Report ID: <code>{e(report_id)}</code> &nbsp;·&nbsp;
    Generated: {e(now)} &nbsp;·&nbsp;
    Tool: <code>{e(tool_name)}</code>
  </div>

  <div class="scorecard">
    <div class="sc-box">
      <div class="label">Result</div>
      <div class="val"><span class="badge">{e(str(grade))}</span></div>
    </div>
    {"" if score == "–" else f'<div class="sc-box"><div class="label">Score</div><div class="val">{score}/100</div></div>'}
    <div class="sc-box">
      <div class="label">Findings</div>
      <div class="val">{len(findings)}</div>
    </div>
  </div>

  {agents_html}

  <div class="summary">{summary_text}</div>

  <h2>Findings ({len(findings)})</h2>
  <table>
    <thead>
      <tr>
        <th>Severity</th><th>Category</th><th>Anti-Pattern / Check</th>
        <th>Location</th><th>Issue</th><th>Recommendation</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  {hints_html}

  <div class="footer">Made with IBM Bob — wxO Agent Review Tool</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public @tool
# ---------------------------------------------------------------------------

@tool
def export_report(
    analysis: Dict[str, Any],
    report_format: str = "markdown",
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export any agent_review_tool analysis result as a shareable report.

    Renders the result from analyze_agent_config, validate_tool_schemas,
    analyze_flow, validate_live_agent, compare_agents, or
    generate_recommendations into the requested format and optionally writes
    it to disk.  Every report includes a unique report_id for correlation with
    IBM Support.

    Args:
        analysis: The dict returned by any agent_review_tool analysis tool.
        report_format: Output format — one of 'json', 'markdown', or 'html'.
            Defaults to 'markdown'.
        output_path: Optional file path to write the report to (e.g.
            'reports/my_agent_review.md'). Parent directories are created
            automatically. If omitted, the report is only returned in the
            response dict.

    Returns:
        Dict with keys:
          - report_id (str): unique identifier for this report
          - format (str): the format that was rendered
          - output_path (str | None): path written, or null
          - report (str): the full rendered report content
    """
    fmt = (report_format or "markdown").lower().strip()
    if fmt not in ("json", "markdown", "html"):
        fmt = "markdown"

    report_id = _make_report_id(analysis)
    tool_name = _detect_tool(analysis)

    if fmt == "json":
        rendered = _render_json(analysis, report_id)
    elif fmt == "html":
        rendered = _render_html(analysis, report_id, tool_name)
    else:
        rendered = _render_markdown(analysis, report_id, tool_name)

    written_path: Optional[str] = None
    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rendered, encoding="utf-8")
        written_path = str(p)

    return {
        "report_id":   report_id,
        "format":      fmt,
        "output_path": written_path,
        "report":      rendered,
    }

# Made with Bob

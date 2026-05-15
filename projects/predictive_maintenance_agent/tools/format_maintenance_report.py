"""
Maintenance Report Formatter Tool

Formats the complete maintenance plan into a structured, human-readable
Markdown report suitable for display in the watsonx Orchestrate chat interface
and for distribution to maintenance teams.
"""

import json
from datetime import datetime, timezone
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


_URGENCY_EMOJI = {
    "immediate": "🔴",
    "scheduled": "🟡",
    "monitor":   "🟢",
}

_URGENCY_LABEL = {
    "immediate": "IMMEDIATE ACTION REQUIRED",
    "scheduled": "SCHEDULED MAINTENANCE",
    "monitor":   "MONITORING — NO ACTION NEEDED",
}

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning":  "🟡",
    "normal":   "🟢",
}

_AVAILABILITY_EMOJI = {
    "available":    "✅",
    "low_stock":    "⚠️",
    "out_of_stock": "❌",
}


def _section(title: str, level: int = 2) -> str:
    prefix = "#" * level
    return f"\n{prefix} {title}\n"


def _table_row(*cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _table_header(*headers) -> str:
    row = _table_row(*headers)
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    return row + "\n" + sep


@tool(permission=ToolPermission.READ_ONLY)
def format_maintenance_report(
    device_name: str,
    device_type: str,
    sensor_data_json: str,
    anomaly_analysis_json: str,
    recommendation_json: str,
    maintenance_plan_json: str,
) -> str:
    """
    Format a complete predictive maintenance report as structured Markdown.

    Combines sensor readings, anomaly analysis, maintenance recommendation,
    and maintenance plan into a single, well-structured Markdown report
    suitable for display in the chat interface and distribution to teams.

    Args:
        device_name: The unique name or identifier of the device (e.g., "PUMP-001")
        device_type: The type/category of the device (e.g., "centrifugal_pump")
        sensor_data_json: JSON string output from get_sensor_data MCP tool
        anomaly_analysis_json: JSON string output from analyze_sensor_anomalies tool
        recommendation_json: JSON string output from generate_maintenance_recommendation tool
        maintenance_plan_json: JSON string output from generate_maintenance_plan tool

    Returns:
        Formatted Markdown string containing the complete maintenance report
        with sections for executive summary, sensor readings, anomaly analysis,
        recommendation, work items, parts list, safety precautions, and cost summary.
    """
    try:
        sensor = json.loads(sensor_data_json)
        anomaly = json.loads(anomaly_analysis_json)
        rec = json.loads(recommendation_json)
        plan = json.loads(maintenance_plan_json)

        urgency = plan.get("urgency_level", "monitor")
        severity = anomaly.get("severity_level", "normal")
        plan_id = plan.get("plan_id", "N/A")
        scheduled_date = plan.get("scheduled_date", "TBD")
        report_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines = []

        # ── Title ──────────────────────────────────────────────────────────────
        lines.append(
            f"# 🔧 Predictive Maintenance Report — {device_name}"
        )
        lines.append(f"**Plan ID:** `{plan_id}` | **Generated:** {report_ts}")
        lines.append("")

        # ── Alert Banner ───────────────────────────────────────────────────────
        urgency_emoji = _URGENCY_EMOJI.get(urgency, "⚪")
        urgency_label = _URGENCY_LABEL.get(urgency, urgency.upper())
        lines.append(f"> {urgency_emoji} **{urgency_label}**")
        lines.append("")

        # ── Executive Summary ──────────────────────────────────────────────────
        lines.append(_section("Executive Summary"))
        lines.append(
            f"| Field | Value |\n|---|---|"
        )
        lines.append(f"| **Device** | {device_name} |")
        lines.append(f"| **Device Type** | {device_type.replace('_', ' ').title()} |")
        lines.append(f"| **Urgency Level** | {urgency_emoji} {urgency.upper()} |")
        lines.append(f"| **Anomaly Severity** | {_SEVERITY_EMOJI.get(severity, '⚪')} {severity.upper()} |")
        lines.append(f"| **Anomalies Detected** | {anomaly.get('anomaly_count', 0)} |")
        lines.append(f"| **Scheduled Date** | {scheduled_date} |")
        lines.append(f"| **Est. Downtime** | {plan.get('estimated_total_duration_hours', 0)} hours |")
        lines.append(f"| **Est. Total Cost** | ${plan.get('estimated_total_cost_usd', 0):,.2f} USD |")
        lines.append(f"| **Priority Score** | {rec.get('priority_score', 1)}/10 |")
        lines.append("")

        # ── Recommended Action ─────────────────────────────────────────────────
        lines.append(_section("Recommended Action"))
        lines.append(rec.get("recommended_action", "No action required."))
        lines.append("")
        lines.append(f"**Rationale:** {rec.get('rationale', '')}")
        lines.append("")

        # ── Sensor Readings ────────────────────────────────────────────────────
        lines.append(_section("Current Sensor Readings"))
        metrics = sensor.get("metrics", {})
        if metrics:
            lines.append(_table_header("Metric", "Value", "Unit"))
            metric_display = {
                "temperature_celsius":    ("Temperature",       "°C"),
                "vibration_mm_per_s":     ("Vibration",         "mm/s"),
                "pressure_bar":           ("Pressure",          "bar"),
                "humidity_percent":       ("Humidity",          "%"),
                "power_consumption_kw":   ("Power Consumption", "kW"),
                "rpm":                    ("RPM",               "rpm"),
            }
            for key, (label, unit) in metric_display.items():
                if key in metrics:
                    lines.append(_table_row(label, f"{metrics[key]:.2f}", unit))
        else:
            # Flat sensor data (no nested metrics key)
            lines.append(_table_header("Metric", "Value"))
            skip_keys = {"device_name", "device_type", "timestamp", "status", "data_source"}
            for k, v in sensor.items():
                if k not in skip_keys and isinstance(v, (int, float)):
                    lines.append(_table_row(k.replace("_", " ").title(), v))
        lines.append("")
        lines.append(
            f"*Timestamp: {sensor.get('timestamp', 'N/A')} | "
            f"Source: {sensor.get('data_source', 'IoT Sensor')}*"
        )
        lines.append("")

        # ── Anomaly Analysis ───────────────────────────────────────────────────
        lines.append(_section("Anomaly Analysis"))
        anomaly_details = anomaly.get("anomaly_details", [])
        if anomaly_details:
            lines.append(
                _table_header(
                    "Metric", "Value", "Warning Threshold",
                    "Critical Threshold", "Severity", "Root Cause"
                )
            )
            for a in anomaly_details:
                sev = a.get("severity", "normal")
                sev_emoji = _SEVERITY_EMOJI.get(sev, "⚪")
                thresholds = a.get("thresholds", {})
                lines.append(
                    _table_row(
                        a.get("metric", ""),
                        f"{a.get('value', 0):.2f}",
                        str(thresholds.get("warning", "N/A")),
                        str(thresholds.get("critical", "N/A")),
                        f"{sev_emoji} {sev.upper()}",
                        a.get("root_cause", ""),
                    )
                )
        else:
            lines.append("✅ No anomalies detected. All metrics within normal operating ranges.")

        healthy = anomaly.get("healthy_metrics", [])
        if healthy:
            lines.append("")
            lines.append(f"**Healthy Metrics:** {', '.join(healthy)}")
        lines.append("")

        # ── Maintenance History Context ─────────────────────────────────────────
        hist = rec.get("historical_context", {})
        if hist:
            lines.append(_section("Maintenance History Context"))
            lines.append(
                f"| Field | Value |\n|---|---|"
            )
            lines.append(f"| Total Maintenance Events | {hist.get('total_maintenance_events', 0)} |")
            lines.append(f"| Last Maintenance Date | {hist.get('last_maintenance_date', 'N/A')} |")
            lines.append(f"| Days Since Last Maintenance | {hist.get('days_since_last_maintenance', 'N/A')} |")
            lines.append(f"| Average Downtime (hours) | {hist.get('average_downtime_hours', 0)} |")
            lines.append(f"| Total Historical Cost | ${hist.get('total_maintenance_cost_usd', 0):,.2f} USD |")
            recent_types = hist.get("recent_maintenance_types", [])
            if recent_types:
                lines.append(f"| Recent Maintenance Types | {', '.join(str(t) for t in recent_types if t)} |")
            lines.append("")

        # ── Work Items ─────────────────────────────────────────────────────────
        lines.append(_section("Work Items"))
        work_items = plan.get("work_items", [])
        if work_items:
            lines.append(
                _table_header(
                    "#", "Task", "Category", "Duration (hrs)",
                    "Skill Required", "Tools Required"
                )
            )
            for item in work_items:
                cat = item.get("category", "maintenance")
                cat_emoji = {"safety": "🦺", "maintenance": "🔧", "verification": "✔️"}.get(cat, "📋")
                tools_str = ", ".join(item.get("tools_required", []))
                lines.append(
                    _table_row(
                        item.get("item_number", ""),
                        item.get("task", ""),
                        f"{cat_emoji} {cat.title()}",
                        item.get("duration_hours", 0),
                        item.get("skill_required", ""),
                        tools_str,
                    )
                )
        lines.append("")
        lines.append(
            f"**Total Estimated Duration:** {plan.get('estimated_total_duration_hours', 0)} hours"
        )
        lines.append("")

        # ── Required Parts ─────────────────────────────────────────────────────
        lines.append(_section("Required Spare Parts"))
        parts = plan.get("required_parts", [])
        if parts:
            lines.append(
                _table_header(
                    "Part ID", "Part Name", "Part Number",
                    "Qty Needed", "Stock Available", "Availability", "Unit Price"
                )
            )
            for p in parts:
                avail = p.get("availability_status", "unknown")
                avail_emoji = _AVAILABILITY_EMOJI.get(avail, "❓")
                lines.append(
                    _table_row(
                        p.get("part_id", ""),
                        p.get("part_name", ""),
                        p.get("part_number", ""),
                        p.get("quantity_needed", 1),
                        p.get("stock_available", 0),
                        f"{avail_emoji} {avail.replace('_', ' ').title()}",
                        f"${p.get('unit_price_usd', 0):,.2f}",
                    )
                )
        else:
            lines.append("No spare parts required for this maintenance action.")
        lines.append("")

        # ── Safety Precautions ─────────────────────────────────────────────────
        lines.append(_section("Safety Precautions"))
        lines.append("> ⚠️ **All safety procedures must be followed before commencing work.**")
        lines.append("")
        for i, precaution in enumerate(plan.get("safety_precautions", []), 1):
            lines.append(f"{i}. {precaution}")
        lines.append("")

        # ── Team & Cost Summary ────────────────────────────────────────────────
        lines.append(_section("Resource & Cost Summary"))
        team = plan.get("assigned_team", {})
        lines.append(
            f"| Field | Value |\n|---|---|"
        )
        lines.append(f"| Team Size | {team.get('team_size', 0)} technicians |")
        roles = team.get("roles_required", [])
        if roles:
            lines.append(f"| Roles Required | {', '.join(roles)} |")
        lines.append(f"| Labor Hours | {team.get('estimated_labor_hours', 0)} hrs @ ${team.get('labor_rate_per_hour_usd', 85)}/hr |")
        lines.append(f"| **Labor Cost** | **${plan.get('estimated_labor_cost_usd', 0):,.2f} USD** |")
        lines.append(f"| **Parts Cost** | **${plan.get('estimated_parts_cost_usd', 0):,.2f} USD** |")
        lines.append(f"| **Total Estimated Cost** | **${plan.get('estimated_total_cost_usd', 0):,.2f} USD** |")
        lines.append("")

        # ── Footer ─────────────────────────────────────────────────────────────
        lines.append("---")
        lines.append(
            f"*Report generated by Predictive Maintenance Agent | "
            f"Plan ID: `{plan_id}` | {report_ts}*"
        )

        return "\n".join(lines)

    except Exception as e:
        return (
            f"# ⚠️ Maintenance Report — {device_name}\n\n"
            f"**Error generating report:** {str(e)}\n\n"
            f"Please check the input JSON data and try again."
        )

# Made with Bob
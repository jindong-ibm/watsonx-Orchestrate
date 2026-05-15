"""
Maintenance Recommendation Tool

Generates actionable maintenance recommendations by combining anomaly analysis
results with historical maintenance records. Determines urgency level, recommended
actions, estimated downtime, and required spare parts.
"""

import json
from datetime import datetime, timezone
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# Urgency mapping based on severity and recency of last maintenance
_URGENCY_RULES = {
    "critical": "immediate",   # Critical anomalies → immediate action
    "warning":  "scheduled",   # Warning anomalies → schedule within next window
    "normal":   "monitor",     # No anomalies → continue monitoring
}

# Recommended actions by anomaly metric
_ACTION_MAP = {
    "Temperature": {
        "immediate": "Emergency shutdown and thermal inspection. Check cooling system, "
                     "bearings, and lubrication. Do not restart until root cause is resolved.",
        "scheduled": "Schedule cooling system inspection and bearing lubrication check "
                     "within the next 48 hours.",
    },
    "Vibration": {
        "immediate": "Immediate shutdown for vibration analysis. Inspect bearings, shaft "
                     "alignment, and coupling. Replace worn components before restart.",
        "scheduled": "Schedule vibration analysis and bearing inspection within the next "
                     "planned maintenance window (within 7 days).",
    },
    "Pressure": {
        "immediate": "Immediate inspection of seals, valves, and flow paths. Check for "
                     "blockages or seal failures. Isolate equipment if pressure is unsafe.",
        "scheduled": "Schedule seal inspection and pressure system check within 72 hours.",
    },
    "Humidity": {
        "immediate": "Inspect moisture ingress points, electrical insulation, and lubrication "
                     "contamination. Check environmental seals and drainage.",
        "scheduled": "Schedule environmental seal inspection and moisture control check.",
    },
    "Power Consumption": {
        "immediate": "Inspect for mechanical binding, electrical faults, and overloading. "
                     "Check motor windings and drive components.",
        "scheduled": "Schedule electrical inspection and mechanical efficiency check.",
    },
    "RPM": {
        "immediate": "Inspect drive components, coupling, and control system. Check for "
                     "belt/chain wear or coupling slip.",
        "scheduled": "Schedule drive system inspection and control calibration.",
    },
}

# Parts commonly required by anomaly type
_PARTS_BY_ANOMALY = {
    "Temperature":        ["BEAR-002", "LUBR-005", "SEAL-001"],
    "Vibration":          ["BEAR-002", "BEAR-020", "LUBR-005"],
    "Pressure":           ["SEAL-001", "GASKET-004", "VALVE-010"],
    "Humidity":           ["SEAL-001", "GASKET-004"],
    "Power Consumption":  ["BEAR-002", "BRUSH-021"],
    "RPM":                ["BELT-012", "LUBR-005"],
}

# Estimated downtime hours by urgency and number of anomalies
_DOWNTIME_ESTIMATES = {
    "immediate": {1: 8.0, 2: 12.0, 3: 16.0, "many": 24.0},
    "scheduled": {1: 4.0, 2: 6.0,  3: 8.0,  "many": 12.0},
    "monitor":   {1: 0.0, 2: 0.0,  3: 0.0,  "many": 0.0},
}


def _get_downtime_estimate(urgency: str, anomaly_count: int) -> float:
    """Estimate downtime based on urgency and number of anomalies."""
    table = _DOWNTIME_ESTIMATES.get(urgency, _DOWNTIME_ESTIMATES["monitor"])
    if anomaly_count <= 3:
        return table.get(anomaly_count, 0.0)
    return table["many"]


def _get_required_parts(anomaly_details: list) -> list:
    """Collect unique required parts from all anomalies."""
    parts = set()
    for anomaly in anomaly_details:
        metric = anomaly.get("metric", "")
        for part in _PARTS_BY_ANOMALY.get(metric, []):
            parts.add(part)
    return sorted(list(parts))


@tool(permission=ToolPermission.READ_ONLY)
def generate_maintenance_recommendation(
    device_name: str,
    device_type: str,
    anomaly_analysis_json: str,
    maintenance_history_json: str,
) -> str:
    """
    Generate a maintenance recommendation based on anomaly analysis and maintenance history.

    Combines the results of sensor anomaly detection with historical maintenance
    patterns to produce a prioritized, actionable maintenance recommendation including
    urgency level, specific actions, estimated downtime, and required parts.

    Args:
        device_name: The unique name or identifier of the device (e.g., "PUMP-001")
        device_type: The type/category of the device (e.g., "centrifugal_pump")
        anomaly_analysis_json: JSON string output from analyze_sensor_anomalies tool
        maintenance_history_json: JSON string output from get_maintenance_history MCP tool

    Returns:
        JSON string containing:
        - device_name: Name of the device
        - device_type: Type of the device
        - urgency_level: "immediate", "scheduled", or "monitor"
        - recommended_action: Specific maintenance action to take
        - estimated_downtime_hours: Estimated hours of equipment downtime
        - required_parts: List of part IDs needed for the maintenance
        - rationale: Explanation of why this recommendation was made
        - historical_context: Summary of relevant maintenance history
        - priority_score: Numeric priority score (1-10, higher = more urgent)
        - recommendation_timestamp: When the recommendation was generated
    """
    try:
        anomaly_data = json.loads(anomaly_analysis_json)
        history_data = json.loads(maintenance_history_json)

        severity = anomaly_data.get("severity_level", "normal")
        anomaly_details = anomaly_data.get("anomaly_details", [])
        anomaly_count = anomaly_data.get("anomaly_count", 0)
        root_cause_summary = anomaly_data.get("root_cause_summary", "")

        # Determine urgency
        urgency = _URGENCY_RULES.get(severity, "monitor")

        # Check if last maintenance was recent (within 30 days) — may affect urgency
        summary = history_data.get("summary", {})
        last_maintenance_str = summary.get("last_maintenance_date")
        days_since_maintenance = None
        if last_maintenance_str:
            try:
                last_maint = datetime.strptime(last_maintenance_str, "%Y-%m-%d")
                days_since_maintenance = (datetime.now() - last_maint).days
                # If critical and maintenance was very recent, escalate rationale
                if severity == "critical" and days_since_maintenance < 30:
                    urgency = "immediate"
            except ValueError:
                pass

        # Build recommended action from anomaly metrics
        action_parts = []
        for anomaly in anomaly_details:
            metric = anomaly.get("metric", "")
            action_key = "immediate" if anomaly.get("severity") == "critical" else "scheduled"
            action = _ACTION_MAP.get(metric, {}).get(action_key, "")
            if action and action not in action_parts:
                action_parts.append(action)

        if not action_parts:
            recommended_action = (
                f"Continue routine monitoring of {device_name}. "
                "All metrics are within normal operating ranges. "
                "Perform next scheduled preventive maintenance as planned."
            )
        else:
            recommended_action = " | ".join(action_parts)

        # Estimate downtime
        estimated_downtime = _get_downtime_estimate(urgency, anomaly_count)

        # Get required parts
        required_parts = _get_required_parts(anomaly_details)

        # Build rationale
        rationale_parts = [root_cause_summary]
        if days_since_maintenance is not None:
            rationale_parts.append(
                f"Last maintenance was {days_since_maintenance} days ago "
                f"(on {last_maintenance_str})."
            )
        avg_downtime = summary.get("average_downtime_hours", 0)
        if avg_downtime > 0:
            rationale_parts.append(
                f"Historical average downtime for this device is {avg_downtime} hours."
            )
        total_cost = summary.get("total_maintenance_cost_usd", 0)
        if total_cost > 0:
            rationale_parts.append(
                f"Total historical maintenance cost: ${total_cost:,.2f} USD."
            )
        rationale = " ".join(rationale_parts)

        # Historical context
        records = history_data.get("maintenance_records", [])
        recent_records = records[:3]  # Most recent 3
        historical_context = {
            "total_maintenance_events": history_data.get("total_records", 0),
            "last_maintenance_date": last_maintenance_str,
            "days_since_last_maintenance": days_since_maintenance,
            "recent_maintenance_types": [r.get("maintenance_type") for r in recent_records],
            "average_downtime_hours": avg_downtime,
            "total_maintenance_cost_usd": total_cost,
        }

        # Priority score (1-10)
        priority_map = {"immediate": 9, "scheduled": 5, "monitor": 2}
        priority_score = priority_map.get(urgency, 2)
        if anomaly_count >= 3:
            priority_score = min(10, priority_score + 1)

        result = {
            "device_name": device_name,
            "device_type": device_type,
            "urgency_level": urgency,
            "recommended_action": recommended_action,
            "estimated_downtime_hours": estimated_downtime,
            "required_parts": required_parts,
            "rationale": rationale,
            "historical_context": historical_context,
            "priority_score": priority_score,
            "anomaly_summary": {
                "severity_level": severity,
                "anomaly_count": anomaly_count,
                "critical_metrics": [
                    a["metric"] for a in anomaly_details if a.get("severity") == "critical"
                ],
                "warning_metrics": [
                    a["metric"] for a in anomaly_details if a.get("severity") == "warning"
                ],
            },
            "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({
            "device_name": device_name,
            "device_type": device_type,
            "urgency_level": "monitor",
            "recommended_action": f"Error generating recommendation: {str(e)}",
            "estimated_downtime_hours": 0.0,
            "required_parts": [],
            "rationale": f"Analysis error: {str(e)}",
            "historical_context": {},
            "priority_score": 1,
            "recommendation_timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2)

# Made with Bob
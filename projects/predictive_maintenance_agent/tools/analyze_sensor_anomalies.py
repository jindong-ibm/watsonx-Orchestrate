"""
Sensor Anomaly Analysis Tool

Analyzes IoT sensor data from manufacturing equipment to detect anomalies
and perform root cause analysis. Uses threshold-based detection with
device-type-specific thresholds for each sensor metric.
"""

import json
from typing import Optional
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# Anomaly thresholds by device type and metric
# Format: { device_type_keyword: { metric: (warning_threshold, critical_threshold) } }
_THRESHOLDS = {
    "pump": {
        "temperature_celsius":    (75.0,  90.0),
        "vibration_mm_per_s":     (6.0,   10.0),
        "pressure_bar":           (6.0,   8.0),
        "humidity_percent":       (70.0,  85.0),
        "power_consumption_kw":   (9.0,   11.0),
        "rpm":                    (1600,  1700),
    },
    "compressor": {
        "temperature_celsius":    (85.0,  100.0),
        "vibration_mm_per_s":     (7.5,   12.0),
        "pressure_bar":           (11.0,  13.0),
        "humidity_percent":       (70.0,  85.0),
        "power_consumption_kw":   (18.0,  22.0),
        "rpm":                    (3300,  3500),
    },
    "motor": {
        "temperature_celsius":    (80.0,  95.0),
        "vibration_mm_per_s":     (5.0,   8.0),
        "pressure_bar":           (3.0,   4.0),
        "humidity_percent":       (70.0,  85.0),
        "power_consumption_kw":   (13.0,  16.0),
        "rpm":                    (1900,  2000),
    },
    "conveyor": {
        "temperature_celsius":    (55.0,  70.0),
        "vibration_mm_per_s":     (3.0,   5.0),
        "pressure_bar":           (1.5,   2.5),
        "humidity_percent":       (70.0,  85.0),
        "power_consumption_kw":   (7.0,   9.0),
        "rpm":                    (70,    80),
    },
    "turbine": {
        "temperature_celsius":    (140.0, 160.0),
        "vibration_mm_per_s":     (12.0,  18.0),
        "pressure_bar":           (18.0,  22.0),
        "humidity_percent":       (70.0,  85.0),
        "power_consumption_kw":   (60.0,  70.0),
        "rpm":                    (3700,  3800),
    },
    "default": {
        "temperature_celsius":    (70.0,  85.0),
        "vibration_mm_per_s":     (5.0,   8.0),
        "pressure_bar":           (5.0,   7.0),
        "humidity_percent":       (70.0,  85.0),
        "power_consumption_kw":   (10.0,  13.0),
        "rpm":                    (1400,  1500),
    },
}

# Root cause mapping: metric anomaly → likely causes
_ROOT_CAUSE_MAP = {
    "temperature_celsius": {
        "warning":  "Elevated temperature may indicate insufficient cooling, increased friction, "
                    "or partial blockage in cooling passages. Check coolant flow and heat exchangers.",
        "critical": "Critical temperature indicates imminent thermal failure. Possible causes: "
                    "cooling system failure, bearing seizure, overloading, or blocked ventilation. "
                    "Immediate shutdown recommended.",
    },
    "vibration_mm_per_s": {
        "warning":  "Elevated vibration suggests early-stage bearing wear, misalignment, "
                    "imbalance, or loosened fasteners. Schedule vibration analysis.",
        "critical": "Critical vibration levels indicate severe bearing damage, shaft misalignment, "
                    "structural resonance, or impeller damage. Risk of catastrophic failure.",
    },
    "pressure_bar": {
        "warning":  "Abnormal pressure may indicate partial blockage, worn seals, valve issues, "
                    "or changes in process conditions. Inspect seals and flow paths.",
        "critical": "Critical pressure deviation indicates seal failure, major blockage, "
                    "or process upset. Risk of equipment damage or safety incident.",
    },
    "humidity_percent": {
        "warning":  "High humidity may accelerate corrosion and electrical insulation degradation. "
                    "Check environmental controls and moisture seals.",
        "critical": "Critical humidity levels risk electrical failures, corrosion damage, "
                    "and lubricant contamination. Inspect moisture ingress points.",
    },
    "power_consumption_kw": {
        "warning":  "Increased power consumption suggests mechanical inefficiency, increased load, "
                    "or electrical issues. Check for mechanical binding or process overload.",
        "critical": "Critical power consumption indicates severe mechanical resistance, "
                    "electrical fault, or overloading. Risk of motor burnout.",
    },
    "rpm": {
        "warning":  "RPM deviation from setpoint suggests drive belt wear, coupling slip, "
                    "or control system issues. Inspect drive components.",
        "critical": "Critical RPM deviation indicates drive failure, coupling damage, "
                    "or control system malfunction. Equipment may be operating unsafely.",
    },
}


def _get_thresholds(device_type: str) -> dict:
    """Get thresholds for the given device type."""
    device_type_lower = device_type.lower()
    for key in _THRESHOLDS:
        if key in device_type_lower:
            return _THRESHOLDS[key]
    return _THRESHOLDS["default"]


@tool(permission=ToolPermission.READ_ONLY)
def analyze_sensor_anomalies(
    device_name: str,
    device_type: str,
    sensor_data_json: str,
) -> str:
    """
    Analyze IoT sensor data to detect anomalies and perform root cause analysis.

    Applies device-type-specific thresholds to each sensor metric to identify
    warning and critical anomalies. For each anomaly detected, provides a
    root cause analysis with likely failure modes and recommended actions.

    Args:
        device_name: The unique name or identifier of the device (e.g., "PUMP-001")
        device_type: The type/category of the device (e.g., "centrifugal_pump",
                     "air_compressor", "electric_motor", "conveyor_belt", "turbine")
        sensor_data_json: JSON string from get_sensor_data containing the metrics object
                          with temperature_celsius, vibration_mm_per_s, pressure_bar,
                          humidity_percent, power_consumption_kw, and rpm fields

    Returns:
        JSON string containing:
        - device_name: Name of the device
        - device_type: Type of the device
        - anomalies_detected: Boolean indicating if any anomalies were found
        - severity_level: Overall severity ("normal", "warning", or "critical")
        - anomaly_count: Number of metrics with anomalies
        - anomaly_details: List of anomaly objects, each with:
            - metric: Name of the anomalous metric
            - current_value: Measured value
            - warning_threshold: Warning threshold for this metric
            - critical_threshold: Critical threshold for this metric
            - severity: "warning" or "critical"
            - root_cause: Likely causes and recommended actions
        - root_cause_summary: Combined summary of all root causes
        - healthy_metrics: List of metrics within normal range
        - analysis_timestamp: When the analysis was performed
    """
    try:
        # Parse sensor data
        sensor_data = json.loads(sensor_data_json)
        metrics = sensor_data.get("metrics", sensor_data)

        thresholds = _get_thresholds(device_type)
        anomaly_details = []
        healthy_metrics = []
        overall_severity = "normal"

        metric_labels = {
            "temperature_celsius":  "Temperature",
            "vibration_mm_per_s":   "Vibration",
            "pressure_bar":         "Pressure",
            "humidity_percent":     "Humidity",
            "power_consumption_kw": "Power Consumption",
            "rpm":                  "RPM",
        }

        for metric_key, (warn_thresh, crit_thresh) in thresholds.items():
            value = metrics.get(metric_key)
            if value is None:
                continue

            label = metric_labels.get(metric_key, metric_key)

            if value >= crit_thresh:
                severity = "critical"
                overall_severity = "critical"
                rca = _ROOT_CAUSE_MAP.get(metric_key, {}).get("critical", "Critical anomaly detected.")
                anomaly_details.append({
                    "metric": label,
                    "metric_key": metric_key,
                    "current_value": value,
                    "warning_threshold": warn_thresh,
                    "critical_threshold": crit_thresh,
                    "severity": severity,
                    "root_cause": rca,
                })
            elif value >= warn_thresh:
                severity = "warning"
                if overall_severity != "critical":
                    overall_severity = "warning"
                rca = _ROOT_CAUSE_MAP.get(metric_key, {}).get("warning", "Warning anomaly detected.")
                anomaly_details.append({
                    "metric": label,
                    "metric_key": metric_key,
                    "current_value": value,
                    "warning_threshold": warn_thresh,
                    "critical_threshold": crit_thresh,
                    "severity": severity,
                    "root_cause": rca,
                })
            else:
                healthy_metrics.append({
                    "metric": label,
                    "metric_key": metric_key,
                    "current_value": value,
                    "warning_threshold": warn_thresh,
                    "critical_threshold": crit_thresh,
                })

        # Build root cause summary
        if anomaly_details:
            critical_items = [a for a in anomaly_details if a["severity"] == "critical"]
            warning_items = [a for a in anomaly_details if a["severity"] == "warning"]

            summary_parts = []
            if critical_items:
                metrics_list = ", ".join(a["metric"] for a in critical_items)
                summary_parts.append(
                    f"CRITICAL anomalies detected in: {metrics_list}. "
                    "Immediate maintenance action required to prevent equipment failure."
                )
            if warning_items:
                metrics_list = ", ".join(a["metric"] for a in warning_items)
                summary_parts.append(
                    f"WARNING anomalies detected in: {metrics_list}. "
                    "Schedule maintenance within the next maintenance window."
                )
            root_cause_summary = " ".join(summary_parts)
        else:
            root_cause_summary = (
                f"All sensor metrics for {device_name} are within normal operating ranges. "
                "No anomalies detected. Continue routine monitoring."
            )

        from datetime import datetime, timezone
        result = {
            "device_name": device_name,
            "device_type": device_type,
            "anomalies_detected": len(anomaly_details) > 0,
            "severity_level": overall_severity,
            "anomaly_count": len(anomaly_details),
            "anomaly_details": anomaly_details,
            "root_cause_summary": root_cause_summary,
            "healthy_metrics": healthy_metrics,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({
            "device_name": device_name,
            "device_type": device_type,
            "anomalies_detected": False,
            "severity_level": "error",
            "anomaly_count": 0,
            "anomaly_details": [],
            "root_cause_summary": f"Error during analysis: {str(e)}",
            "healthy_metrics": [],
            "analysis_timestamp": "",
        }, indent=2)

# Made with Bob
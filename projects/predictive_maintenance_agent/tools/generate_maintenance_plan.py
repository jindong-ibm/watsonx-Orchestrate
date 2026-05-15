"""
Maintenance Plan Generator Tool

Generates a detailed maintenance plan with work items, scheduling, and resource
assignments based on the maintenance recommendation and spare parts availability.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# Work item templates by recommended action type
_WORK_ITEM_TEMPLATES = {
    "Temperature": [
        {
            "task": "Thermal inspection and temperature measurement",
            "duration_hours": 1.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Infrared thermometer", "Temperature data logger"],
        },
        {
            "task": "Cooling system inspection and cleaning",
            "duration_hours": 2.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Cleaning kit", "Pressure washer"],
        },
        {
            "task": "Bearing lubrication and inspection",
            "duration_hours": 1.5,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Grease gun", "Bearing puller", "Torque wrench"],
        },
    ],
    "Vibration": [
        {
            "task": "Vibration analysis and spectrum measurement",
            "duration_hours": 1.5,
            "skill_required": "Vibration Analyst",
            "tools_required": ["Vibration analyzer", "Accelerometer"],
        },
        {
            "task": "Shaft alignment check and correction",
            "duration_hours": 3.0,
            "skill_required": "Alignment Specialist",
            "tools_required": ["Laser alignment tool", "Dial indicator"],
        },
        {
            "task": "Bearing replacement",
            "duration_hours": 4.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Bearing puller", "Hydraulic press", "Torque wrench"],
        },
    ],
    "Pressure": [
        {
            "task": "Pressure system inspection and leak test",
            "duration_hours": 1.5,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Pressure gauge", "Leak detector"],
        },
        {
            "task": "Seal and gasket replacement",
            "duration_hours": 2.5,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Seal kit", "Torque wrench", "Gasket scraper"],
        },
        {
            "task": "Valve inspection and adjustment",
            "duration_hours": 1.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Valve wrench", "Pressure gauge"],
        },
    ],
    "Humidity": [
        {
            "task": "Environmental seal inspection",
            "duration_hours": 1.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Seal inspection kit", "Moisture meter"],
        },
        {
            "task": "Electrical insulation resistance test",
            "duration_hours": 1.5,
            "skill_required": "Electrical Technician",
            "tools_required": ["Megohmmeter", "Multimeter"],
        },
    ],
    "Power Consumption": [
        {
            "task": "Electrical system inspection and load test",
            "duration_hours": 2.0,
            "skill_required": "Electrical Technician",
            "tools_required": ["Power analyzer", "Clamp meter", "Multimeter"],
        },
        {
            "task": "Motor winding resistance test",
            "duration_hours": 1.5,
            "skill_required": "Electrical Technician",
            "tools_required": ["Megohmmeter", "Multimeter"],
        },
        {
            "task": "Mechanical binding inspection",
            "duration_hours": 1.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Torque wrench", "Feeler gauge"],
        },
    ],
    "RPM": [
        {
            "task": "Drive system inspection (belt/chain/coupling)",
            "duration_hours": 1.5,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Belt tension gauge", "Tachometer"],
        },
        {
            "task": "Speed control calibration",
            "duration_hours": 1.0,
            "skill_required": "Controls Technician",
            "tools_required": ["Tachometer", "Calibration kit"],
        },
    ],
    "default": [
        {
            "task": "General equipment inspection",
            "duration_hours": 2.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Inspection kit", "Multimeter"],
        },
        {
            "task": "Lubrication service",
            "duration_hours": 1.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Grease gun", "Oil can"],
        },
        {
            "task": "Functional test and performance verification",
            "duration_hours": 1.0,
            "skill_required": "Mechanical Technician",
            "tools_required": ["Test instruments", "Data logger"],
        },
    ],
}

# Safety precautions by device type
_SAFETY_PRECAUTIONS = {
    "centrifugal_pump": [
        "Isolate and lock out / tag out (LOTO) all energy sources before work",
        "Depressurize and drain the pump before opening",
        "Wear appropriate PPE: safety glasses, gloves, steel-toed boots",
        "Ensure proper ventilation if handling hazardous fluids",
    ],
    "air_compressor": [
        "Isolate and lock out / tag out (LOTO) all energy sources",
        "Bleed all pressure from the system before opening",
        "Wear hearing protection during operational tests",
        "Check for oil leaks before restart",
    ],
    "electric_motor": [
        "Isolate and lock out / tag out (LOTO) electrical supply",
        "Verify zero energy state with voltage tester before touching",
        "Wear insulated gloves for electrical work",
        "Ensure motor is cool before bearing work",
    ],
    "conveyor": [
        "Isolate and lock out / tag out (LOTO) all drive systems",
        "Block conveyor belt to prevent movement",
        "Clear all personnel from conveyor path before restart",
        "Inspect emergency stop systems before restart",
    ],
    "turbine": [
        "Follow full turbine shutdown procedure before any maintenance",
        "Allow adequate cool-down time (minimum 4 hours)",
        "Isolate steam/gas supply and verify zero pressure",
        "Use confined space entry procedures if applicable",
    ],
    "default": [
        "Isolate and lock out / tag out (LOTO) all energy sources",
        "Wear appropriate PPE for the task",
        "Follow site safety procedures and permit-to-work system",
        "Ensure area is clear before restart",
    ],
}


def _get_scheduled_date(urgency: str) -> str:
    """Calculate scheduled maintenance date based on urgency."""
    now = datetime.now(timezone.utc)
    if urgency == "immediate":
        scheduled = now + timedelta(hours=4)
    elif urgency == "scheduled":
        # Next business day or within 7 days
        scheduled = now + timedelta(days=2)
        # Skip to Monday if weekend
        if scheduled.weekday() >= 5:
            scheduled += timedelta(days=7 - scheduled.weekday())
    else:
        # Monitor: next scheduled maintenance window (30 days)
        scheduled = now + timedelta(days=30)
    return scheduled.strftime("%Y-%m-%d %H:%M UTC")


def _build_work_items(anomaly_metrics: list, device_name: str, urgency: str) -> list:
    """Build ordered work items from anomaly metrics."""
    work_items = []
    seen_tasks = set()
    item_number = 1

    # Add safety pre-work
    work_items.append({
        "item_number": item_number,
        "task": "Safety isolation and LOTO procedure",
        "duration_hours": 0.5,
        "skill_required": "Certified Technician",
        "tools_required": ["LOTO kit", "Voltage tester"],
        "category": "safety",
        "status": "pending",
    })
    item_number += 1

    # Add metric-specific work items
    for metric in anomaly_metrics:
        templates = _WORK_ITEM_TEMPLATES.get(metric, [])
        for tmpl in templates:
            if tmpl["task"] not in seen_tasks:
                seen_tasks.add(tmpl["task"])
                work_items.append({
                    "item_number": item_number,
                    "task": tmpl["task"],
                    "duration_hours": tmpl["duration_hours"],
                    "skill_required": tmpl["skill_required"],
                    "tools_required": tmpl["tools_required"],
                    "category": "maintenance",
                    "status": "pending",
                })
                item_number += 1

    # If no specific metrics, use default
    if item_number == 2:
        for tmpl in _WORK_ITEM_TEMPLATES["default"]:
            work_items.append({
                "item_number": item_number,
                "task": tmpl["task"],
                "duration_hours": tmpl["duration_hours"],
                "skill_required": tmpl["skill_required"],
                "tools_required": tmpl["tools_required"],
                "category": "maintenance",
                "status": "pending",
            })
            item_number += 1

    # Add post-maintenance verification
    work_items.append({
        "item_number": item_number,
        "task": "Post-maintenance functional test and performance verification",
        "duration_hours": 1.0,
        "skill_required": "Mechanical Technician",
        "tools_required": ["Test instruments", "Data logger"],
        "category": "verification",
        "status": "pending",
    })
    item_number += 1

    # Add LOTO removal and restart
    work_items.append({
        "item_number": item_number,
        "task": "LOTO removal and controlled restart",
        "duration_hours": 0.5,
        "skill_required": "Certified Technician",
        "tools_required": ["LOTO kit"],
        "category": "safety",
        "status": "pending",
    })

    return work_items


@tool(permission=ToolPermission.READ_ONLY)
def generate_maintenance_plan(
    device_name: str,
    device_type: str,
    recommendation_json: str,
    spare_parts_json: str,
) -> str:
    """
    Generate a detailed maintenance plan with work items and scheduling.

    Creates a comprehensive maintenance plan including ordered work items,
    resource requirements, safety precautions, scheduling, and parts list
    based on the maintenance recommendation and spare parts availability.

    Args:
        device_name: The unique name or identifier of the device (e.g., "PUMP-001")
        device_type: The type/category of the device (e.g., "centrifugal_pump")
        recommendation_json: JSON string output from generate_maintenance_recommendation tool
        spare_parts_json: JSON string output from get_spare_parts MCP tool

    Returns:
        JSON string containing:
        - plan_id: Unique identifier for this maintenance plan
        - device_name: Name of the device
        - device_type: Type of the device
        - urgency_level: Urgency of the maintenance
        - scheduled_date: When maintenance should be performed
        - estimated_total_duration_hours: Total estimated time for all work items
        - work_items: Ordered list of maintenance tasks
        - required_parts: Parts needed with availability status
        - safety_precautions: Safety requirements for this device type
        - assigned_team: Recommended team composition
        - estimated_total_cost_usd: Estimated total cost (labor + parts)
        - plan_status: Current status of the plan
        - plan_created_timestamp: When the plan was generated
    """
    try:
        rec_data = json.loads(recommendation_json)
        parts_data = json.loads(spare_parts_json)

        urgency = rec_data.get("urgency_level", "monitor")
        required_part_ids = rec_data.get("required_parts", [])
        estimated_downtime = rec_data.get("estimated_downtime_hours", 4.0)
        anomaly_summary = rec_data.get("anomaly_summary", {})
        critical_metrics = anomaly_summary.get("critical_metrics", [])
        warning_metrics = anomaly_summary.get("warning_metrics", [])
        all_anomaly_metrics = critical_metrics + warning_metrics

        # Build work items
        work_items = _build_work_items(all_anomaly_metrics, device_name, urgency)
        total_duration = sum(item["duration_hours"] for item in work_items)

        # Build parts list with availability
        parts_list = []
        total_parts_cost = 0.0
        parts_available = []

        if isinstance(parts_data, list):
            parts_records = parts_data
        elif isinstance(parts_data, dict):
            parts_records = parts_data.get("parts", [parts_data])
        else:
            parts_records = []

        for part in parts_records:
            part_id = part.get("part_id", "")
            stock = part.get("stock_quantity", 0)
            reorder = part.get("reorder_level", 0)
            unit_price = part.get("unit_price", 0.0)
            qty_needed = 1
            availability = "available" if stock >= qty_needed else "low_stock"
            if stock == 0:
                availability = "out_of_stock"

            part_entry = {
                "part_id": part_id,
                "part_name": part.get("part_name", ""),
                "part_number": part.get("part_number", ""),
                "quantity_needed": qty_needed,
                "stock_available": stock,
                "availability_status": availability,
                "unit_price_usd": unit_price,
                "total_price_usd": unit_price * qty_needed,
            }
            parts_list.append(part_entry)
            total_parts_cost += unit_price * qty_needed
            parts_available.append(availability in ("available",))

        # Estimate labor cost (assume $85/hr blended rate)
        labor_rate = 85.0
        total_labor_cost = total_duration * labor_rate
        total_cost = total_labor_cost + total_parts_cost

        # Safety precautions
        safety = _SAFETY_PRECAUTIONS.get(
            device_type, _SAFETY_PRECAUTIONS["default"]
        )

        # Determine team composition
        skills_needed = set(item["skill_required"] for item in work_items)
        team_size = max(2, len(skills_needed))
        assigned_team = {
            "team_size": team_size,
            "roles_required": sorted(list(skills_needed)),
            "estimated_labor_hours": total_duration,
            "labor_rate_per_hour_usd": labor_rate,
        }

        # Scheduled date
        scheduled_date = _get_scheduled_date(urgency)

        plan = {
            "plan_id": f"MP-{uuid.uuid4().hex[:8].upper()}",
            "device_name": device_name,
            "device_type": device_type,
            "urgency_level": urgency,
            "scheduled_date": scheduled_date,
            "estimated_total_duration_hours": round(total_duration, 1),
            "work_items": work_items,
            "required_parts": parts_list,
            "safety_precautions": safety,
            "assigned_team": assigned_team,
            "estimated_total_cost_usd": round(total_cost, 2),
            "estimated_labor_cost_usd": round(total_labor_cost, 2),
            "estimated_parts_cost_usd": round(total_parts_cost, 2),
            "plan_status": "draft",
            "anomaly_context": {
                "severity_level": anomaly_summary.get("severity_level", "normal"),
                "critical_metrics": critical_metrics,
                "warning_metrics": warning_metrics,
                "recommended_action": rec_data.get("recommended_action", ""),
            },
            "plan_created_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(plan, indent=2)

    except Exception as e:
        return json.dumps({
            "plan_id": f"MP-ERROR-{uuid.uuid4().hex[:6].upper()}",
            "device_name": device_name,
            "device_type": device_type,
            "urgency_level": "monitor",
            "scheduled_date": "",
            "estimated_total_duration_hours": 0.0,
            "work_items": [],
            "required_parts": [],
            "safety_precautions": [],
            "assigned_team": {},
            "estimated_total_cost_usd": 0.0,
            "plan_status": "error",
            "error": str(e),
            "plan_created_timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2)

# Made with Bob
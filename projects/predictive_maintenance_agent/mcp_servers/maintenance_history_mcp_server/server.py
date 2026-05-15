"""
Maintenance History MCP Server

Provides maintenance history records for manufacturing equipment via the
Model Context Protocol. Returns historical maintenance data including
maintenance type, dates, technician info, costs, parts used, and downtime.

Replace the simulated data with real CMMS/EAM database queries (e.g., IBM Maximo,
SAP PM, Infor EAM) for production use.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Maintenance History MCP Server")


def _generate_maintenance_records(device_name: str, device_type: str) -> list:
    """Generate realistic simulated maintenance history records."""
    device_type_lower = device_type.lower()

    # Maintenance types vary by device
    if "pump" in device_type_lower:
        maintenance_types = ["Seal Replacement", "Bearing Replacement", "Impeller Inspection",
                             "Lubrication Service", "Vibration Analysis", "Preventive Maintenance"]
        common_parts = ["SEAL-001", "BEAR-002", "IMP-003", "GASKET-004", "LUBR-005"]
    elif "compressor" in device_type_lower:
        maintenance_types = ["Valve Replacement", "Filter Change", "Belt Replacement",
                             "Oil Change", "Pressure Test", "Preventive Maintenance"]
        common_parts = ["VALVE-010", "FILT-011", "BELT-012", "OIL-013", "SEAL-014"]
    elif "motor" in device_type_lower:
        maintenance_types = ["Bearing Replacement", "Winding Inspection", "Brush Replacement",
                             "Cooling Fan Service", "Insulation Test", "Preventive Maintenance"]
        common_parts = ["BEAR-020", "BRUSH-021", "FAN-022", "WIND-023", "INSUL-024"]
    elif "conveyor" in device_type_lower:
        maintenance_types = ["Belt Replacement", "Roller Replacement", "Tensioner Adjustment",
                             "Drive Chain Lubrication", "Alignment Check", "Preventive Maintenance"]
        common_parts = ["BELT-030", "ROLL-031", "TENS-032", "CHAIN-033", "SPRK-034"]
    else:
        maintenance_types = ["General Inspection", "Lubrication Service", "Component Replacement",
                             "Calibration", "Cleaning", "Preventive Maintenance"]
        common_parts = ["PART-100", "PART-101", "PART-102", "PART-103", "PART-104"]

    technicians = [
        "John Martinez", "Sarah Chen", "Mike Thompson", "Lisa Patel",
        "David Kim", "Emma Wilson", "Carlos Rodriguez", "Anna Kowalski"
    ]

    records = []
    base_date = datetime.now(timezone.utc)

    # Generate 3-6 historical records
    num_records = random.randint(3, 6)
    for i in range(num_records):
        # Records spread over past 18 months
        days_ago = random.randint(i * 60 + 10, i * 60 + 90)
        maintenance_date = base_date - timedelta(days=days_ago)
        duration_days = random.randint(1, 3)
        completion_date = maintenance_date + timedelta(days=duration_days)

        maint_type = random.choice(maintenance_types)
        technician = random.choice(technicians)
        parts_used = random.sample(common_parts, k=random.randint(1, 3))
        downtime = round(random.uniform(2.0, 24.0), 1)
        cost = round(random.uniform(500.0, 8000.0), 2)
        status = "completed" if i > 0 else random.choice(["completed", "completed", "in_progress"])

        records.append({
            "maintenance_id": f"MNT-{device_name}-{1000 + i}",
            "maintenance_type": maint_type,
            "maintenance_date": maintenance_date.strftime("%Y-%m-%d"),
            "completion_date": completion_date.strftime("%Y-%m-%d") if status == "completed" else None,
            "technician_name": technician,
            "cost": cost,
            "part_ids": parts_used,
            "downtime_hours": downtime,
            "status": status,
            "description": f"{maint_type} performed on {device_name} ({device_type}). "
                           f"Parts replaced: {', '.join(parts_used)}. "
                           f"Equipment returned to service after {downtime} hours downtime."
        })

    # Sort by date descending (most recent first)
    records.sort(key=lambda r: r["maintenance_date"], reverse=True)
    return records


@mcp.tool()
def get_maintenance_history(device_name: str, device_type: str) -> str:
    """
    Retrieve maintenance history records for a manufacturing device.

    Queries the CMMS/EAM database for all historical maintenance activities
    performed on the specified device, including preventive and corrective
    maintenance records.

    Args:
        device_name: The unique name or identifier of the device (e.g., "PUMP-001")
        device_type: The type/category of the device (e.g., "centrifugal_pump",
                     "air_compressor", "electric_motor", "conveyor_belt")

    Returns:
        JSON string containing:
        - device_name: Name of the device
        - device_type: Type of the device
        - total_records: Number of maintenance records found
        - maintenance_records: List of records, each containing:
            - maintenance_id: Unique maintenance record identifier
            - maintenance_type: Type of maintenance performed
            - maintenance_date: Date maintenance was initiated (YYYY-MM-DD)
            - completion_date: Date maintenance was completed (YYYY-MM-DD or null)
            - technician_name: Name of the technician who performed the work
            - cost: Total cost of the maintenance activity in USD
            - part_ids: List of part IDs used during maintenance
            - downtime_hours: Total equipment downtime in hours
            - status: Status of the maintenance (completed/in_progress/scheduled)
            - description: Detailed description of work performed
        - summary: Aggregated statistics (total cost, avg downtime, last maintenance date)
        - status: "ok" or "error"
    """
    try:
        records = _generate_maintenance_records(device_name, device_type)

        # Calculate summary statistics
        completed = [r for r in records if r["status"] == "completed"]
        total_cost = sum(r["cost"] for r in completed)
        avg_downtime = (sum(r["downtime_hours"] for r in completed) / len(completed)
                        if completed else 0.0)
        last_maintenance = records[0]["maintenance_date"] if records else None

        result = {
            "device_name": device_name,
            "device_type": device_type,
            "total_records": len(records),
            "maintenance_records": records,
            "summary": {
                "total_maintenance_cost_usd": round(total_cost, 2),
                "average_downtime_hours": round(avg_downtime, 1),
                "last_maintenance_date": last_maintenance,
                "completed_count": len(completed),
                "in_progress_count": len([r for r in records if r["status"] == "in_progress"]),
            },
            "status": "ok",
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_result = {
            "device_name": device_name,
            "device_type": device_type,
            "status": "error",
            "error": str(e),
        }
        return json.dumps(error_result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")

# Made with Bob

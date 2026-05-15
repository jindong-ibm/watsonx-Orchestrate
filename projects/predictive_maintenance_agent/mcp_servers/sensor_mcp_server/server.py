"""
Sensor MCP Server

Provides IoT sensor data for manufacturing equipment via the Model Context Protocol.
Returns simulated sensor metrics including temperature, vibration, pressure,
humidity, power consumption, and RPM.

Replace the simulated data with real IoT platform API calls (e.g., AWS IoT,
Azure IoT Hub, IBM Maximo) for production use.
"""

import json
import random
from datetime import datetime, timezone
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Sensor MCP Server")


def _simulate_sensor_data(device_name: str, device_type: str) -> dict:
    """Generate realistic simulated sensor readings based on device type."""
    device_type_lower = device_type.lower()

    # Base ranges vary by device type
    if "pump" in device_type_lower:
        temp_base, vib_base, pressure_base = 65.0, 3.5, 4.2
        rpm_base, power_base = 1450, 7.5
    elif "compressor" in device_type_lower:
        temp_base, vib_base, pressure_base = 75.0, 5.0, 8.5
        rpm_base, power_base = 3000, 15.0
    elif "motor" in device_type_lower:
        temp_base, vib_base, pressure_base = 70.0, 2.8, 2.0
        rpm_base, power_base = 1800, 11.0
    elif "conveyor" in device_type_lower:
        temp_base, vib_base, pressure_base = 45.0, 1.5, 1.0
        rpm_base, power_base = 60, 5.5
    elif "turbine" in device_type_lower:
        temp_base, vib_base, pressure_base = 120.0, 8.0, 15.0
        rpm_base, power_base = 3600, 50.0
    else:
        # Generic industrial equipment defaults
        temp_base, vib_base, pressure_base = 60.0, 3.0, 3.5
        rpm_base, power_base = 1200, 8.0

    # Add random variation (±10%)
    def vary(base: float, pct: float = 0.10) -> float:
        return round(base * (1 + random.uniform(-pct, pct)), 2)

    return {
        "temperature_celsius": vary(temp_base),
        "vibration_mm_per_s": vary(vib_base),
        "pressure_bar": vary(pressure_base),
        "humidity_percent": round(random.uniform(35.0, 65.0), 2),
        "power_consumption_kw": vary(power_base),
        "rpm": int(vary(rpm_base, 0.05)),
    }


@mcp.tool()
def get_sensor_data(device_name: str, device_type: str, timestamp: str) -> str:
    """
    Retrieve real-time IoT sensor data for a manufacturing device.

    Fetches the latest sensor readings from the IoT platform for the specified
    device. Returns a JSON object containing all available sensor metrics.

    Args:
        device_name: The unique name or identifier of the device (e.g., "PUMP-001")
        device_type: The type/category of the device (e.g., "centrifugal_pump",
                     "air_compressor", "electric_motor", "conveyor_belt", "turbine")
        timestamp: ISO 8601 timestamp for the data request (e.g., "2026-02-27T20:00:00Z")

    Returns:
        JSON string containing:
        - device_name: Name of the device
        - device_type: Type of the device
        - timestamp: Timestamp of the reading
        - metrics: Object with sensor readings:
            - temperature_celsius: Operating temperature in Celsius
            - vibration_mm_per_s: Vibration level in mm/s (RMS)
            - pressure_bar: Operating pressure in bar
            - humidity_percent: Ambient humidity percentage
            - power_consumption_kw: Power consumption in kilowatts
            - rpm: Rotational speed in revolutions per minute
        - status: "ok" or "error"
    """
    try:
        # Validate timestamp
        if not timestamp:
            timestamp = datetime.now(timezone.utc).isoformat()

        metrics = _simulate_sensor_data(device_name, device_type)

        result = {
            "device_name": device_name,
            "device_type": device_type,
            "timestamp": timestamp,
            "reading_timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "unit_info": {
                "temperature": "Celsius",
                "vibration": "mm/s RMS",
                "pressure": "bar",
                "humidity": "percent",
                "power_consumption": "kilowatts",
                "rpm": "revolutions per minute",
            },
            "status": "ok",
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_result = {
            "device_name": device_name,
            "device_type": device_type,
            "timestamp": timestamp,
            "status": "error",
            "error": str(e),
        }
        return json.dumps(error_result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")

# Made with Bob

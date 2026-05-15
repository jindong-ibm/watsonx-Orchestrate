"""
Spare Parts MCP Server

Provides spare parts inventory management for manufacturing equipment via the
Model Context Protocol. Supports querying part stock levels and placing orders
when stock falls below reorder thresholds.

Replace the simulated data with real ERP/inventory system API calls (e.g.,
SAP MM, Oracle Inventory, IBM Maximo) for production use.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Spare Parts MCP Server")

# Simulated parts catalog (in production, this would query a real database)
_PARTS_CATALOG = {
    "SEAL-001": {"part_number": "SL-001-A", "part_name": "Mechanical Seal Kit", "category": "Seals",
                 "manufacturer": "SKF", "stock_quantity": 8, "reorder_level": 5, "unit_price": 245.00},
    "BEAR-002": {"part_number": "BR-6205-ZZ", "part_name": "Deep Groove Ball Bearing 6205-ZZ",
                 "category": "Bearings", "manufacturer": "NSK",
                 "stock_quantity": 3, "reorder_level": 6, "unit_price": 32.50},
    "IMP-003": {"part_number": "IMP-150-SS", "part_name": "Stainless Steel Impeller 150mm",
                "category": "Pump Components", "manufacturer": "Grundfos",
                "stock_quantity": 2, "reorder_level": 2, "unit_price": 890.00},
    "GASKET-004": {"part_number": "GSK-VITON-4", "part_name": "Viton Gasket Set",
                   "category": "Seals", "manufacturer": "Parker",
                   "stock_quantity": 15, "reorder_level": 8, "unit_price": 45.00},
    "LUBR-005": {"part_number": "LUB-GREASE-5", "part_name": "High-Temp Bearing Grease 500g",
                 "category": "Lubricants", "manufacturer": "Mobil",
                 "stock_quantity": 20, "reorder_level": 10, "unit_price": 28.00},
    "VALVE-010": {"part_number": "VLV-CHECK-10", "part_name": "Check Valve 2-inch",
                  "category": "Valves", "manufacturer": "Swagelok",
                  "stock_quantity": 4, "reorder_level": 3, "unit_price": 320.00},
    "FILT-011": {"part_number": "FLT-AIR-11", "part_name": "Air Filter Element",
                 "category": "Filters", "manufacturer": "Donaldson",
                 "stock_quantity": 12, "reorder_level": 6, "unit_price": 55.00},
    "BELT-012": {"part_number": "BLT-V-12", "part_name": "V-Belt Drive Belt",
                 "category": "Drive Components", "manufacturer": "Gates",
                 "stock_quantity": 6, "reorder_level": 4, "unit_price": 78.00},
    "BEAR-020": {"part_number": "BR-6308-2RS", "part_name": "Sealed Ball Bearing 6308-2RS",
                 "category": "Bearings", "manufacturer": "FAG",
                 "stock_quantity": 2, "reorder_level": 4, "unit_price": 48.00},
    "BRUSH-021": {"part_number": "BRH-CARBON-21", "part_name": "Carbon Brush Set",
                  "category": "Electrical", "manufacturer": "Mersen",
                  "stock_quantity": 10, "reorder_level": 5, "unit_price": 35.00},
    "BELT-030": {"part_number": "BLT-CONV-30", "part_name": "Conveyor Belt 1000mm x 10m",
                 "category": "Conveyor Components", "manufacturer": "Habasit",
                 "stock_quantity": 1, "reorder_level": 2, "unit_price": 1250.00},
    "ROLL-031": {"part_number": "RLL-CARRY-31", "part_name": "Carrying Roller 89mm",
                 "category": "Conveyor Components", "manufacturer": "Rulmeca",
                 "stock_quantity": 18, "reorder_level": 10, "unit_price": 42.00},
    "PART-100": {"part_number": "GEN-100", "part_name": "Generic Replacement Part A",
                 "category": "General", "manufacturer": "OEM",
                 "stock_quantity": 5, "reorder_level": 3, "unit_price": 150.00},
    "PART-101": {"part_number": "GEN-101", "part_name": "Generic Replacement Part B",
                 "category": "General", "manufacturer": "OEM",
                 "stock_quantity": 7, "reorder_level": 4, "unit_price": 95.00},
}


def _find_part(part_id: str = "", part_number: str = "", part_name: str = "",
               category: str = "", manufacturer: str = "") -> list:
    """Find parts matching the given criteria."""
    results = []
    for pid, pdata in _PARTS_CATALOG.items():
        match = False
        if part_id and pid.upper() == part_id.upper():
            match = True
        elif part_number and pdata["part_number"].upper() == part_number.upper():
            match = True
        elif part_name and part_name.lower() in pdata["part_name"].lower():
            match = True
        elif category and category.lower() in pdata["category"].lower():
            match = True
        elif manufacturer and manufacturer.lower() in pdata["manufacturer"].lower():
            match = True
        elif not any([part_id, part_number, part_name, category, manufacturer]):
            # No filters — return all
            match = True

        if match:
            results.append({"part_id": pid, **pdata})

    return results


@mcp.tool()
def get_spare_parts(
    part_id: str = "",
    part_number: str = "",
    part_name: str = "",
    category: str = "",
    manufacturer: str = "",
) -> str:
    """
    Query spare parts inventory for stock levels and pricing.

    Searches the spare parts inventory system for parts matching the given
    criteria and returns current stock levels, reorder thresholds, and pricing.
    At least one search parameter should be provided; if none are provided,
    all parts are returned.

    Args:
        part_id: Internal part identifier (e.g., "BEAR-002")
        part_number: Manufacturer part number (e.g., "BR-6205-ZZ")
        part_name: Part name or partial name (e.g., "bearing")
        category: Part category (e.g., "Bearings", "Seals", "Filters")
        manufacturer: Manufacturer name (e.g., "SKF", "NSK")

    Returns:
        JSON string containing:
        - parts: List of matching parts, each with:
            - part_id: Internal part identifier
            - part_number: Manufacturer part number
            - part_name: Descriptive part name
            - category: Part category
            - manufacturer: Part manufacturer
            - stock_quantity: Current quantity in stock
            - reorder_level: Minimum stock level before reorder is triggered
            - unit_price: Price per unit in USD
            - needs_reorder: Boolean indicating if stock is at or below reorder level
        - total_found: Number of matching parts
        - status: "ok" or "error"
    """
    try:
        parts = _find_part(part_id, part_number, part_name, category, manufacturer)

        # Add needs_reorder flag
        for part in parts:
            part["needs_reorder"] = part["stock_quantity"] <= part["reorder_level"]

        result = {
            "parts": parts,
            "total_found": len(parts),
            "query": {
                "part_id": part_id,
                "part_number": part_number,
                "part_name": part_name,
                "category": category,
                "manufacturer": manufacturer,
            },
            "status": "ok",
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"parts": [], "total_found": 0, "status": "error", "error": str(e)}, indent=2)


@mcp.tool()
def order_spare_parts(
    part_id: str,
    part_number: str,
    part_name: str,
    category: str,
    manufacturer: str,
    quantity_to_order: int,
) -> str:
    """
    Place an order for spare parts when stock is below the reorder level.

    Creates a purchase order for the specified part and quantity. The order
    is submitted to the procurement system for approval and fulfillment.

    Args:
        part_id: Internal part identifier (e.g., "BEAR-002")
        part_number: Manufacturer part number (e.g., "BR-6205-ZZ")
        part_name: Descriptive name of the part
        category: Part category
        manufacturer: Part manufacturer
        quantity_to_order: Number of units to order (must be > 0)

    Returns:
        JSON string containing:
        - order_id: Unique purchase order identifier
        - part_id: Part identifier ordered
        - part_name: Name of the part ordered
        - quantity_ordered: Number of units ordered
        - unit_price: Price per unit in USD
        - total_cost: Total order cost in USD
        - estimated_delivery_date: Expected delivery date (YYYY-MM-DD)
        - order_status: "submitted" or "error"
        - message: Human-readable status message
        - status: "ok" or "error"
    """
    try:
        if quantity_to_order <= 0:
            return json.dumps({
                "status": "error",
                "error": "quantity_to_order must be greater than 0"
            }, indent=2)

        # Look up part details
        parts = _find_part(part_id=part_id, part_number=part_number)
        if not parts:
            # Try by name if ID/number not found
            parts = _find_part(part_name=part_name)

        unit_price = parts[0]["unit_price"] if parts else 100.00
        resolved_part_id = parts[0]["part_id"] if parts else part_id

        order_id = f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
        estimated_delivery = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
        total_cost = round(unit_price * quantity_to_order, 2)

        result = {
            "order_id": order_id,
            "part_id": resolved_part_id,
            "part_number": part_number,
            "part_name": part_name,
            "category": category,
            "manufacturer": manufacturer,
            "quantity_ordered": quantity_to_order,
            "unit_price": unit_price,
            "total_cost": total_cost,
            "estimated_delivery_date": estimated_delivery,
            "order_status": "submitted",
            "message": (
                f"Purchase order {order_id} submitted successfully for {quantity_to_order} unit(s) "
                f"of {part_name}. Estimated delivery: {estimated_delivery}. "
                f"Total cost: ${total_cost:.2f} USD."
            ),
            "status": "ok",
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")

# Made with Bob

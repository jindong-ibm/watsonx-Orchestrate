"""
Predictive Maintenance Flow — Local Test Script

Tests the predictive_maintenance_flow locally using the ADK's compile_deploy()
and invoke() APIs before deploying to watsonx Orchestrate.

Usage:
    # Ensure the ADK environment is active and orchestrate server is running:
    orchestrate server start

    # Run this script:
    python flow_main.py

    # Or with custom device parameters:
    python flow_main.py --device-name PUMP-001 --device-type centrifugal_pump
"""

import asyncio
import argparse
import json
import sys
from tools.predictive_maintenance_flow import build_predictive_maintenance_flow


async def run_flow(device_name: str, device_type: str, timestamp: str = "") -> None:
    """
    Compile, deploy, and invoke the predictive maintenance flow.

    Args:
        device_name: Device identifier (e.g., "PUMP-001")
        device_type: Device type (e.g., "centrifugal_pump")
        timestamp: Optional ISO 8601 timestamp for sensor data
    """
    print(f"\n{'='*60}")
    print(f"  Predictive Maintenance Flow — Local Test")
    print(f"{'='*60}")
    print(f"  Device Name : {device_name}")
    print(f"  Device Type : {device_type}")
    print(f"  Timestamp   : {timestamp or '(current time)'}")
    print(f"{'='*60}\n")

    # Step 1: Compile and deploy the flow
    print("⏳ Compiling and deploying flow...")
    try:
        compiled_flow = await build_predictive_maintenance_flow.compile_deploy()  # type: ignore[attr-defined]
        print("✅ Flow compiled and deployed successfully.\n")
    except Exception as e:
        print(f"❌ Failed to compile/deploy flow: {e}")
        sys.exit(1)

    # Step 2: Invoke the flow with input data
    input_data = {
        "device_name": device_name,
        "device_type": device_type,
        "timestamp": timestamp,
    }
    print(f"🚀 Invoking flow with input: {json.dumps(input_data, indent=2)}\n")
    print("ℹ️  Note: The flow includes human-in-the-loop steps.")
    print("   When prompted, review the recommendation and select Approve/Reject.\n")

    try:
        flow_run = await compiled_flow.invoke(input_data)
        print("\n" + "="*60)
        print("  Flow Completed Successfully")
        print("="*60)
        if flow_run and hasattr(flow_run, "output") and flow_run.output:
            report = flow_run.output.get("maintenance_report", "")
            if report:
                print("\n📋 MAINTENANCE REPORT:\n")
                print(report)
            else:
                print(f"\nFlow output: {flow_run.output}")
        else:
            print(f"\nFlow run result: {flow_run}")
    except Exception as e:
        print(f"\n❌ Flow invocation failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Test the Predictive Maintenance Flow locally"
    )
    parser.add_argument(
        "--device-name",
        default="PUMP-001",
        help="Device name/identifier (default: PUMP-001)",
    )
    parser.add_argument(
        "--device-type",
        default="centrifugal_pump",
        choices=[
            "centrifugal_pump",
            "air_compressor",
            "electric_motor",
            "conveyor",
            "turbine",
        ],
        help="Device type (default: centrifugal_pump)",
    )
    parser.add_argument(
        "--timestamp",
        default="",
        help="ISO 8601 timestamp for sensor data (default: current time)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_flow(
            device_name=args.device_name,
            device_type=args.device_type,
            timestamp=args.timestamp,
        )
    )


if __name__ == "__main__":
    main()

# Made with Bob
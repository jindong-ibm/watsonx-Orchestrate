"""
main_flow.py — Local test harness for the MDP Patient Monitoring Flow

Run with:
  cd mdp_patient_monitoring
  python main_flow.py

This script:
  1. Compiles and deploys the MDP monitoring flow
  2. Dumps the compiled spec to generated/mdp_patient_monitoring_flow.json
  3. Invokes the flow with three test scenarios:
     - A stable patient (S0)
     - A moderate-risk patient (S2)
     - A critical patient (S3)
"""

import asyncio
import json
from pathlib import Path

from mdp_patient_monitoring.tools.mdp_monitoring_flow import build_mdp_patient_monitoring_flow

GENERATED = Path(__file__).resolve().parent / "generated"
GENERATED.mkdir(exist_ok=True)

_TEST_CASES = [
    {
        "label": "Stable Patient (S0 → S0)",
        "input": {
            "patient_id": "P-1001",
            "heart_rate": 72.0,
            "systolic_bp": 120.0,
            "diastolic_bp": 78.0,
            "spo2": 98.0,
            "temperature": 36.8,
            "respiratory_rate": 15.0,
            "previous_state": "S0_STABLE",
            "previous_action": "CONTINUE_MONITORING",
            "previous_cumulative_reward": 0.0,
            "current_q_table_json": "{}",
            "check_completed_on_time": True,
        },
    },
    {
        "label": "Moderate Risk Patient (S1 → S2)",
        "input": {
            "patient_id": "P-2034",
            "heart_rate": 108.0,
            "systolic_bp": 148.0,
            "diastolic_bp": 92.0,
            "spo2": 94.0,
            "temperature": 38.4,
            "respiratory_rate": 22.0,
            "previous_state": "S1_MILD",
            "previous_action": "INCREASE_MONITORING",
            "previous_cumulative_reward": 3.0,
            "current_q_table_json": "{}",
            "check_completed_on_time": True,
        },
    },
    {
        "label": "Critical Patient (S2 → S3)",
        "input": {
            "patient_id": "P-3017",
            "heart_rate": 155.0,
            "systolic_bp": 65.0,
            "diastolic_bp": 40.0,
            "spo2": 88.0,
            "temperature": 40.5,
            "respiratory_rate": 32.0,
            "previous_state": "S2_MODERATE",
            "previous_action": "CLINICAL_REVIEW",
            "previous_cumulative_reward": -2.0,
            "current_q_table_json": "{}",
            "check_completed_on_time": False,
        },
    },
]


async def main() -> None:
    print("Compiling MDP Patient Monitoring Flow…")
    flow_def = await build_mdp_patient_monitoring_flow().compile_deploy()
    spec_path = GENERATED / "mdp_patient_monitoring_flow.json"
    flow_def.dump_spec(str(spec_path))
    print(f"  ✓ Spec written to {spec_path}\n")

    for case in _TEST_CASES:
        print(f"{'─' * 60}")
        print(f"  Test: {case['label']}")
        print(f"{'─' * 60}")
        result = await flow_def.invoke(case["input"], debug=False)
        print(json.dumps(result, indent=2, default=str))
        print()

    print("All test cases complete.")


if __name__ == "__main__":
    asyncio.run(main())

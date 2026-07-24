"""
main_flow.py — Local test harness for the CMMN Insurance Claims Flow

Run with:
  python cmmn_insurance_claims/main_flow.py

Test scenarios:
  1. Standard AUTO claim — no fraud signals, normal flow → APPROVED
  2. PROPERTY claim with high fraud signals → INVESTIGATION stage triggered
  3. MEDICAL claim with lapsed policy → immediate DENIED closure
  4. LIABILITY claim with claimant counter-offer → NEGOTIATING
"""

import asyncio
import json
from pathlib import Path

from cmmn_insurance_claims.tools.cmmn_claims_flow import build_cmmn_insurance_claims_flow

GENERATED = Path(__file__).resolve().parent / "generated"
GENERATED.mkdir(exist_ok=True)

_TEST_CASES = [
    {
        "label": "Standard AUTO claim (clean) → APPROVED",
        "input": {
            "claimant_name": "Alice Johnson",
            "policy_number": "POL-2024-001",
            "claim_type": "AUTO",
            "incident_date": "2024-10-15",
            "incident_description": "Rear-end collision at a traffic light",
            "estimated_damage": 3800.0,
            "policy_effective_date": "2024-01-01",
            "policy_expiry_date": "2024-12-31",
            "documents_received": ["police_report", "photos_of_damage", "repair_estimate", "driver_license"],
            "incident_on_weekend": False,
            "new_policy_recent_claim": False,
            "claim_near_policy_limit": False,
            "multiple_claims_12_months": False,
            "inconsistent_damage_report": False,
            "no_police_report_auto": False,
            "single_witness": False,
            "adjuster_approved_amount": 3800.0,
            "reserve_approved_by_manager": True,
            "denial_reason": "",
            "claimant_counter_offered": False,
            "claimant_counter_amount_usd": 0.0,
            "elapsed_days": 5,
            "sla_days": 30,
        },
    },
    {
        "label": "PROPERTY claim with high fraud signals → INVESTIGATION",
        "input": {
            "claimant_name": "Bob Martinez",
            "policy_number": "POL-2024-002",
            "claim_type": "PROPERTY",
            "incident_date": "2024-11-02",
            "incident_description": "House fire — total loss claim",
            "estimated_damage": 85000.0,
            "policy_effective_date": "2024-09-01",
            "policy_expiry_date": "2025-08-31",
            "documents_received": ["photos_of_damage", "incident_report"],
            "incident_on_weekend": True,
            "new_policy_recent_claim": True,
            "claim_near_policy_limit": True,
            "multiple_claims_12_months": True,
            "inconsistent_damage_report": True,
            "no_police_report_auto": False,
            "single_witness": True,
            "adjuster_approved_amount": 85000.0,
            "reserve_approved_by_manager": True,
            "denial_reason": "",
            "claimant_counter_offered": False,
            "claimant_counter_amount_usd": 0.0,
            "elapsed_days": 18,
            "sla_days": 45,
        },
    },
    {
        "label": "MEDICAL claim with lapsed policy → DENIED (coverage not confirmed)",
        "input": {
            "claimant_name": "Carol Smith",
            "policy_number": "POL-2023-999",
            "claim_type": "MEDICAL",
            "incident_date": "2024-07-20",
            "incident_description": "Emergency hospitalisation",
            "estimated_damage": 12000.0,
            "policy_effective_date": "2023-01-01",
            "policy_expiry_date": "2024-06-30",  # expired before incident
            "documents_received": ["medical_records", "bills_and_receipts"],
            "incident_on_weekend": False,
            "new_policy_recent_claim": False,
            "claim_near_policy_limit": False,
            "multiple_claims_12_months": False,
            "inconsistent_damage_report": False,
            "no_police_report_auto": False,
            "single_witness": False,
            "adjuster_approved_amount": 0.0,
            "reserve_approved_by_manager": False,
            "denial_reason": "Policy lapsed prior to incident date.",
            "claimant_counter_offered": False,
            "claimant_counter_amount_usd": 0.0,
            "elapsed_days": 3,
            "sla_days": 20,
        },
    },
    {
        "label": "LIABILITY claim with claimant counter-offer → NEGOTIATING",
        "input": {
            "claimant_name": "David Chen",
            "policy_number": "POL-2024-045",
            "claim_type": "LIABILITY",
            "incident_date": "2024-09-10",
            "incident_description": "Slip-and-fall at commercial property",
            "estimated_damage": 42000.0,
            "policy_effective_date": "2024-01-01",
            "policy_expiry_date": "2024-12-31",
            "documents_received": ["incident_report", "witness_statements", "medical_records", "legal_notice"],
            "incident_on_weekend": True,
            "new_policy_recent_claim": False,
            "claim_near_policy_limit": False,
            "multiple_claims_12_months": False,
            "inconsistent_damage_report": False,
            "no_police_report_auto": False,
            "single_witness": True,
            "adjuster_approved_amount": 35000.0,
            "reserve_approved_by_manager": True,
            "denial_reason": "",
            "claimant_counter_offered": True,
            "claimant_counter_amount_usd": 48000.0,
            "elapsed_days": 28,
            "sla_days": 60,
        },
    },
]


async def main() -> None:
    print("Compiling CMMN Insurance Claims Flow…")
    flow_def = await build_cmmn_insurance_claims_flow().compile_deploy()
    spec_path = GENERATED / "cmmn_insurance_claims_flow.json"
    flow_def.dump_spec(str(spec_path))
    print(f"  ✓ Spec written to {spec_path}\n")

    for case in _TEST_CASES:
        print(f"{'─' * 70}")
        print(f"  Test: {case['label']}")
        print(f"{'─' * 70}")
        result = await flow_def.invoke(case["input"], debug=False)
        print(json.dumps(result, indent=2, default=str))
        print()

    print("All test cases complete.")


if __name__ == "__main__":
    asyncio.run(main())

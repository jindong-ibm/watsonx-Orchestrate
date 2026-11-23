"""
Programmatic testing script for the Self-Service Remediation flow.

Run this script to compile and test the flow locally before deploying.
"""
import asyncio
from pathlib import Path
from self_service_remediation.tools.remediation_flow import build_self_service_remediation_flow


async def main():
    """Compile and test the self-service remediation flow."""
    print("Building Self-Service Remediation Flow...")

    flow_def = await build_self_service_remediation_flow().compile_deploy()

    # Save compiled flow spec
    generated_folder = f"{Path(__file__).resolve().parent}/generated"
    Path(generated_folder).mkdir(exist_ok=True)
    flow_def.dump_spec(f"{generated_folder}/remediation_flow.json")
    print(f"Flow spec saved to {generated_folder}/remediation_flow.json")

    # Test invocation
    print("\nTesting flow invocation (dry-run mode)...")
    result = await flow_def.invoke(
        {
            "user_issue_description": "Pods are stuck in CrashLoopBackOff after the recent upgrade",
            "namespace": "cpd",
            "release_version": "5.4.x",
            "dry_run": True
        },
        debug=True
    )

    print("\n=== Flow Result ===")
    print(f"Diagnosis: {result.get('diagnosis_summary', 'N/A')}")
    print(f"Matched Issues: {len(result.get('matched_issues', []))}")
    print(f"Cluster Health: {result.get('cluster_health', 'N/A')}")
    print(f"Recommendations: {result.get('recommendations', [])}")


if __name__ == "__main__":
    asyncio.run(main())

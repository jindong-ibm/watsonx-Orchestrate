"""
Standalone script to run the full Self-Service Remediation pipeline.

Calls each step directly without the WXO flow engine, making it easy to
run locally for debugging or ad-hoc remediation outside of watsonx Orchestrate.

Usage:
    python run_remediation.py [--namespace cpd] [--release 5.4.x] [--dry-run] \
                              [--issue "Pods are stuck in CrashLoopBackOff"]

Arguments (all optional):
    --namespace   OpenShift namespace to inspect (default: cpd)
    --release     watsonx Orchestrate release version (default: 5.4.x)
    --dry-run     Show remediation commands without executing them (default: True)
    --no-dry-run  Actually execute remediation commands
    --issue       User-reported issue description
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from self_service_remediation.tools.fetch_known_issues import fetch_known_issues
from self_service_remediation.tools.collect_cluster_status import collect_cluster_status
from self_service_remediation.tools.collect_service_logs import collect_service_logs
from self_service_remediation.tools.analyze_and_match import analyze_and_match_issues
from self_service_remediation.tools.execute_remediation import execute_remediation
from self_service_remediation.tools.remediation_flow import generate_diagnosis_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_remediation")


def _unwrap(result: Any) -> dict:
    """
    Unwrap a WxO ToolResponse into a plain dict.

    When tool functions decorated with @tool are called directly (outside the
    WxO flow engine), they return a ToolResponse object rather than a plain dict.
    ToolResponse stores the payload under the 'content' key.
    This helper handles both cases so the runner works with and without the SDK.
    """
    # ToolResponse exposes .content; check without importing the SDK class
    if hasattr(result, "content"):
        return result.content  # type: ignore[return-value]
    return result  # already a plain dict


def _section(title: str) -> None:
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


def run(
    user_issue_description: str,
    namespace: str = "cpd",
    release_version: str = "5.4.x",
    dry_run: bool = True,
) -> dict:
    """
    Execute all remediation steps in sequence and return the combined result.

    Steps:
      1. Fetch known issues from IBM documentation
      2. Collect cluster status (nodes, pods, events)
      3. Collect service logs (errors & warnings)
      4. Analyze and match against known issues
      5. Generate diagnosis report
      6. Execute remediation for the top-matched issue

    Returns:
        Dict with keys: diagnosis_summary, matched_issues, cluster_health,
                        remediation_result, recommendations
    """
    # ── Step 1: Fetch known issues ──────────────────────────────────────────
    _section("Step 1 / 6 — Fetch Known Issues")
    known_issues = _unwrap(fetch_known_issues(release_version=release_version))
    print(f"  Release     : {known_issues['release']}")
    print(f"  Issues found: {known_issues['total_count']}")
    print(f"  Source URL  : {known_issues['source_url']}")

    # ── Step 2: Collect cluster status ──────────────────────────────────────
    _section("Step 2 / 6 — Collect Cluster Status")
    cluster_status = _unwrap(collect_cluster_status(namespace=namespace))
    print(f"  Cluster version : {cluster_status['cluster_version']}")
    print(f"  Nodes           : {len(cluster_status['nodes'])}")
    print(f"  Unhealthy pods  : {len(cluster_status['unhealthy_pods'])}")
    print(f"  Recent events   : {len(cluster_status['recent_events'])}")
    print(f"  Overall health  : {cluster_status['overall_health']}")

    # ── Step 3: Collect service logs ────────────────────────────────────────
    _section("Step 3 / 6 — Collect Service Logs")
    service_logs = _unwrap(collect_service_logs(namespace=namespace, since_minutes=60))
    print(f"  Services checked: {len(service_logs['services_checked'])}")
    print(f"  Errors found    : {service_logs['total_errors']}")
    print(f"  Warnings found  : {service_logs['total_warnings']}")

    # ── Step 4: Analyze and match ────────────────────────────────────────────
    _section("Step 4 / 6 — Analyze & Match Issues")
    analysis = _unwrap(analyze_and_match_issues(
        cluster_status=cluster_status,
        service_logs=service_logs,
        known_issues=known_issues,
    ))
    print(f"  Severity        : {analysis['severity']}")
    print(f"  Matched issues  : {len(analysis['matched_issues'])}")
    print(f"  Unmatched errors: {len(analysis['unmatched_errors'])}")
    if analysis["matched_issues"]:
        top = analysis["matched_issues"][0]
        print(f"  Top match       : {top['title']} (confidence: {top['confidence']:.0%})")

    # ── Step 5: Generate diagnosis report ────────────────────────────────────
    _section("Step 5 / 6 — Generate Diagnosis Report")
    diagnosis = _unwrap(generate_diagnosis_report(
        user_issue_description=user_issue_description,
        cluster_status=cluster_status,
        service_logs=service_logs,
        analysis_result=analysis,
    ))
    print(diagnosis["diagnosis_summary"])

    # ── Step 6: Execute remediation ──────────────────────────────────────────
    _section(f"Step 6 / 6 — Execute Remediation {'[DRY RUN]' if dry_run else '[LIVE]'}")
    top_match = diagnosis.get("top_match")
    remediation = _unwrap(execute_remediation(
        issue_title=top_match["title"] if top_match else "No match",
        solution_steps=top_match["solution_steps"] if top_match else "",
        component=top_match["component"] if top_match else "general",
        namespace=namespace,
        dry_run=dry_run,
    ))

    print(f"  Overall status: {remediation['overall_status']}")
    for step in remediation.get("steps_executed", []):
        print(f"  Step {step['step_number']}: [{step['status']}] {step['command']}")
        if step.get("output"):
            print(f"           {step['output']}")
    if remediation.get("post_check"):
        print(f"  Post-check    : {remediation['post_check']}")
    for rec in remediation.get("recommendations", []):
        print(f"  ▶ {rec}")

    # ── Summary ──────────────────────────────────────────────────────────────
    _section("Remediation Complete")
    result = {
        "diagnosis_summary": diagnosis["diagnosis_summary"],
        "matched_issues": diagnosis["matched_issues"],
        "cluster_health": diagnosis["cluster_health"],
        "remediation_result": remediation,
        "recommendations": remediation.get("recommendations", []),
    }
    print(f"  Cluster health : {result['cluster_health']}")
    print(f"  Matched issues : {len(result['matched_issues'])}")
    print(f"  Remediation    : {remediation['overall_status']}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Self-Service Remediation pipeline standalone."
    )
    parser.add_argument(
        "--issue",
        default="Pods are stuck in CrashLoopBackOff after the recent upgrade",
        help="User-reported issue description",
    )
    parser.add_argument(
        "--namespace",
        default="cpd",
        help="OpenShift namespace to inspect (default: cpd)",
    )
    parser.add_argument(
        "--release",
        default="5.4.x",
        help="watsonx Orchestrate release version (default: 5.4.x)",
    )
    dry_run_group = parser.add_mutually_exclusive_group()
    dry_run_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Show commands without executing them (default)",
    )
    dry_run_group.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Execute remediation commands for real",
    )
    parser.add_argument(
        "--output-json",
        metavar="FILE",
        help="Write the final result as JSON to this file",
    )

    args = parser.parse_args()

    print("=" * 62)
    print("  Self-Service Remediation — Standalone Runner")
    print("=" * 62)
    print(f"  Issue     : {args.issue}")
    print(f"  Namespace : {args.namespace}")
    print(f"  Release   : {args.release}")
    print(f"  Dry run   : {args.dry_run}")

    result = run(
        user_issue_description=args.issue,
        namespace=args.namespace,
        release_version=args.release,
        dry_run=args.dry_run,
    )

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"\nResult written to: {out_path}")


if __name__ == "__main__":
    main()

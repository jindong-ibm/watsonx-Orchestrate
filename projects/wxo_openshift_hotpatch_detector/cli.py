#!/usr/bin/env python3
"""
Command-line interface for OpenShift Hot Patch Detector.
"""

import argparse
import sys
import json
import yaml
from pathlib import Path

from detector import OpenShiftHotPatchDetector, ScanResult


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Detect hot patches in watsonx Orchestrate OpenShift deployments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan watsonx Orchestrate namespace
  python cli.py scan --namespace watsonx-orchestrate
  
  # Scan with baseline comparison
  python cli.py scan --namespace watsonx-orchestrate --baseline baseline.yaml
  
  # Generate HTML report
  python cli.py scan --namespace watsonx-orchestrate --output report.html --format html
  
  # Export current state as baseline
  python cli.py export-baseline --namespace watsonx-orchestrate --output baseline.yaml
  
  # Scan multiple namespaces
  python cli.py scan --namespaces watsonx-orchestrate,wxo-dev --output multi-ns-report.json
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan for hot patches")
    scan_parser.add_argument(
        "--namespace",
        default="watsonx-orchestrate",
        help="Namespace to scan (default: watsonx-orchestrate)",
    )
    scan_parser.add_argument(
        "--namespaces",
        help="Comma-separated list of namespaces to scan",
    )
    scan_parser.add_argument(
        "--baseline",
        help="Path to baseline configuration file",
    )
    scan_parser.add_argument(
        "--kubeconfig",
        help="Path to kubeconfig file",
    )
    scan_parser.add_argument(
        "--format",
        choices=["json", "yaml", "summary"],
        default="summary",
        help="Output format",
    )
    scan_parser.add_argument(
        "--output",
        help="Output file path (prints to stdout if not specified)",
    )
    scan_parser.add_argument(
        "--min-severity",
        choices=["critical", "high", "medium", "low", "info"],
        default="low",
        help="Minimum severity to report",
    )
    
    # Export baseline command
    export_parser = subparsers.add_parser("export-baseline", help="Export current state as baseline")
    export_parser.add_argument(
        "--namespace",
        default="watsonx-orchestrate",
        help="Namespace to export",
    )
    export_parser.add_argument(
        "--output",
        required=True,
        help="Output file path for baseline",
    )
    export_parser.add_argument(
        "--kubeconfig",
        help="Path to kubeconfig file",
    )
    
    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify deployment against baseline")
    verify_parser.add_argument(
        "--namespace",
        default="watsonx-orchestrate",
        help="Namespace to verify",
    )
    verify_parser.add_argument(
        "--baseline",
        required=True,
        help="Path to baseline configuration file",
    )
    verify_parser.add_argument(
        "--kubeconfig",
        help="Path to kubeconfig file",
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "scan":
        return handle_scan(args)
    elif args.command == "export-baseline":
        return handle_export_baseline(args)
    elif args.command == "verify":
        return handle_verify(args)
    
    return 0


def handle_scan(args):
    """Handle scan command."""
    # Determine namespaces to scan
    if args.namespaces:
        namespaces = [ns.strip() for ns in args.namespaces.split(",")]
    else:
        namespaces = [args.namespace]
    
    # Load baseline if provided
    baseline = None
    if args.baseline:
        try:
            detector = OpenShiftHotPatchDetector(namespace=namespaces[0], kubeconfig=args.kubeconfig)
            baseline = detector.load_baseline(args.baseline)
            print(f"Loaded baseline from {args.baseline}")
        except Exception as e:
            print(f"Error loading baseline: {e}", file=sys.stderr)
            return 1
    
    # Scan each namespace
    all_results = []
    for namespace in namespaces:
        print(f"\nScanning namespace: {namespace}...")
        
        try:
            detector = OpenShiftHotPatchDetector(namespace=namespace, kubeconfig=args.kubeconfig)
            result = detector.scan(baseline=baseline)
            all_results.append(result)
            
            print(f"  Found {len(result.findings)} potential hot patch(es)")
            print(f"  Critical: {result.severity_counts.get('critical', 0)}")
            print(f"  High: {result.severity_counts.get('high', 0)}")
            
        except Exception as e:
            print(f"  Error scanning namespace: {e}", file=sys.stderr)
            continue
    
    if not all_results:
        print("No results to report", file=sys.stderr)
        return 1
    
    # Filter by severity
    from detector import Severity
    severity_map = {
        "critical": Severity.CRITICAL,
        "high": Severity.HIGH,
        "medium": Severity.MEDIUM,
        "low": Severity.LOW,
        "info": Severity.INFO,
    }
    min_severity = severity_map[args.min_severity]
    
    # Combine results
    combined_result = all_results[0]
    if len(all_results) > 1:
        for result in all_results[1:]:
            combined_result.findings.extend(result.findings)
            combined_result.resources_scanned += result.resources_scanned
            combined_result.errors.extend(result.errors)
    
    # Filter findings
    combined_result.findings = [
        f for f in combined_result.findings
        if _severity_gte(f.severity, min_severity)
    ]
    
    # Generate output
    if args.format == "json":
        output = json.dumps(combined_result.to_dict(), indent=2)
    elif args.format == "yaml":
        output = yaml.dump(combined_result.to_dict(), default_flow_style=False)
    else:  # summary
        output = generate_summary(combined_result)
    
    # Write output
    if args.output:
        Path(args.output).write_text(output)
        print(f"\nReport saved to {args.output}")
    else:
        print("\n" + output)
    
    # Return exit code based on findings
    if combined_result.severity_counts.get("critical", 0) > 0:
        return 2  # Critical findings
    elif combined_result.severity_counts.get("high", 0) > 0:
        return 1  # High priority findings
    else:
        return 0  # No critical/high findings


def handle_export_baseline(args):
    """Handle export-baseline command."""
    print(f"Exporting baseline for namespace: {args.namespace}...")
    
    try:
        detector = OpenShiftHotPatchDetector(namespace=args.namespace, kubeconfig=args.kubeconfig)
        detector.export_baseline(args.output)
        print(f"Baseline exported to {args.output}")
        return 0
    except Exception as e:
        print(f"Error exporting baseline: {e}", file=sys.stderr)
        return 1


def handle_verify(args):
    """Handle verify command."""
    print(f"Verifying namespace {args.namespace} against baseline...")
    
    try:
        detector = OpenShiftHotPatchDetector(namespace=args.namespace, kubeconfig=args.kubeconfig)
        baseline = detector.load_baseline(args.baseline)
        result = detector.scan(baseline=baseline)
        
        if not result.findings:
            print("✅ No hot patches detected. Deployment matches baseline.")
            return 0
        else:
            print(f"⚠️  Found {len(result.findings)} deviation(s) from baseline:")
            for finding in result.findings:
                print(f"  - {finding.severity.value.upper()}: {finding.title}")
                print(f"    {finding.description}")
            return 1
            
    except Exception as e:
        print(f"Error verifying deployment: {e}", file=sys.stderr)
        return 1


def generate_summary(result: ScanResult) -> str:
    """Generate a text summary of scan results."""
    lines = []
    lines.append("=" * 70)
    lines.append("WATSONX ORCHESTRATE HOT PATCH DETECTION SUMMARY")
    lines.append("=" * 70)
    lines.append(f"Scan ID: {result.scan_id}")
    lines.append(f"Date: {result.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Namespace(s): {', '.join(result.namespaces) if result.namespaces else result.namespace}")
    lines.append("")
    lines.append(f"Resources Scanned: {result.resources_scanned}")
    lines.append(f"Resources with Changes: {result.resources_with_changes}")
    lines.append(f"Total Findings: {len(result.findings)}")
    lines.append("")
    lines.append("Severity Breakdown:")
    lines.append(f"  Critical: {result.severity_counts.get('critical', 0)}")
    lines.append(f"  High:     {result.severity_counts.get('high', 0)}")
    lines.append(f"  Medium:   {result.severity_counts.get('medium', 0)}")
    lines.append(f"  Low:      {result.severity_counts.get('low', 0)}")
    lines.append("")
    
    if result.findings:
        lines.append("Findings:")
        lines.append("-" * 70)
        for i, finding in enumerate(result.findings[:10], 1):  # Show first 10
            lines.append(f"\n{i}. [{finding.severity.value.upper()}] {finding.title}")
            lines.append(f"   Resource: {finding.resource_type}/{finding.resource_name}")
            lines.append(f"   {finding.description}")
            if finding.recommendation:
                lines.append(f"   Recommendation: {finding.recommendation}")
        
        if len(result.findings) > 10:
            lines.append(f"\n... and {len(result.findings) - 10} more findings")
    
    if result.errors:
        lines.append("\nErrors:")
        for error in result.errors:
            lines.append(f"  - {error}")
    
    lines.append("\n" + "=" * 70)
    
    return "\n".join(lines)


def _severity_gte(severity1, severity2) -> bool:
    """Check if severity1 >= severity2."""
    order = ["info", "low", "medium", "high", "critical"]
    return order.index(severity1.value) >= order.index(severity2.value)


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob

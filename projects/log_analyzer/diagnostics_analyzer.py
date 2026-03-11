#!/usr/bin/env python3
"""
Diagnostics Analyzer - Enhanced log analyzer for watsonx Orchestrate diagnostics.

Features:
1. Check pod health status from Healthcheck/summary.html
2. Analyze container logs with event correlation and root cause analysis
3. Provide unified diagnostics report

Usage:
    python diagnostics_analyzer.py <diagnostics_folder> <event_string> [options]
"""

import os
import re
import sys
import argparse
from datetime import datetime
from html.parser import HTMLParser
from typing import List, Tuple, Optional

# Import the entire log_analyzer module to reuse its functions
try:
    import log_analyzer as la
except ImportError:
    print("Error: Could not import log_analyzer.py")
    print("Make sure log_analyzer.py is in the same directory.")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Pod Health Check - HTML Parser
# ─────────────────────────────────────────────────────────────────────────────

class PodStatusParser(HTMLParser):
    """
    Parse HTML to extract pod names and their status.
    
    Handles various HTML structures:
    - Tables with pod name and status columns
    - Divs/spans with status classes
    - Any text containing "pod" and "status" patterns
    """
    
    def __init__(self):
        super().__init__()
        self.pods = []  # List of (pod_name, status) tuples
        self.current_data = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.row_data = []
        
    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
        elif tag == 'tr':
            self.in_row = True
            self.row_data = []
        elif tag in ('td', 'th'):
            self.in_cell = True
            
    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
        elif tag == 'tr':
            self.in_row = False
            # Process completed row
            if len(self.row_data) >= 2:
                self._extract_pod_from_row(self.row_data)
            self.row_data = []
        elif tag in ('td', 'th'):
            self.in_cell = False
            
    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
            
        # Collect cell data when in table
        if self.in_table and self.in_row and self.in_cell:
            self.row_data.append(data)
        
        # Also look for pod/status patterns in any text
        self._extract_pod_from_text(data)
    
    def _extract_pod_from_row(self, row_data: List[str]):
        """Extract pod name and status from table row data."""
        # Look for patterns like: ["pod-name", "Running"] or ["Name", "Status", "pod-name", "Running"]
        for i, cell in enumerate(row_data):
            # Skip header rows
            if cell.lower() in ('name', 'pod', 'pod name', 'status', 'state'):
                continue
                
            # Check if this looks like a pod name (contains hyphens, alphanumeric)
            if re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$', cell, re.IGNORECASE):
                # Next cell might be the status
                if i + 1 < len(row_data):
                    potential_status = row_data[i + 1]
                    if self._is_status_keyword(potential_status):
                        self.pods.append((cell, potential_status))
                        return
    
    def _extract_pod_from_text(self, text: str):
        """Extract pod name and status from free-form text."""
        # Pattern: "pod-name: Running" or "pod-name (Running)" or "pod-name - Running"
        patterns = [
            r'([a-z0-9\-]+)\s*[:\(\-]\s*([a-zA-Z]+)',
            r'pod[:\s]+([a-z0-9\-]+)\s+status[:\s]+([a-zA-Z]+)',
            r'([a-z0-9\-]+)\s+is\s+([a-zA-Z]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                pod_name, status = match.groups()
                if self._is_status_keyword(status):
                    # Avoid duplicates
                    if (pod_name, status) not in self.pods:
                        self.pods.append((pod_name, status))
    
    def _is_status_keyword(self, text: str) -> bool:
        """Check if text looks like a pod status."""
        status_keywords = [
            'running', 'pending', 'succeeded', 'failed', 'unknown',
            'crashloopbackoff', 'error', 'terminating', 'completed',
            'containercreating', 'imagepullbackoff', 'evicted'
        ]
        return text.lower() in status_keywords or 'crash' in text.lower()


def parse_pod_health(html_path: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Parse the summary.html file and extract pod statuses.
    
    Returns:
        (all_pods, non_running_pods) - both as list of (name, status) tuples
    """
    if not os.path.exists(html_path):
        return [], []
    
    try:
        with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
    except Exception as e:
        print(la.colorize(f"[WARN] Could not read {html_path}: {e}", "yellow"))
        return [], []
    
    parser = PodStatusParser()
    parser.feed(html_content)
    
    all_pods = parser.pods
    
    # Define healthy/normal pod states that should not be flagged as issues
    HEALTHY_STATES = {'running', 'completed', 'succeeded'}
    
    # Filter for pods not in healthy states
    non_running = [(name, status) for name, status in all_pods
                   if status.lower() not in HEALTHY_STATES]
    
    return all_pods, non_running


def print_pod_health_report(html_path: str, all_pods: List[Tuple[str, str]], 
                            non_running: List[Tuple[str, str]]):
    """Print the pod health check report."""
    la.print_header("POD HEALTH CHECK")
    
    if not os.path.exists(html_path):
        print(la.colorize(f"  [WARN] Health check file not found: {html_path}", "yellow"))
        print(la.colorize("  Skipping pod health check.\n", "dim"))
        la.print_separator()
        return
    
    print(f"  Source: {la.colorize(html_path, 'cyan')}\n")
    
    if not all_pods:
        print(la.colorize("  [INFO] No pod status information found in HTML.", "yellow"))
        print(la.colorize("  The HTML structure may not contain recognizable pod status data.\n", "dim"))
        la.print_separator()
        return
    
    total = len(all_pods)
    non_running_count = len(non_running)
    healthy_count = total - non_running_count
    
    print(f"  {la.colorize('✓', 'green')} Total pods found    : {la.colorize(str(total), 'cyan')}")
    print(f"  {la.colorize('✓', 'green')} Healthy pods        : {la.colorize(str(healthy_count), 'green')} (Running/Completed/Succeeded)")
    
    if non_running_count > 0:
        print(f"  {la.colorize('✗', 'red')} Unhealthy pods      : {la.colorize(str(non_running_count), 'red')}")
        print(f"\n  {la.colorize('Unhealthy Pods:', 'bold')}")
        la.print_separator()
        
        for pod_name, status in non_running:
            status_upper = status.upper()
            # Color-code by severity
            if 'crash' in status.lower() or 'fail' in status.lower():
                color = 'red'
            elif 'pending' in status.lower() or 'creating' in status.lower():
                color = 'yellow'
            else:
                color = 'cyan'
            
            status_badge = la.colorize(f"[{status_upper}]", color)
            print(f"  {status_badge:30s} {pod_name}")
    else:
        print(f"  {la.colorize('✓', 'green')} Unhealthy pods      : {la.colorize('0', 'green')}")
        print(f"\n  {la.colorize('All pods are healthy!', 'green')}")
    
    print()
    la.print_separator()


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostics Folder Validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_diagnostics_folder(folder: str) -> Tuple[str, str]:
    """
    Validate the diagnostics folder structure and return paths.
    
    Returns:
        (health_check_path, logs_path)
    """
    if not os.path.isdir(folder):
        print(la.colorize(f"[ERROR] Diagnostics folder not found: {folder}", "red"))
        sys.exit(1)
    
    # Expected paths
    health_check_path = os.path.join(folder, "Healthcheck", "summary.html")
    logs_base = os.path.join(folder, "watsonx Orchestrate", "hub", "containerLogs", "cpd-instance-1")
    
    # Check if logs folder exists
    if not os.path.isdir(logs_base):
        print(la.colorize(
            f"[WARN] Container logs folder not found: {logs_base}\n"
            "Expected structure: <folder>/watsonx Orchestrate/hub/containerLogs/cpd-instance-1/",
            "yellow"
        ))
        # Don't exit - we can still do health check
    
    return health_check_path, logs_base


# ─────────────────────────────────────────────────────────────────────────────
# CLI Argument Parser
# ─────────────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diagnostics_analyzer",
        description=(
            "Analyze watsonx Orchestrate diagnostics: check pod health and "
            "analyze container logs with event correlation and root cause analysis."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage - check health and analyze logs
  python diagnostics_analyzer.py /path/to/diagnostics "OutOfMemory"

  # With correlation key
  python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key pod

  # Search for strings with special characters (use single quotes inside double quotes)
  python diagnostics_analyzer.py /path/to/diagnostics '"level"="ERROR"' --key transaction-id

  # Or escape the quotes
  python diagnostics_analyzer.py /path/to/diagnostics "\\"level\\"=\\"ERROR\\"" --key transaction-id

  # Skip health check
  python diagnostics_analyzer.py /path/to/diagnostics "CrashLoop" --skip-health-check

  # Export full report
  python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key request-id --output report.txt

Note: When searching for strings containing quotes or special characters, wrap the entire
      search string in single quotes (') or escape the inner quotes with backslashes (\\").
        """,
    )
    
    parser.add_argument(
        "diagnostics_folder",
        help="Path to the diagnostics folder containing Healthcheck/ and watsonx Orchestrate/"
    )
    parser.add_argument(
        "event",
        help="Event string to search for in container logs (e.g., 'OutOfMemory', 'ERROR')"
    )
    parser.add_argument(
        "--key", "-k",
        metavar="CORRELATION_KEY",
        default="",
        help="Correlation key to extract context (e.g., transaction-id, pod, request-id)"
    )
    parser.add_argument(
        "--ext", "-e",
        nargs="+",
        metavar="EXT",
        default=[".log", ".txt"],
        help="Log file extensions to scan (default: .log .txt)"
    )
    parser.add_argument(
        "--case-sensitive", "-c",
        action="store_true",
        default=False,
        help="Enable case-sensitive matching"
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        default=None,
        help="Export the full report (health check + journey + RCA) to a file"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output"
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        default=False,
        help="Skip the pod health check step"
    )
    parser.add_argument(
        "--skip-rca",
        action="store_true",
        default=False,
        help="Skip the root cause analysis step"
    )
    
    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    
    # Disable color if requested
    if args.no_color:
        for key in la.COLORS:
            la.COLORS[key] = ""
    
    diagnostics_folder = os.path.abspath(args.diagnostics_folder)
    event_string = args.event
    correlation_key = args.key or ""
    
    # ── Step 1: Validate folder structure ────────────────────────────────────
    la.print_header("DIAGNOSTICS ANALYZER")
    print(f"  Diagnostics folder: {la.colorize(diagnostics_folder, 'cyan')}")
    print(f"  Event to search   : {la.colorize(repr(event_string), 'green')}")
    if correlation_key:
        print(f"  Correlation key   : {la.colorize(repr(correlation_key), 'magenta')}")
    print()
    
    health_check_path, logs_path = validate_diagnostics_folder(diagnostics_folder)
    
    # ── Step 2: Pod Health Check ──────────────────────────────────────────────
    all_pods = []
    non_running_pods = []
    
    if not args.skip_health_check:
        all_pods, non_running_pods = parse_pod_health(health_check_path)
        print_pod_health_report(health_check_path, all_pods, non_running_pods)
    else:
        print(la.colorize("\n  [INFO] Pod health check skipped (--skip-health-check).\n", "dim"))
    
    # ── Step 3: Log Analysis ──────────────────────────────────────────────────
    if not os.path.isdir(logs_path):
        print(la.colorize(
            f"\n[ERROR] Cannot proceed with log analysis - logs folder not found:\n{logs_path}",
            "red"
        ))
        sys.exit(1)
    
    la.print_header("LOG ANALYSIS")
    print(f"  Log folder: {la.colorize(logs_path, 'cyan')}")
    print(f"  Event     : {la.colorize(repr(event_string), 'green')}")
    if correlation_key:
        print(f"  Key       : {la.colorize(repr(correlation_key), 'magenta')}")
    print()
    
    # Discover log files
    print(la.colorize("  Discovering log files...", "dim"))
    log_files = la.discover_log_files(logs_path, args.ext)
    
    if not log_files:
        print(la.colorize(
            f"  No log files found in {logs_path} with extensions: {', '.join(args.ext)}",
            "yellow"
        ))
        sys.exit(0)
    
    print(f"  Found {la.colorize(str(len(log_files)), 'cyan')} log file(s)\n")
    
    # Search for event
    print(la.colorize("  Searching for event...", "dim"))
    event_hits = la.search_event(log_files, event_string, args.case_sensitive)
    
    if not event_hits:
        print(la.colorize(
            f"  No lines matching '{event_string}' found in any log file.",
            "yellow"
        ))
        sys.exit(0)
    
    print(f"  Found {la.colorize(str(len(event_hits)), 'green')} matching line(s)\n")
    
    # Extract correlation values and collect context
    correlation_values = []
    context_entries = []
    
    if correlation_key:
        print(la.colorize("  Extracting correlation values...", "dim"))
        correlation_values = la.extract_correlation_values(
            event_hits, correlation_key, args.case_sensitive
        )
        
        if correlation_values:
            print(f"  Extracted: {la.colorize(', '.join(correlation_values[:5]), 'yellow')}")
            if len(correlation_values) > 5:
                print(f"             {la.colorize(f'... and {len(correlation_values) - 5} more', 'dim')}")
            print()
            
            print(la.colorize("  Collecting context entries...", "dim"))
            context_entries = la.collect_context_entries(
                log_files, correlation_values, args.case_sensitive
            )
            print(f"  Found {la.colorize(str(len(context_entries)), 'yellow')} context line(s)\n")
    
    # Build journey
    print(la.colorize("  Building event journey...", "dim"))
    journey = la.merge_and_sort(event_hits, context_entries)
    print(f"  Journey contains {la.colorize(str(len(journey)), 'cyan')} unique entries\n")
    
    # Display journey
    la.print_header("EVENT JOURNEY (sorted by timestamp)")
    la.print_journey(
        journey,
        highlight_event=event_string,
        correlation_key=correlation_key,
        correlation_values=correlation_values,
    )
    
    # Root cause analysis
    findings = []
    if not args.skip_rca:
        la.print_header("ROOT CAUSE ANALYSIS")
        print(la.colorize("  Analyzing journey for failure signals...", "dim"))
        findings = la.analyse_root_cause(journey)
        print(f"  Found {la.colorize(str(len(findings)), 'yellow')} signal(s)\n")
        la.print_rca(findings, journey)
    else:
        print(la.colorize("\n  [INFO] Root cause analysis skipped (--skip-rca).\n", "dim"))
    
    # Summary
    la.print_summary(
        log_files=log_files,
        event_string=event_string,
        correlation_key=correlation_key,
        correlation_values=correlation_values,
        event_hits=event_hits,
        journey=journey,
        findings=findings,
    )
    
    # Export if requested
    if args.output:
        output_path = args.output
        
        # Write complete diagnostics report
        with open(output_path, 'w', encoding='utf-8') as f:
            # Header
            f.write("=" * 80 + "\n")
            f.write("WATSONX ORCHESTRATE DIAGNOSTICS ANALYSIS REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n")
            f.write(f"Diagnostics Folder: {diagnostics_folder}\n")
            f.write(f"Event Searched: {event_string}\n")
            if correlation_key:
                f.write(f"Correlation Key: {correlation_key}\n")
            f.write("=" * 80 + "\n\n")
            
            # Section 1: Pod Health Check
            f.write("=" * 80 + "\n")
            f.write("SECTION 1: POD HEALTH CHECK\n")
            f.write("=" * 80 + "\n")
            f.write(f"Source: {health_check_path}\n\n")
            
            if all_pods:
                f.write(f"Total pods found    : {len(all_pods)}\n")
                f.write(f"Healthy pods        : {len(all_pods) - len(non_running_pods)} (Running/Completed/Succeeded)\n")
                f.write(f"Unhealthy pods      : {len(non_running_pods)}\n\n")
                
                if non_running_pods:
                    f.write("Unhealthy Pods:\n")
                    f.write("-" * 80 + "\n")
                    for pod_name, status in non_running_pods:
                        f.write(f"  [{status.upper():20s}] {pod_name}\n")
                    f.write("\n")
                else:
                    f.write("All pods are healthy!\n\n")
            else:
                f.write("No pod status information found in HTML.\n\n")
            
            # Section 2: Log Analysis Summary
            f.write("\n" + "=" * 80 + "\n")
            f.write("SECTION 2: LOG ANALYSIS SUMMARY\n")
            f.write("=" * 80 + "\n")
            f.write(f"Log folder          : {logs_path}\n")
            f.write(f"Log files scanned   : {len(log_files)}\n")
            f.write(f"Event searched      : {repr(event_string)}\n")
            f.write(f"Event hits          : {len(event_hits)}\n")
            if correlation_key:
                vals_str = ", ".join(correlation_values[:5]) if correlation_values else "(none found)"
                if len(correlation_values) > 5:
                    vals_str += f" ... and {len(correlation_values) - 5} more"
                f.write(f"Correlation key     : {repr(correlation_key)}\n")
                f.write(f"Correlation values  : {vals_str}\n")
            f.write(f"Journey entries     : {len(journey)}\n")
            timestamped = sum(1 for e in journey if e.timestamp)
            f.write(f"Entries with ts     : {timestamped}\n")
            if findings:
                top = findings[0]
                f.write(f"Root cause          : {top.category} ({top.severity.upper()})\n")
            f.write("\n")
        
        # Append Section 3: Event Journey
        with open(output_path, 'a', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("SECTION 3: EVENT JOURNEY (sorted by timestamp)\n")
            f.write("=" * 80 + "\n\n")
        
        # Use the existing export_journey function with append mode
        la.export_journey(journey, output_path, append=True)
        
        # Append Section 4: Root Cause Analysis
        if not args.skip_rca and findings:
            la.export_rca(findings, journey, output_path)
        
        print(la.colorize(f"\n  Full diagnostics report exported to: {output_path}", "green"))


if __name__ == "__main__":
    main()

# Made with Bob

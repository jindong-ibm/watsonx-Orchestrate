#!/usr/bin/env python3
"""
Log Analyzer - Search and correlate log entries across multiple log files.

Features:
1. Search all log files in a folder for a specific event string
2. Find context log entries based on correlation keys (e.g., transaction-id)
3. Merge and sort all related log entries by timestamp for a complete event journey
4. Analyse the journey and suggest the most likely root cause of a failure
"""

import os
import re
import sys
import glob
import argparse
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Common timestamp patterns found in log files
# ─────────────────────────────────────────────────────────────────────────────
TIMESTAMP_PATTERNS = [
    # ISO 8601 with milliseconds: 2024-01-15T10:30:45.123Z  or  2024-01-15T10:30:45,123
    (
        r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.,]\d{3,6}(?:Z|[+-]\d{2}:?\d{2})?',
        ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S,%f",
         "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S,%f"],
    ),
    # ISO 8601 without milliseconds: 2024-01-15T10:30:45
    (
        r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}',
        ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"],
    ),
    # Apache/Nginx common log: 15/Jan/2024:10:30:45
    (
        r'\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}',
        ["%d/%b/%Y:%H:%M:%S"],
    ),
    # US date format: 01/15/2024 10:30:45
    (
        r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}',
        ["%m/%d/%Y %H:%M:%S"],
    ),
    # Epoch milliseconds (13-digit): 1705312245123
    (r'\b1[0-9]{12}\b', None),
]

# ANSI color codes for terminal output
COLORS = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "red":     "\033[91m",
    "green":   "\033[92m",
    "yellow":  "\033[93m",
    "blue":    "\033[94m",
    "magenta": "\033[95m",
    "cyan":    "\033[96m",
    "white":   "\033[97m",
}

# Rotating colors assigned to source files
FILE_COLOR_CYCLE = [
    "\033[94m",  # blue
    "\033[92m",  # green
    "\033[93m",  # yellow
    "\033[95m",  # magenta
    "\033[96m",  # cyan
    "\033[91m",  # red
]


def colorize(text: str, color: str) -> str:
    """Wrap *text* in ANSI color codes when stdout is a TTY."""
    if sys.stdout.isatty():
        return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"
    return text


def file_color(index: int) -> str:
    """Return an ANSI color string for the given file index."""
    if sys.stdout.isatty():
        return FILE_COLOR_CYCLE[index % len(FILE_COLOR_CYCLE)]
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LogEntry:
    """Represents a single log line with metadata."""
    raw_line: str
    source_file: str
    line_number: int
    timestamp: Optional[datetime] = None
    timestamp_str: str = ""
    matched_event: bool = False       # True if this line matched the event search
    matched_context: bool = False     # True if this line matched a correlation key
    correlation_values: list = field(default_factory=list)

    def display_source(self) -> str:
        return os.path.basename(self.source_file)

    def sort_key(self):
        """
        Primary sort: entries with a parsed timestamp come first.
        Secondary sort: timestamp value, then filename, then line number.
        """
        if self.timestamp:
            return (0, self.timestamp, self.source_file, self.line_number)
        return (1, datetime.min, self.source_file, self.line_number)


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp parsing
# ─────────────────────────────────────────────────────────────────────────────
def parse_timestamp(line: str) -> tuple:
    """
    Try to extract and parse a timestamp from a log line.
    Returns (datetime_object, raw_timestamp_string) or (None, "").
    """
    for pattern, formats in TIMESTAMP_PATTERNS:
        match = re.search(pattern, line)
        if not match:
            continue
        ts_str = match.group(0)

        # Epoch milliseconds
        if formats is None:
            try:
                return datetime.fromtimestamp(int(ts_str) / 1000), ts_str
            except (ValueError, OSError):
                continue

        for fmt in formats:
            try:
                # Strip trailing Z, normalize comma → dot, truncate to 6 decimal digits
                clean = ts_str.rstrip("Z").replace(",", ".")
                clean = re.sub(r'(\.\d{6})\d+', r'\1', clean)
                dt = datetime.strptime(clean, fmt)
                return dt, ts_str
            except ValueError:
                continue

    return None, ""


# ─────────────────────────────────────────────────────────────────────────────
# File discovery
# ─────────────────────────────────────────────────────────────────────────────
def discover_log_files(folder: str, extensions: list) -> list:
    """
    Recursively find all log files under *folder* matching *extensions*.
    Returns a sorted list of absolute paths.
    """
    found = []
    for ext in extensions:
        pattern = os.path.join(folder, "**", f"*{ext}")
        found.extend(glob.glob(pattern, recursive=True))
    return sorted(set(found))


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 – Search for the event string
# ─────────────────────────────────────────────────────────────────────────────
def search_event(
    log_files: list,
    event_string: str,
    case_sensitive: bool = False,
) -> list:
    """
    Scan every log file for lines containing *event_string*.
    Returns a list of matching LogEntry objects.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(re.escape(event_string), flags)
    except re.error as exc:
        print(colorize(f"[ERROR] Invalid search pattern: {exc}", "red"))
        return []

    hits = []
    for filepath in log_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    line = line.rstrip("\n")
                    if pattern.search(line):
                        ts, ts_str = parse_timestamp(line)
                        entry = LogEntry(
                            raw_line=line,
                            source_file=filepath,
                            line_number=lineno,
                            timestamp=ts,
                            timestamp_str=ts_str,
                            matched_event=True,
                        )
                        hits.append(entry)
        except OSError as exc:
            print(colorize(f"[WARN] Cannot read {filepath}: {exc}", "yellow"))

    return hits


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 – Extract correlation key values from event hits
# ─────────────────────────────────────────────────────────────────────────────
def extract_correlation_values(
    hits: list,
    correlation_key: str,
    case_sensitive: bool = False,
) -> list:
    """
    For each hit, search for *correlation_key* followed by a value
    (e.g. "transaction-id: abc123" or "transaction-id=abc123").
    Returns a deduplicated list of extracted values.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    # Match patterns like:  key: value  |  key=value  |  key="value"  |  key='value'
    key_escaped = re.escape(correlation_key)
    value_pattern = re.compile(
        key_escaped + r'[=:\s]+["\']?([A-Za-z0-9_\-\.]+)["\']?',
        flags,
    )

    values = set()
    for entry in hits:
        for match in value_pattern.finditer(entry.raw_line):
            val = match.group(1).strip()
            if val:
                values.add(val)
                entry.correlation_values.append(val)

    return list(values)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 – Collect all log lines that share a correlation value
# ─────────────────────────────────────────────────────────────────────────────
def collect_context_entries(
    log_files: list,
    correlation_values: list,
    case_sensitive: bool = False,
) -> list:
    """
    Re-scan all log files and return every line that contains at least one
    of the *correlation_values*.
    """
    if not correlation_values:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    # Build a single OR pattern for efficiency
    escaped = [re.escape(v) for v in correlation_values]
    combined = re.compile("|".join(escaped), flags)

    context_entries = []
    for filepath in log_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    line = line.rstrip("\n")
                    if combined.search(line):
                        ts, ts_str = parse_timestamp(line)
                        matched_vals = [v for v in correlation_values
                                        if re.search(re.escape(v), line, flags)]
                        entry = LogEntry(
                            raw_line=line,
                            source_file=filepath,
                            line_number=lineno,
                            timestamp=ts,
                            timestamp_str=ts_str,
                            matched_context=True,
                            correlation_values=matched_vals,
                        )
                        context_entries.append(entry)
        except OSError as exc:
            print(colorize(f"[WARN] Cannot read {filepath}: {exc}", "yellow"))

    return context_entries


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 – Merge, deduplicate, and sort
# ─────────────────────────────────────────────────────────────────────────────
def merge_and_sort(event_hits: list, context_entries: list) -> list:
    """
    Combine event hits and context entries, deduplicate by (file, line_number),
    and sort by timestamp.
    """
    seen = {}  # (filepath, lineno) -> LogEntry

    for entry in event_hits:
        key = (entry.source_file, entry.line_number)
        if key not in seen:
            seen[key] = entry
        else:
            seen[key].matched_event = True

    for entry in context_entries:
        key = (entry.source_file, entry.line_number)
        if key not in seen:
            seen[key] = entry
        else:
            seen[key].matched_context = True
            seen[key].correlation_values = list(
                set(seen[key].correlation_values + entry.correlation_values)
            )

    merged = list(seen.values())
    merged.sort(key=lambda e: e.sort_key())
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Phase 5 – Root Cause Analysis
# ─────────────────────────────────────────────────────────────────────────────

# ── Signal definitions ────────────────────────────────────────────────────────
# Each signal is a dict with:
#   pattern   – regex to match against a log line (case-insensitive)
#   category  – short label for the failure class
#   severity  – "critical" | "high" | "medium" | "low"
#   message   – human-readable description of what was detected
#   hint      – actionable suggestion for the operator
#
# Signals are evaluated in order; the FIRST match per entry wins for scoring,
# but ALL matching signals across the journey are collected.
# ─────────────────────────────────────────────────────────────────────────────
RCA_SIGNALS = [
    # ── External / downstream failures ───────────────────────────────────────
    {
        "pattern": r'\b(timeout|timed[\s_-]?out|connection[\s_-]?timeout|read[\s_-]?timeout)\b',
        "category": "Timeout",
        "severity": "high",
        "message": "A timeout was detected in the log journey.",
        "hint": "Check network latency, upstream service SLAs, and client/server timeout configurations.",
    },
    {
        "pattern": r'\b(connection[\s_-]?refused|connection[\s_-]?reset|ECONNREFUSED|ECONNRESET)\b',
        "category": "Connection Error",
        "severity": "critical",
        "message": "A connection was refused or reset by a downstream service.",
        "hint": "Verify the downstream service is running, reachable, and not overloaded.",
    },
    {
        "pattern": r'\b(circuit[\s_-]?breaker|circuit[\s_-]?open)\b',
        "category": "Circuit Breaker Open",
        "severity": "critical",
        "message": "A circuit breaker tripped, blocking calls to a downstream dependency.",
        "hint": "Investigate the downstream service health; the circuit breaker may need manual reset.",
    },
    # ── HTTP / API errors ─────────────────────────────────────────────────────
    {
        "pattern": r'\b(http[_\s]?status|status[_\s]?code)[=:\s]+5\d{2}\b',
        "category": "HTTP 5xx Error",
        "severity": "critical",
        "message": "An HTTP 5xx server-side error was returned.",
        "hint": "Examine the responding service logs for stack traces or resource exhaustion.",
    },
    {
        "pattern": r'\b(http[_\s]?status|status[_\s]?code)[=:\s]+4\d{2}\b',
        "category": "HTTP 4xx Error",
        "severity": "high",
        "message": "An HTTP 4xx client-side error was returned.",
        "hint": "Check request payload, authentication tokens, and API contract compliance.",
    },
    {
        "pattern": r'\bstatus[=:\s]+5\d{2}\b',
        "category": "HTTP 5xx Error",
        "severity": "critical",
        "message": "An HTTP 5xx server-side error was returned.",
        "hint": "Examine the responding service logs for stack traces or resource exhaustion.",
    },
    # ── Authentication / authorisation ────────────────────────────────────────
    {
        "pattern": r'\b(unauthorized|unauthenticated|401|403|forbidden|access[\s_-]?denied|permission[\s_-]?denied)\b',
        "category": "Auth Failure",
        "severity": "high",
        "message": "An authentication or authorisation failure was detected.",
        "hint": "Verify credentials, token expiry, and IAM/RBAC policies for the calling service.",
    },
    # ── Resource / capacity ───────────────────────────────────────────────────
    {
        "pattern": r'\b(out[\s_-]?of[\s_-]?memory|OOM|heap[\s_-]?space|memory[\s_-]?limit|killed)\b',
        "category": "Out of Memory",
        "severity": "critical",
        "message": "An out-of-memory condition was detected.",
        "hint": "Increase heap/memory limits, profile for memory leaks, or scale horizontally.",
    },
    {
        "pattern": r'\b(disk[\s_-]?full|no[\s_-]?space[\s_-]?left|ENOSPC)\b',
        "category": "Disk Full",
        "severity": "critical",
        "message": "The disk is full or storage quota was exceeded.",
        "hint": "Free disk space, rotate/archive old logs, or expand storage capacity.",
    },
    {
        "pattern": r'\b(rate[\s_-]?limit|too[\s_-]?many[\s_-]?requests|throttl|429)\b',
        "category": "Rate Limiting / Throttling",
        "severity": "high",
        "message": "A rate limit or throttling condition was hit.",
        "hint": "Implement exponential back-off, increase quota, or distribute load across time.",
    },
    {
        "pattern": r'\b(slow[\s_-]?response|high[\s_-]?latency|elapsed_ms|latency)\b.*\b([5-9]\d{3}|\d{5,})\b',
        "category": "High Latency",
        "severity": "medium",
        "message": "Unusually high response latency was observed (≥5 s).",
        "hint": "Profile the slow component; check for lock contention, N+1 queries, or GC pauses.",
    },
    # ── Data / business logic ─────────────────────────────────────────────────
    {
        "pattern": r'\b(insufficient[\s_-]?funds|decline[d]?|decline[\s_-]?code|bank[\s_-]?declin)\b',
        "category": "Payment Declined",
        "severity": "high",
        "message": "A payment was declined by the bank or payment processor.",
        "hint": "The decline is typically a business-level event; surface a clear error to the user and offer retry or alternative payment.",
    },
    {
        "pattern": r'\b(validation[\s_-]?fail|invalid[\s_-]?input|bad[\s_-]?request|malformed|schema[\s_-]?error)\b',
        "category": "Validation / Bad Input",
        "severity": "medium",
        "message": "Input validation failed or a malformed request was received.",
        "hint": "Review the request payload against the API schema; add stricter client-side validation.",
    },
    {
        "pattern": r'\b(not[\s_-]?found|404|record[\s_-]?not[\s_-]?found|no[\s_-]?such[\s_-]?(file|record|entity))\b',
        "category": "Resource Not Found",
        "severity": "medium",
        "message": "A required resource or record was not found.",
        "hint": "Verify the resource ID/path is correct and that the resource has not been deleted.",
    },
    # ── Infrastructure / runtime ──────────────────────────────────────────────
    {
        "pattern": r'\b(NullPointerException|NPE|null[\s_-]?reference|AttributeError|TypeError)\b',
        "category": "Null / Type Error",
        "severity": "high",
        "message": "A null pointer or type error was raised.",
        "hint": "Add null-checks or defensive coding around the failing code path; review recent changes.",
    },
    {
        "pattern": r'\b(deadlock|lock[\s_-]?timeout|lock[\s_-]?wait)\b',
        "category": "Database Deadlock",
        "severity": "critical",
        "message": "A database deadlock or lock-wait timeout was detected.",
        "hint": "Review transaction ordering, add retry logic, and consider shorter transactions.",
    },
    {
        "pattern": r'\b(database[\s_-]?error|db[\s_-]?error|sql[\s_-]?error|query[\s_-]?fail|ORA-\d+|SQLSTATE)\b',
        "category": "Database Error",
        "severity": "critical",
        "message": "A database error was encountered.",
        "hint": "Check DB connectivity, query syntax, index health, and connection pool settings.",
    },
    {
        "pattern": r'\b(exception|stack[\s_-]?trace|traceback|fatal|panic|crash)\b',
        "category": "Unhandled Exception",
        "severity": "high",
        "message": "An unhandled exception, panic, or crash was detected.",
        "hint": "Capture the full stack trace from the log; fix the underlying code defect.",
    },
    # ── Retry / retry exhaustion ──────────────────────────────────────────────
    {
        "pattern": r'\b(retry[\s_-]?exhausted|max[\s_-]?retries|no[\s_-]?more[\s_-]?retries|giving[\s_-]?up)\b',
        "category": "Retry Exhausted",
        "severity": "high",
        "message": "All retry attempts were exhausted before the operation succeeded.",
        "hint": "Increase retry budget, add jitter, or fix the underlying transient failure.",
    },
    # ── Generic error / failure catch-all ─────────────────────────────────────
    {
        "pattern": r'\b(ERROR|FATAL|CRITICAL|SEVERE)\b',
        "category": "Generic Error",
        "severity": "medium",
        "message": "A generic ERROR/FATAL log level entry was found.",
        "hint": "Review the full error message and surrounding context for more specific clues.",
    },
    {
        "pattern": r'\b(WARN|WARNING)\b',
        "category": "Warning",
        "severity": "low",
        "message": "Warning-level entries were present in the journey.",
        "hint": "Warnings may be precursors to the failure; investigate whether they contributed.",
    },
]

# Severity ordering for sorting / display
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class RcaFinding:
    """A single root-cause signal matched in the journey."""
    category: str
    severity: str
    message: str
    hint: str
    evidence: list = field(default_factory=list)   # list of (source_file, line_number, raw_line)

    def severity_rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 99)


def analyse_root_cause(journey: list) -> list:
    """
    Scan the sorted journey for known failure signals.

    Returns a list of RcaFinding objects, deduplicated by category and sorted
    by severity (critical → high → medium → low).  Each finding includes
    evidence lines from the journey that triggered it.
    """
    findings: dict = {}   # category -> RcaFinding

    for entry in journey:
        line = entry.raw_line
        for signal in RCA_SIGNALS:
            if re.search(signal["pattern"], line, re.IGNORECASE):
                cat = signal["category"]
                if cat not in findings:
                    findings[cat] = RcaFinding(
                        category=cat,
                        severity=signal["severity"],
                        message=signal["message"],
                        hint=signal["hint"],
                    )
                findings[cat].evidence.append(
                    (entry.display_source(), entry.line_number, entry.raw_line)
                )
                break   # one signal per line is enough

    result = sorted(findings.values(), key=lambda f: f.severity_rank())
    return result


def _duration_between_first_and_last(journey: list) -> Optional[timedelta]:
    """Return the elapsed time between the first and last timestamped entry."""
    timestamped = [e for e in journey if e.timestamp]
    if len(timestamped) < 2:
        return None
    return timestamped[-1].timestamp - timestamped[0].timestamp


def print_rca(findings: list, journey: list) -> None:
    """Pretty-print the root cause analysis report."""
    print_header("ROOT CAUSE ANALYSIS")

    if not findings:
        print(colorize(
            "  No known failure signals detected in the journey.\n"
            "  The event may be informational or the failure pattern is not yet catalogued.",
            "green"
        ))
        print_separator()
        return

    # ── Overall verdict ───────────────────────────────────────────────────────
    top = findings[0]
    severity_colors = {
        "critical": "red",
        "high":     "yellow",
        "medium":   "cyan",
        "low":      "dim",
    }
    verdict_color = severity_colors.get(top.severity, "white")

    print(f"\n  {colorize('Most Likely Root Cause:', 'bold')}")
    print(f"  {'─' * 60}")
    print(f"  Category  : {colorize(top.category, verdict_color)}")
    print(f"  Severity  : {colorize(top.severity.upper(), verdict_color)}")
    print(f"  Summary   : {top.message}")
    print(f"  Suggestion: {colorize(top.hint, 'cyan')}")

    # ── Timeline insight ──────────────────────────────────────────────────────
    elapsed = _duration_between_first_and_last(journey)
    if elapsed is not None:
        total_secs = elapsed.total_seconds()
        if total_secs < 60:
            elapsed_str = f"{total_secs:.1f} seconds"
        elif total_secs < 3600:
            elapsed_str = f"{total_secs / 60:.1f} minutes"
        else:
            elapsed_str = f"{total_secs / 3600:.1f} hours"
        print(f"\n  {colorize('Timeline:', 'bold')} journey spans {colorize(elapsed_str, 'cyan')}")

    # ── All findings ──────────────────────────────────────────────────────────
    if len(findings) > 1:
        print(f"\n  {colorize('All Detected Signals:', 'bold')}")
        print(f"  {'─' * 60}")
        for i, finding in enumerate(findings, start=1):
            fc = severity_colors.get(finding.severity, "white")
            badge = colorize(f"[{finding.severity.upper()}]", fc)
            print(f"  {i:>2}. {badge} {colorize(finding.category, 'bold')}  –  {finding.message}")

    # ── Evidence ──────────────────────────────────────────────────────────────
    print(f"\n  {colorize('Evidence Lines:', 'bold')}")
    print(f"  {'─' * 60}")
    shown = set()
    for finding in findings:
        for src, lineno, raw in finding.evidence:
            key = (src, lineno)
            if key in shown:
                continue
            shown.add(key)
            fc = severity_colors.get(finding.severity, "white")
            badge = colorize(f"[{finding.severity.upper()}]", fc)
            print(f"  {badge} {colorize(src, 'blue')}:L{lineno}  {raw[:120]}")

    print()
    print_separator()


def export_rca(findings: list, journey: list, output_path: str) -> None:
    """Append the RCA report to an existing export file (or write standalone)."""
    mode = "a" if os.path.exists(output_path) else "w"
    with open(output_path, mode, encoding="utf-8") as fh:
        fh.write("\n\n" + "=" * 80 + "\n")
        fh.write("SECTION 4: ROOT CAUSE ANALYSIS\n")
        fh.write("=" * 80 + "\n\n")

        if not findings:
            fh.write("  No known failure signals detected.\n")
            return

        top = findings[0]
        fh.write(f"  Most Likely Root Cause\n")
        fh.write(f"  {'─' * 60}\n")
        fh.write(f"  Category  : {top.category}\n")
        fh.write(f"  Severity  : {top.severity.upper()}\n")
        fh.write(f"  Summary   : {top.message}\n")
        fh.write(f"  Suggestion: {top.hint}\n\n")

        elapsed = _duration_between_first_and_last(journey)
        if elapsed is not None:
            fh.write(f"  Timeline  : journey spans {elapsed.total_seconds():.1f} seconds\n\n")

        fh.write(f"  All Detected Signals\n")
        fh.write(f"  {'─' * 60}\n")
        for i, finding in enumerate(findings, start=1):
            fh.write(f"  {i:>2}. [{finding.severity.upper()}] {finding.category}  –  {finding.message}\n")
            fh.write(f"      Suggestion: {finding.hint}\n")

        fh.write(f"\n  Evidence Lines\n")
        fh.write(f"  {'─' * 60}\n")
        shown = set()
        for finding in findings:
            for src, lineno, raw in finding.evidence:
                key = (src, lineno)
                if key in shown:
                    continue
                shown.add(key)
                fh.write(f"  [{finding.severity.upper()}] {src}:L{lineno}  {raw}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────
def build_file_color_map(entries: list) -> dict:
    """Assign a color to each unique source file."""
    files = sorted({e.source_file for e in entries})
    return {f: file_color(i) for i, f in enumerate(files)}


def print_separator(char: str = "─", width: int = 80) -> None:
    print(colorize(char * width, "dim"))


def print_header(title: str, width: int = 80) -> None:
    print()
    print_separator("═", width)
    print(colorize(f"  {title}", "bold"))
    print_separator("═", width)


def print_journey(
    entries: list,
    highlight_event: str,
    correlation_key: str,
    correlation_values: list,
    no_color: bool = False,
) -> None:
    """Pretty-print the sorted event journey."""
    if not entries:
        print(colorize("  No entries to display.", "yellow"))
        return

    color_map = build_file_color_map(entries)
    flags = re.IGNORECASE

    # Build highlight patterns
    event_pat = re.compile(re.escape(highlight_event), flags)
    corr_pats = [re.compile(re.escape(v), flags) for v in correlation_values]
    key_pat = re.compile(re.escape(correlation_key), flags) if correlation_key else None

    prev_file = None
    for entry in entries:
        src = entry.display_source()
        fc = color_map.get(entry.source_file, "")
        reset = COLORS["reset"] if sys.stdout.isatty() else ""

        # File change banner
        if entry.source_file != prev_file:
            print()
            print(f"{fc}{colorize('▶ FILE: ', 'bold')}{src}{reset}")
            print_separator()
            prev_file = entry.source_file

        # Timestamp column
        ts_col = entry.timestamp_str if entry.timestamp_str else "  (no timestamp)  "
        ts_display = colorize(f"[{ts_col}]", "cyan")

        # Line number
        ln_display = colorize(f"L{entry.line_number:>5}", "dim")

        # Tag badges
        badges = ""
        if entry.matched_event:
            badges += colorize(" [EVENT]", "green")
        if entry.matched_context:
            badges += colorize(" [CTX]", "yellow")

        # Highlight keywords in the raw line
        display_line = entry.raw_line
        if sys.stdout.isatty():
            # Highlight event string
            display_line = event_pat.sub(
                lambda m: colorize(m.group(0), "green"), display_line
            )
            # Highlight correlation key
            if key_pat:
                display_line = key_pat.sub(
                    lambda m: colorize(m.group(0), "magenta"), display_line
                )
            # Highlight correlation values
            for cp in corr_pats:
                display_line = cp.sub(
                    lambda m: colorize(m.group(0), "yellow"), display_line
                )

        print(f"  {ts_display} {ln_display}{badges}  {display_line}")

    print()


def print_summary(
    log_files: list,
    event_string: str,
    correlation_key: str,
    correlation_values: list,
    event_hits: list,
    journey: list,
    findings: list,
) -> None:
    """Print a summary block."""
    print_header("SUMMARY")
    print(f"  Log folder scanned  : {colorize(str(len(log_files)), 'cyan')} file(s)")
    print(f"  Event searched      : {colorize(repr(event_string), 'green')}")
    print(f"  Event hits          : {colorize(str(len(event_hits)), 'green')}")
    if correlation_key:
        vals_str = ", ".join(correlation_values) if correlation_values else "(none found)"
        print(f"  Correlation key     : {colorize(repr(correlation_key), 'magenta')}")
        print(f"  Correlation values  : {colorize(vals_str, 'yellow')}")
    print(f"  Journey entries     : {colorize(str(len(journey)), 'cyan')}")
    timestamped = sum(1 for e in journey if e.timestamp)
    print(f"  Entries with ts     : {colorize(str(timestamped), 'cyan')}")
    if findings:
        top = findings[0]
        sev_colors = {"critical": "red", "high": "yellow", "medium": "cyan", "low": "dim"}
        fc = sev_colors.get(top.severity, "white")
        print(f"  Root cause          : {colorize(top.category, fc)} "
              f"({colorize(top.severity.upper(), fc)})  –  {top.message}")
    print_separator()


def export_journey(entries: list, output_path: str, append: bool = False) -> None:
    """Write the journey to a plain-text file (creates or overwrites, or appends if append=True)."""
    mode = "a" if append else "w"
    with open(output_path, mode, encoding="utf-8") as fh:
        fh.write(f"Log Event Journey  –  generated {datetime.now().isoformat()}\n")
        fh.write("=" * 80 + "\n\n")
        prev_file = None
        for entry in entries:
            if entry.source_file != prev_file:
                fh.write(f"\n▶ FILE: {entry.display_source()}\n")
                fh.write("─" * 80 + "\n")
                prev_file = entry.source_file
            ts = entry.timestamp_str or "(no timestamp)"
            badges = ""
            if entry.matched_event:
                badges += " [EVENT]"
            if entry.matched_context:
                badges += " [CTX]"
            fh.write(f"  [{ts}] L{entry.line_number:>5}{badges}  {entry.raw_line}\n")
    print(colorize(f"\n  Journey exported to: {output_path}", "green"))


# ─────────────────────────────────────────────────────────────────────────────
# Interactive mode
# ─────────────────────────────────────────────────────────────────────────────
def prompt(msg: str, default: str = "") -> str:
    """Prompt the user for input, showing an optional default."""
    if default:
        full_msg = f"{msg} [{default}]: "
    else:
        full_msg = f"{msg}: "
    try:
        value = input(colorize(full_msg, "bold")).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return value if value else default


def interactive_mode() -> argparse.Namespace:
    """Gather parameters interactively when no CLI args are provided."""
    print_header("LOG ANALYZER  –  Interactive Mode")
    print("  Tip: press Ctrl-C at any prompt to exit.\n")

    folder = prompt("Log folder path")
    while not os.path.isdir(folder):
        print(colorize(f"  [ERROR] '{folder}' is not a valid directory.", "red"))
        folder = prompt("Log folder path")

    event_string = prompt("Event string to search for")
    while not event_string:
        print(colorize("  [ERROR] Event string cannot be empty.", "red"))
        event_string = prompt("Event string to search for")

    correlation_key = prompt(
        "Correlation key (e.g. transaction-id, request-id) — leave blank to skip", ""
    )

    extensions_raw = prompt("Log file extensions (comma-separated)", ".log,.txt")
    extensions = [e.strip() for e in extensions_raw.split(",") if e.strip()]

    case_raw = prompt("Case-sensitive search? (y/N)", "n")
    case_sensitive = case_raw.lower() in ("y", "yes")

    output_raw = prompt("Export journey to file? (leave blank to skip)", "")

    skip_rca_raw = prompt("Skip root cause analysis? (y/N)", "n")
    skip_rca = skip_rca_raw.lower() in ("y", "yes")

    ns = argparse.Namespace(
        folder=folder,
        event=event_string,
        key=correlation_key,
        extensions=extensions,
        case_sensitive=case_sensitive,
        output=output_raw if output_raw else None,
        no_color=False,
        skip_rca=skip_rca,
    )
    return ns


# ─────────────────────────────────────────────────────────────────────────────
# CLI argument parser
# ─────────────────────────────────────────────────────────────────────────────
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log_analyzer",
        description=(
            "Search log files for an event, correlate entries by a key "
            "(e.g. transaction-id), display a time-sorted event journey, "
            "and suggest the root cause of any detected failure."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (no arguments)
  python log_analyzer.py

  # CLI mode
  python log_analyzer.py /var/logs "PaymentFailed" --key transaction-id
  python log_analyzer.py ./logs "ERROR" --key request-id --ext .log .txt --output journey.txt

  # Skip root cause analysis
  python log_analyzer.py ./logs "PaymentFailed" --key transaction-id --skip-rca
        """,
    )
    parser.add_argument("folder", nargs="?", help="Path to the log folder")
    parser.add_argument("event", nargs="?", help="Event string to search for")
    parser.add_argument(
        "--key", "-k",
        metavar="CORRELATION_KEY",
        default="",
        help="Correlation key to extract context (e.g. transaction-id)",
    )
    parser.add_argument(
        "--ext", "-e",
        nargs="+",
        metavar="EXT",
        default=[".log", ".txt"],
        help="Log file extensions to scan (default: .log .txt)",
    )
    parser.add_argument(
        "--case-sensitive", "-c",
        action="store_true",
        default=False,
        help="Enable case-sensitive matching",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        default=None,
        help="Export the journey and RCA report to a plain-text file",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color output",
    )
    parser.add_argument(
        "--skip-rca",
        action="store_true",
        default=False,
        help="Skip the root cause analysis step",
    )
    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # If required positional args are missing, fall back to interactive mode
    if not args.folder or not args.event:
        args = interactive_mode()

    # Disable color if requested
    if args.no_color:
        for key in COLORS:
            COLORS[key] = ""
        for i in range(len(FILE_COLOR_CYCLE)):
            FILE_COLOR_CYCLE[i] = ""

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print(colorize(f"[ERROR] '{folder}' is not a valid directory.", "red"))
        sys.exit(1)

    event_string = args.event
    correlation_key = args.key or ""
    extensions = args.extensions if hasattr(args, "extensions") else args.ext

    # ── Step 1: Discover log files ──────────────────────────────────────────
    print_header("STEP 1 – Discovering log files")
    log_files = discover_log_files(folder, extensions)
    if not log_files:
        print(colorize(
            f"  No log files found in '{folder}' with extensions: "
            f"{', '.join(extensions)}", "yellow"
        ))
        sys.exit(0)

    for f in log_files:
        print(f"  {colorize('✔', 'green')}  {f}")
    print(f"\n  Total: {colorize(str(len(log_files)), 'cyan')} file(s)")

    # ── Step 2: Search for the event string ─────────────────────────────────
    print_header("STEP 2 – Searching for event")
    print(f"  Pattern : {colorize(repr(event_string), 'green')}")
    print(f"  Case    : {'sensitive' if args.case_sensitive else 'insensitive'}\n")

    event_hits = search_event(log_files, event_string, args.case_sensitive)

    if not event_hits:
        print(colorize(
            f"  No lines matching '{event_string}' found in any log file.", "yellow"
        ))
        sys.exit(0)

    print(f"  Found {colorize(str(len(event_hits)), 'green')} matching line(s):\n")
    for entry in event_hits:
        ts_col = f"[{entry.timestamp_str}]" if entry.timestamp_str else "[no timestamp]"
        print(
            f"    {colorize(ts_col, 'cyan')}  "
            f"{colorize(entry.display_source(), 'blue')}:{entry.line_number}  "
            f"{entry.raw_line[:120]}"
        )

    # ── Step 3: Extract correlation values ──────────────────────────────────
    correlation_values = []
    context_entries = []

    if correlation_key:
        print_header("STEP 3 – Extracting correlation values")
        print(f"  Key: {colorize(repr(correlation_key), 'magenta')}\n")

        correlation_values = extract_correlation_values(
            event_hits, correlation_key, args.case_sensitive
        )

        if not correlation_values:
            print(colorize(
                f"  No values found for key '{correlation_key}' in the event hits.\n"
                "  The journey will contain only the direct event matches.",
                "yellow"
            ))
        else:
            print(f"  Extracted values: {colorize(', '.join(correlation_values), 'yellow')}\n")

            # ── Step 4: Collect context entries ─────────────────────────────
            print_header("STEP 4 – Collecting context entries")
            context_entries = collect_context_entries(
                log_files, correlation_values, args.case_sensitive
            )
            print(
                f"  Found {colorize(str(len(context_entries)), 'yellow')} "
                "context line(s) sharing the correlation value(s)."
            )
    else:
        print(colorize(
            "\n  [INFO] No correlation key provided – skipping context collection.",
            "dim"
        ))

    # ── Step 5: Merge and sort ───────────────────────────────────────────────
    print_header("STEP 5 – Building event journey")
    journey = merge_and_sort(event_hits, context_entries)
    print(f"  Journey contains {colorize(str(len(journey)), 'cyan')} unique log entries.")

    # ── Step 6: Display the journey ─────────────────────────────────────────
    print_header("EVENT JOURNEY  (sorted by timestamp)")
    print_journey(
        journey,
        highlight_event=event_string,
        correlation_key=correlation_key,
        correlation_values=correlation_values,
    )

    # ── Step 7: Root cause analysis ──────────────────────────────────────────
    findings = []
    skip_rca = getattr(args, "skip_rca", False)
    if not skip_rca:
        print_header("STEP 6 – Root Cause Analysis")
        findings = analyse_root_cause(journey)
        print(
            f"  Analysed {colorize(str(len(journey)), 'cyan')} entries  →  "
            f"found {colorize(str(len(findings)), 'yellow')} signal(s)."
        )
        print_rca(findings, journey)
    else:
        print(colorize("\n  [INFO] Root cause analysis skipped (--skip-rca).", "dim"))

    # ── Summary ─────────────────────────────────────────────────────────────
    print_summary(
        log_files=log_files,
        event_string=event_string,
        correlation_key=correlation_key,
        correlation_values=correlation_values,
        event_hits=event_hits,
        journey=journey,
        findings=findings,
    )

    # ── Optional export ──────────────────────────────────────────────────────
    if args.output:
        export_journey(journey, args.output)
        if not skip_rca and findings:
            export_rca(findings, journey, args.output)


if __name__ == "__main__":
    main()

# Made with Bob

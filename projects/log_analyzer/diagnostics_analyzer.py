#!/usr/bin/env python3
"""
Diagnostics Analyzer - Enhanced log analyzer for watsonx Orchestrate diagnostics.

Features:
1. Check pod health status from Healthcheck/summary.html
2. Scan logs for sensitive information (PII, credentials, tokens)
3. Analyze container logs with event correlation and root cause analysis
4. Provide unified diagnostics report

Usage:
    python diagnostics_analyzer.py <diagnostics_folder> <event_string> [options]
"""

import os
import re
import sys
import argparse
from datetime import datetime
from html.parser import HTMLParser
from typing import List, Tuple, Optional, Dict, Any

# Import the entire log_analyzer module to reuse its functions
try:
    import log_analyzer as la
except ImportError:
    print("Error: Could not import log_analyzer.py")
    print("Make sure log_analyzer.py is in the same directory.")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Sensitive Information Detection Patterns
# ─────────────────────────────────────────────────────────────────────────────

# Patterns for detecting sensitive information in logs
# Note: Patterns are designed to minimize false positives by using context-aware matching
SENSITIVE_PATTERNS = {
    'email': {
        'pattern': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'severity': 'medium',
        'description': 'Email address detected',
        'category': 'PII'
    },
    'ssn': {
        # Only match SSN with explicit context keywords to avoid false positives
        'pattern': r'(?i)(?:ssn|social.?security)[\s:=]+["\']?\d{3}-\d{2}-\d{4}["\']?',
        'severity': 'critical',
        'description': 'Social Security Number (SSN) detected',
        'category': 'PII'
    },
    'credit_card': {
        # Match credit card numbers with context keywords or specific formatting
        # Excludes common ID patterns like tenant_id, user_id, etc.
        'pattern': r'(?i)(?:card|cc|credit.?card|pan)[\s:=]+["\']?(?:\d{4}[-\s]?){3}\d{4}["\']?|(?<!")(?<!\d)\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b(?!\d)(?!")',
        'severity': 'critical',
        'description': 'Credit card number detected',
        'category': 'Financial'
    },
    'api_key': {
        # Match API keys with explicit context, minimum 32 chars to avoid short IDs
        'pattern': r'(?i)(api[_-]?key|apikey|api[_-]?secret)[\s:=]+["\']?([a-zA-Z0-9_\-]{32,})["\']?',
        'severity': 'critical',
        'description': 'API key detected',
        'category': 'Credentials'
    },
    'bearer_token': {
        # Match Bearer tokens in Authorization headers, minimum 32 chars
        'pattern': r'(?i)bearer[\s]+([a-zA-Z0-9_\-\.]{32,})',
        'severity': 'critical',
        'description': 'Bearer token detected',
        'category': 'Credentials'
    },
    'jwt_token': {
        # JWT tokens have specific structure: header.payload.signature
        'pattern': r'\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b',
        'severity': 'high',
        'description': 'JWT token detected',
        'category': 'Credentials'
    },
    'aws_key': {
        # AWS access keys have specific prefixes and exact length
        'pattern': r'\b(AKIA|A3T|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}\b',
        'severity': 'critical',
        'description': 'AWS access key detected',
        'category': 'Credentials'
    },
    'password': {
        # Match passwords with explicit context keywords, exclude common field names
        'pattern': r'(?i)(?:password|passwd|pwd)[\s:=]+["\']([^\s"\']{8,})["\']',
        'severity': 'critical',
        'description': 'Password detected',
        'category': 'Credentials'
    },
    'private_key': {
        # Match PEM-formatted private keys
        'pattern': r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
        'severity': 'critical',
        'description': 'Private key detected',
        'category': 'Credentials'
    },
    'ip_address': {
        # Match valid IPv4 addresses, but exclude common non-routable ranges in context
        # Note: This will still match all IPs - consider if you want to exclude 127.0.0.1, 0.0.0.0, etc.
        'pattern': r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
        'severity': 'low',
        'description': 'IP address detected',
        'category': 'Network'
    },
    'phone_number': {
        # Match US phone numbers with explicit context to reduce false positives
        'pattern': r'(?i)(?:phone|tel|mobile|cell)[\s:=]+["\']?(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}["\']?',
        'severity': 'medium',
        'description': 'Phone number detected',
        'category': 'PII'
    },
    'oauth_token': {
        # Match OAuth/access tokens with context, minimum 32 chars
        'pattern': r'(?i)(oauth|access[_-]?token)[\s:=]+["\']?([a-zA-Z0-9_\-\.]{32,})["\']?',
        'severity': 'critical',
        'description': 'OAuth token detected',
        'category': 'Credentials'
    },
    'connection_string': {
        # Match database connection strings with embedded credentials
        'pattern': r'(?i)(mongodb|mysql|postgresql|mssql|oracle):\/\/[^\s:]+:[^\s@]+@[^\s]+',
        'severity': 'critical',
        'description': 'Database connection string with credentials detected',
        'category': 'Credentials'
    },
    'github_token': {
        # GitHub tokens have specific prefixes and exact lengths
        'pattern': r'\bgh[pousr]_[a-zA-Z0-9]{36,}\b',
        'severity': 'critical',
        'description': 'GitHub token detected',
        'category': 'Credentials'
    },
    'slack_token': {
        # Slack tokens have specific format with exact segment lengths
        'pattern': r'\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}\b',
        'severity': 'critical',
        'description': 'Slack token detected',
        'category': 'Credentials'
    },
}


def scan_sensitive_information(
    log_files: List[str],
    patterns: Dict[str, Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Scan log files for sensitive information (PII, credentials, tokens, etc.).
    
    Args:
        log_files: List of log file paths to scan
        patterns: Custom patterns dictionary (uses SENSITIVE_PATTERNS if None)
    
    Returns:
        List of findings with structure:
        {
            'type': 'email',
            'severity': 'medium',
            'description': 'Email address detected',
            'category': 'PII',
            'file': 'path/to/file.log',
            'line_number': 42,
            'line_content': 'User logged in: user@example.com',
            'matched_value': 'user@example.com'
        }
    """
    if patterns is None:
        patterns = SENSITIVE_PATTERNS
    
    findings = []
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.rstrip('\n\r')
                    
                    # Check each pattern
                    for pattern_name, pattern_info in patterns.items():
                        regex = pattern_info['pattern']
                        matches = re.finditer(regex, line)
                        
                        for match in matches:
                            # Extract the matched value (use group 0 for full match)
                            matched_value = match.group(0)
                            
                            # For patterns with capture groups, use the last group
                            if match.lastindex and match.lastindex > 0:
                                matched_value = match.group(match.lastindex)
                            
                            # Mask the sensitive value for display
                            masked_value = mask_sensitive_value(matched_value, pattern_name)
                            
                            findings.append({
                                'type': pattern_name,
                                'severity': pattern_info['severity'],
                                'description': pattern_info['description'],
                                'category': pattern_info['category'],
                                'file': log_file,
                                'line_number': line_num,
                                'line_content': line,
                                'matched_value': masked_value,
                                'full_match': match.group(0)
                            })
        
        except Exception as e:
            # Log error but continue scanning other files
            continue
    
    return findings


def mask_sensitive_value(value: str, pattern_type: str) -> str:
    """
    Mask sensitive values for safe display.
    
    Args:
        value: The sensitive value to mask
        pattern_type: Type of pattern (e.g., 'email', 'api_key')
    
    Returns:
        Masked version of the value
    """
    if not value or len(value) < 4:
        return '***'
    
    # Different masking strategies based on type
    if pattern_type in ('email',):
        # Show first 2 chars and domain: us***@example.com
        parts = value.split('@')
        if len(parts) == 2:
            local = parts[0][:2] + '***' if len(parts[0]) > 2 else '***'
            return f"{local}@{parts[1]}"
        return '***@***.***'
    
    elif pattern_type in ('phone_number',):
        # Show last 4 digits: ***-***-1234
        return '***-***-' + value[-4:]
    
    elif pattern_type in ('credit_card',):
        # Show last 4 digits: ****-****-****-1234
        clean = re.sub(r'[-\s]', '', value)
        return '****-****-****-' + clean[-4:] if len(clean) >= 4 else '****'
    
    elif pattern_type in ('ssn',):
        # Show last 4 digits: ***-**-1234
        parts = value.split('-')
        if len(parts) == 3:
            return f"***-**-{parts[2]}"
        return '***-**-****'
    
    elif pattern_type in ('ip_address',):
        # Show first octet: 192.*.*.*
        parts = value.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.*.*.*"
        return '*.*.*.*'
    
    else:
        # Generic masking: show first 4 and last 4 chars
        if len(value) <= 8:
            return '***'
        return value[:4] + '***' + value[-4:]


def print_sensitivity_report(findings: List[Dict[str, Any]]):
    """Print the sensitive information detection report."""
    la.print_header("SENSITIVE INFORMATION DETECTION")
    
    if not findings:
        print(la.colorize("  ✓ No sensitive information detected in logs.", "green"))
        print()
        la.print_separator()
        return
    
    # Group findings by severity
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    findings_by_severity = {}
    for finding in findings:
        severity = finding['severity']
        if severity not in findings_by_severity:
            findings_by_severity[severity] = []
        findings_by_severity[severity].append(finding)
    
    # Count by category
    category_counts = {}
    for finding in findings:
        cat = finding['category']
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    # Summary
    total = len(findings)
    critical_count = len(findings_by_severity.get('critical', []))
    high_count = len(findings_by_severity.get('high', []))
    medium_count = len(findings_by_severity.get('medium', []))
    low_count = len(findings_by_severity.get('low', []))
    
    print(f"  {la.colorize('⚠', 'yellow')} Total findings      : {la.colorize(str(total), 'yellow')}")
    
    if critical_count > 0:
        print(f"  {la.colorize('✗', 'red')} Critical severity   : {la.colorize(str(critical_count), 'red')}")
    if high_count > 0:
        print(f"  {la.colorize('!', 'red')} High severity       : {la.colorize(str(high_count), 'red')}")
    if medium_count > 0:
        print(f"  {la.colorize('!', 'yellow')} Medium severity     : {la.colorize(str(medium_count), 'yellow')}")
    if low_count > 0:
        print(f"  {la.colorize('i', 'cyan')} Low severity        : {la.colorize(str(low_count), 'cyan')}")
    
    print(f"\n  {la.colorize('Categories:', 'bold')}")
    for category, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"    • {category:15s} : {count}")
    
    print(f"\n  {la.colorize('Findings by Severity:', 'bold')}")
    la.print_separator()
    
    # Display findings grouped by severity
    for severity in ['critical', 'high', 'medium', 'low']:
        if severity not in findings_by_severity:
            continue
        
        severity_findings = findings_by_severity[severity]
        severity_color = 'red' if severity in ('critical', 'high') else 'yellow' if severity == 'medium' else 'cyan'
        
        print(f"\n  {la.colorize(f'[{severity.upper()}]', severity_color)} {len(severity_findings)} finding(s)")
        print(la.colorize("  " + "─" * 76, "dim"))
        
        # Group by type within severity
        by_type = {}
        for f in severity_findings:
            t = f['type']
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(f)
        
        for finding_type, type_findings in sorted(by_type.items()):
            first = type_findings[0]
            count = len(type_findings)
            
            print(f"\n  {la.colorize('Type:', 'bold')} {first['description']} ({count} occurrence{'s' if count > 1 else ''})")
            print(f"  {la.colorize('Category:', 'dim')} {first['category']}")
            
            # Show first 3 examples
            for i, finding in enumerate(type_findings[:3]):
                file_name = os.path.basename(finding['file'])
                print(f"\n    {la.colorize(f'Example {i+1}:', 'cyan')}")
                print(f"      File: {file_name}:{finding['line_number']}")
                print(f"      Value: {la.colorize(finding['matched_value'], 'yellow')}")
                
                # Show context (truncated)
                context = finding['line_content']
                if len(context) > 100:
                    context = context[:100] + '...'
                print(f"      Context: {context}")
            
            if count > 3:
                print(f"\n    {la.colorize(f'... and {count - 3} more occurrence(s)', 'dim')}")
    
    print()
    la.print_separator()


# ─────────────────────────────────────────────────────────────────────────────
# Pod Health Check - HTML Parser
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Resource Overload Detection Patterns
# ─────────────────────────────────────────────────────────────────────────────

RESOURCE_PATTERNS = {
    'memory_usage': {
        'patterns': [
            r'(?i)memory.*?usage.*?(\d+)%',
            r'(?i)heap.*?used.*?(\d+)%',
            r'(?i)mem.*?utilization.*?(\d+)%',
            r'(?i)heap_used_mb[=:\s]+(\d+).*?heap_max_mb[=:\s]+(\d+)',
        ],
        'category': 'Memory',
        'description': 'Memory usage detected'
    },
    'cpu_usage': {
        'patterns': [
            r'(?i)cpu.*?usage.*?(\d+)%',
            r'(?i)cpu.*?utilization.*?(\d+)%',
            r'(?i)processor.*?load.*?(\d+)%',
        ],
        'category': 'CPU',
        'description': 'CPU usage detected'
    },
    'oom_error': {
        'patterns': [
            r'(?i)OutOfMemory',
            r'(?i)OOM',
            r'(?i)java\.lang\.OutOfMemoryError',
            r'(?i)memory limit exceeded',
            r'(?i)OOMKilled',
        ],
        'category': 'Memory',
        'description': 'Out of Memory error'
    },
    'memory_pressure': {
        'patterns': [
            r'(?i)memory pressure',
            r'(?i)memory leak',
            r'(?i)heap space',
            r'(?i)cannot allocate memory',
        ],
        'category': 'Memory',
        'description': 'Memory pressure indicator'
    },
    'cpu_throttling': {
        'patterns': [
            r'(?i)cpu throttl',
            r'(?i)cpu limit',
            r'(?i)cpu quota exceeded',
        ],
        'category': 'CPU',
        'description': 'CPU throttling detected'
    },
}


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


class ResourceUsageParser(HTMLParser):
    """
    Parse HTML to extract pod resource usage (CPU and Memory).
    
    Extracts resource utilization percentages from HTML tables.
    """
    
    def __init__(self):
        super().__init__()
        self.pods_resources = {}  # Dict: pod_name -> {'cpu': %, 'memory': %}
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.row_data = []
        self.current_pod = None
        
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
            if len(self.row_data) >= 3:
                self._extract_resource_from_row(self.row_data)
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
    
    def _extract_resource_from_row(self, row_data: List[str]):
        """Extract pod name and resource usage from table row."""
        # Skip header rows
        if any(h.lower() in ['name', 'pod', 'pod name', 'status', 'cpu', 'memory', 'usage', 'restarts', 'age']
               for h in row_data[:3]):
            return
        
        # Look for pod name (first column typically) - must contain hyphens and be longer
        pod_name = None
        cpu_usage = None
        memory_usage = None
        
        for i, cell in enumerate(row_data):
            # Check if this looks like a pod name (must have hyphens and be reasonably long)
            if '-' in cell and len(cell) > 10 and re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$', cell, re.IGNORECASE):
                if pod_name is None:  # Only take the first valid pod name
                    pod_name = cell
            # Check for percentage values (CPU/Memory)
            elif '%' in cell and not cell.lower() in ['n/a', 'na']:
                # Extract percentage
                match = re.search(r'(\d+(?:\.\d+)?)%', cell)
                if match:
                    percentage = float(match.group(1))
                    # Assign to CPU or Memory based on position or previous assignment
                    if cpu_usage is None:
                        cpu_usage = percentage
                    elif memory_usage is None:
                        memory_usage = percentage
        
        # Store if we found a pod with resource data
        if pod_name and (cpu_usage is not None or memory_usage is not None):
            self.pods_resources[pod_name] = {
                'cpu': cpu_usage,
                'memory': memory_usage
            }


class FailedPodParser(HTMLParser):
    """
    Parse healthcheck.html to extract failed pod information.
    
    Extracts pods with failed checks, OOMKilled status, and resource usage issues.
    """
    
    def __init__(self):
        super().__init__()
        self.failed_pods = []  # List of dicts with pod info
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.row_data = []
        self.in_pod_usage_section = False  # Track if we're in Failed Pod Usage section
        
    def handle_starttag(self, tag, attrs):
        if tag == 'h2':
            # Check if this is the Failed Pod Usage section
            self.in_pod_usage_section = False
        elif tag == 'table':
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
                self._extract_failed_pod_from_row(self.row_data)
            self.row_data = []
        elif tag in ('td', 'th'):
            self.in_cell = False
            
    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
        
        # Check if we're entering the Failed Pod Usage section
        if 'Failed Pod Usage' in data or 'Pods Usage' in data:
            self.in_pod_usage_section = True
            
        # Collect cell data when in table
        if self.in_table and self.in_row and self.in_cell:
            self.row_data.append(data)
    
    def _extract_failed_pod_from_row(self, row_data: List[str]):
        """Extract failed pod information from table row."""
        # Skip header rows
        if any(h.lower() in ['name', 'pod', 'check', 'type', 'status', 'reason', 'location', 'namespace', 'message']
               for h in row_data[:2]):
            return
        
        # Look for pod name and failure indicators
        pod_name = None
        check_type = None
        status = None
        details = None
        location = None
        namespace = None
        
        # If we're in the Failed Pod Usage section, handle differently
        if self.in_pod_usage_section:
            # Expected format: Location, Name, Namespace, Message
            # e.g., ["hub", "zen-minio-1", "cpd-instance-1", "Memory usage has exceeded the 90% threshold."]
            if len(row_data) >= 4:
                location = row_data[0]
                pod_name = row_data[1]
                namespace = row_data[2]
                details = row_data[3]
                check_type = 'Resource Usage'
                status = 'Resource Overload'
                
                self.failed_pods.append({
                    'pod_name': pod_name,
                    'check_type': check_type,
                    'status': status,
                    'details': details,
                    'location': location,
                    'namespace': namespace
                })
            return
        
        # Original logic for other failed pod sections
        for i, cell in enumerate(row_data):
            # Check if this looks like a pod name (must have hyphens)
            if '-' in cell and re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$', cell, re.IGNORECASE):
                if pod_name is None:
                    pod_name = cell
            # Check for failure keywords
            elif any(keyword in cell.lower() for keyword in ['failed', 'oomkilled', 'error', 'warning', 'back-off']):
                if status is None:
                    status = cell
                elif details is None:
                    details = cell
            # Other cells might be check type or details
            elif pod_name and not check_type and cell not in ['hub', 'spoke']:
                check_type = cell
            elif pod_name and not details and len(cell) > 10:
                details = cell
        
        # Store if we found a failed pod
        if pod_name and (status or details):
            self.failed_pods.append({
                'pod_name': pod_name,
                'check_type': check_type or 'Unknown',
                'status': status or 'Failed',
                'details': details or ''
            })


def parse_resource_usage(html_path: str) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Parse summary.html to extract CPU and Memory usage for each pod.
    
    Returns:
        Dict mapping pod_name -> {'cpu': %, 'memory': %}
    """
    if not os.path.exists(html_path):
        return {}
    
    try:
        with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
    except Exception as e:
        print(la.colorize(f"[WARN] Could not read {html_path}: {e}", "yellow"))
        return {}
    
    parser = ResourceUsageParser()
    parser.feed(html_content)
    
    return parser.pods_resources


def parse_failed_pods(html_path: str) -> List[Dict[str, str]]:
    """
    Parse healthcheck.html to extract failed pod information.
    
    Returns:
        List of dicts with failed pod details
    """
    if not os.path.exists(html_path):
        return []
    
    try:
        with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
    except Exception as e:
        print(la.colorize(f"[WARN] Could not read {html_path}: {e}", "yellow"))
        return []
    
    parser = FailedPodParser()
    parser.feed(html_content)
    
    return parser.failed_pods


def detect_resource_overload(pods_resources: Dict[str, Dict[str, Optional[float]]],
                             threshold: float = 75.0) -> List[Dict[str, Any]]:
    """
    Detect pods with resource usage above threshold.
    
    Args:
        pods_resources: Dict mapping pod_name -> {'cpu': %, 'memory': %}
        threshold: Percentage threshold (default 75%)
    
    Returns:
        List of dicts with overloaded pod information
    """
    overloaded = []
    
    for pod_name, resources in pods_resources.items():
        cpu = resources.get('cpu')
        memory = resources.get('memory')
        
        issues = []
        if cpu is not None and cpu > threshold:
            issues.append(f"CPU: {cpu}%")
        if memory is not None and memory > threshold:
            issues.append(f"Memory: {memory}%")
        
        if issues:
            overloaded.append({
                'pod_name': pod_name,
                'cpu': cpu,
                'memory': memory,
                'issues': issues,
                'severity': 'critical' if (cpu and cpu > 90) or (memory and memory > 90) else 'high'
            })
    
    return overloaded


def merge_flagged_pods(overloaded_pods: List[Dict[str, Any]],
                       failed_pods: List[Dict[str, str]],
                       non_running_pods: List[Tuple[str, str]]) -> List[str]:
    """
    Merge all flagged pods from different sources into a unique list.
    
    Returns:
        List of unique pod names that need investigation
    """
    flagged = set()
    
    # Add overloaded pods
    for pod in overloaded_pods:
        flagged.add(pod['pod_name'])
    
    # Add failed pods
    for pod in failed_pods:
        flagged.add(pod['pod_name'])
    
    # Add non-running pods
    for pod_name, _ in non_running_pods:
        flagged.add(pod_name)
    
    return sorted(list(flagged))


def search_pod_logs_for_resource_issues(pod_name: str, log_files: List[str]) -> List[Dict[str, Any]]:
    """
    Search pod log files for resource-related issues.
    
    Args:
        pod_name: Name of the pod to search for
        log_files: List of log file paths from multiple locations
    
    Returns:
        List of resource-related log entries
    """
    findings = []
    
    # Find log file for this pod
    # Log files are named like: {pod_name}_{container_name}.log
    # Examples:
    # - zen-minio-1_zen-minio.log (pod: zen-minio-1)
    # - wo-mcp-context-forge-67b648c6d-jxnzj_wo-mcp-context-forge.log
    pod_log = None
    for log_file in log_files:
        # Extract filename from log file path
        log_basename = os.path.basename(log_file)
        
        # Check if log file starts with pod name followed by underscore
        # This handles the pattern: {pod_name}_{container_name}.log
        if log_basename.startswith(pod_name + '_'):
            pod_log = log_file
            break
    
    if not pod_log:
        return findings
    
    try:
        with open(pod_log, 'r', encoding='utf-8', errors='replace') as f:
            for line_num, line in enumerate(f, 1):
                # Check against resource patterns
                for pattern_name, pattern_info in RESOURCE_PATTERNS.items():
                    for pattern in pattern_info['patterns']:
                        if re.search(pattern, line, re.IGNORECASE):
                            findings.append({
                                'pod_name': pod_name,
                                'log_file': os.path.basename(pod_log),
                                'line_num': line_num,
                                'line': line.strip(),
                                'pattern': pattern_name,
                                'category': pattern_info['category'],
                                'description': pattern_info['description']
                            })
                            break  # Only match once per line
    except Exception as e:
        print(la.colorize(f"[WARN] Could not read log file {pod_log}: {e}", "yellow"))
    
    return findings


def analyze_resource_root_cause(resource_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze resource-related log findings to determine root cause.
    
    Returns:
        Dict with root cause analysis
    """
    if not resource_findings:
        return {
            'root_cause': 'No resource issues detected',
            'severity': 'info',
            'recommendations': []
        }
    
    # Count pattern occurrences
    pattern_counts = {}
    categories = {}
    
    for finding in resource_findings:
        pattern = finding['pattern']
        category = finding['category']
        
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        categories[category] = categories.get(category, 0) + 1
    
    # Determine primary root cause
    if 'oom_error' in pattern_counts:
        root_cause = 'Out of Memory (OOM) Error'
        severity = 'critical'
        recommendations = [
            'Increase memory limits for affected pods',
            'Check for memory leaks in application code',
            'Review heap size configuration (for Java applications)',
            'Consider horizontal pod autoscaling',
            'Analyze memory usage patterns and optimize'
        ]
    elif 'memory_pressure' in pattern_counts:
        root_cause = 'Memory Pressure'
        severity = 'high'
        recommendations = [
            'Increase memory limits for affected pods',
            'Monitor for memory leaks',
            'Optimize application memory usage',
            'Consider implementing memory caching strategies'
        ]
    elif 'memory_usage' in pattern_counts and categories.get('Memory', 0) > categories.get('CPU', 0):
        root_cause = 'High Memory Utilization'
        severity = 'high'
        recommendations = [
            'Increase memory resource limits',
            'Review application memory configuration',
            'Implement memory usage monitoring',
            'Consider pod resource requests/limits tuning'
        ]
    elif 'cpu_throttling' in pattern_counts:
        root_cause = 'CPU Throttling'
        severity = 'high'
        recommendations = [
            'Increase CPU limits for affected pods',
            'Review CPU quota settings',
            'Optimize application CPU usage',
            'Consider horizontal pod autoscaling'
        ]
    elif 'cpu_usage' in pattern_counts:
        root_cause = 'High CPU Utilization'
        severity = 'high'
        recommendations = [
            'Increase CPU resource limits',
            'Review application CPU configuration',
            'Implement CPU usage monitoring',
            'Consider pod resource requests/limits tuning'
        ]
    else:
        root_cause = 'Resource Utilization Issues'
        severity = 'medium'
        recommendations = [
            'Review resource limits and requests',
            'Monitor resource usage patterns',
            'Consider implementing autoscaling',
            'Optimize application resource usage'
        ]
    
    return {
        'root_cause': root_cause,
        'severity': severity,
        'recommendations': recommendations,
        'pattern_counts': pattern_counts,
        'categories': categories
    }


def print_resource_overload_report(overloaded_pods: List[Dict[str, Any]],
                                   failed_pods: List[Dict[str, str]],
                                   flagged_pods: List[str],
                                   all_resource_findings: Dict[str, List[Dict[str, Any]]],
                                   root_cause_analysis: Dict[str, Any]):
    """Print comprehensive resource overload report."""
    la.print_header("RESOURCE OVERLOAD ANALYSIS")
    
    # Step 1: Resource Usage Summary
    print(f"  {la.colorize('Step 1: Resource Usage Check', 'bold')}")
    print(f"  Threshold: {la.colorize('75%', 'yellow')}\n")
    
    if overloaded_pods:
        print(f"  {la.colorize('⚠', 'red')} Found {la.colorize(str(len(overloaded_pods)), 'red')} pod(s) with high resource usage:\n")
        for pod in overloaded_pods:
            severity_color = 'red' if pod['severity'] == 'critical' else 'yellow'
            print(f"    {la.colorize('•', severity_color)} {pod['pod_name']}")
            for issue in pod['issues']:
                print(f"      {la.colorize(issue, severity_color)}")
    else:
        print(f"  {la.colorize('✓', 'green')} No pods exceeding resource threshold\n")
    
    # Step 2: Failed Pod Checks
    print(f"\n  {la.colorize('Step 2: Failed Pod Checks', 'bold')}\n")
    
    if failed_pods:
        print(f"  {la.colorize('⚠', 'red')} Found {la.colorize(str(len(failed_pods)), 'red')} failed pod check(s):\n")
        for pod in failed_pods:
            print(f"    {la.colorize('•', 'red')} {pod['pod_name']}")
            print(f"      Check: {pod['check_type']}")
            print(f"      Status: {la.colorize(pod['status'], 'red')}")
            if pod['details']:
                print(f"      Details: {pod['details']}")
    else:
        print(f"  {la.colorize('✓', 'green')} No failed pod checks detected\n")
    
    # Step 3: Merged Flagged Pods
    print(f"\n  {la.colorize('Step 3: Merged Flagged Pods', 'bold')}\n")
    print(f"  Total unique pods flagged: {la.colorize(str(len(flagged_pods)), 'cyan')}\n")
    
    if flagged_pods:
        for pod in flagged_pods:
            print(f"    {la.colorize('•', 'cyan')} {pod}")
    
    # Step 4: Log Analysis
    print(f"\n  {la.colorize('Step 4: Resource-Related Log Entries', 'bold')}\n")
    
    total_findings = sum(len(findings) for findings in all_resource_findings.values())
    
    if total_findings > 0:
        print(f"  Found {la.colorize(str(total_findings), 'yellow')} resource-related log entries:\n")
        
        for pod_name in flagged_pods:
            findings = all_resource_findings.get(pod_name, [])
            if findings:
                print(f"    {la.colorize(f'Pod: {pod_name}', 'bold')}")
                print(f"    {la.colorize('─' * 76, 'dim')}")
                
                # Group by category
                by_category = {}
                for finding in findings:
                    cat = finding['category']
                    if cat not in by_category:
                        by_category[cat] = []
                    by_category[cat].append(finding)
                
                for category, cat_findings in by_category.items():
                    print(f"      {la.colorize(f'{category} Issues:', 'yellow')} ({len(cat_findings)} entries)")
                    
                    # Show first 3 entries
                    for i, finding in enumerate(cat_findings[:3]):
                        print(f"        [{finding['log_file']}:{finding['line_num']}] {finding['line'][:100]}")
                    
                    if len(cat_findings) > 3:
                        print(f"        {la.colorize(f'... and {len(cat_findings) - 3} more entries', 'dim')}")
                
                print()
    else:
        print(f"  {la.colorize('No resource-related log entries found', 'dim')}\n")
    
    # Step 5: Root Cause Analysis
    print(f"  {la.colorize('Step 5: Root Cause Analysis', 'bold')}\n")
    
    severity_color = {
        'critical': 'red',
        'high': 'red',
        'medium': 'yellow',
        'low': 'cyan',
        'info': 'green'
    }.get(root_cause_analysis['severity'], 'cyan')
    
    print(f"  {la.colorize('Root Cause:', 'bold')} {la.colorize(root_cause_analysis['root_cause'], severity_color)}")
    print(f"  {la.colorize('Severity:', 'bold')} {la.colorize(root_cause_analysis['severity'].upper(), severity_color)}\n")
    
    if root_cause_analysis.get('pattern_counts'):
        print(f"  {la.colorize('Detected Patterns:', 'dim')}")
        for pattern, count in root_cause_analysis['pattern_counts'].items():
            print(f"    • {pattern}: {count} occurrence(s)")
        print()
    
    # Step 6: Recommendations
    print(f"  {la.colorize('Step 6: Solution Recommendations', 'bold')}\n")
    
    if root_cause_analysis['recommendations']:
        for i, rec in enumerate(root_cause_analysis['recommendations'], 1):
            print(f"    {la.colorize(f'{i}.', 'cyan')} {rec}")
    else:
        print(f"  {la.colorize('No specific recommendations at this time', 'dim')}")
    
    print()
    la.print_separator()


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


def export_resource_report(overloaded_pods: List[Dict[str, Any]],
                          failed_pods: List[Dict[str, str]],
                          flagged_pods: List[str],
                          all_resource_findings: Dict[str, List[Dict[str, Any]]],
                          root_cause_analysis: Dict[str, Any],
                          output_path: str,
                          diagnostics_folder: str,
                          threshold: float):
    """Export resource overload analysis report to a file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        # Header
        f.write("=" * 80 + "\n")
        f.write("WATSONX ORCHESTRATE RESOURCE OVERLOAD ANALYSIS REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Diagnostics Folder: {diagnostics_folder}\n")
        f.write(f"Resource Threshold: {threshold}%\n")
        f.write("=" * 80 + "\n\n")
        
        # Step 1: Resource Usage Summary
        f.write("STEP 1: RESOURCE USAGE CHECK\n")
        f.write("-" * 80 + "\n")
        f.write(f"Threshold: {threshold}%\n\n")
        
        if overloaded_pods:
            f.write(f"Found {len(overloaded_pods)} pod(s) with high resource usage:\n\n")
            for pod in overloaded_pods:
                f.write(f"  • {pod['pod_name']} [{pod['severity'].upper()}]\n")
                for issue in pod['issues']:
                    f.write(f"    - {issue}\n")
                f.write("\n")
        else:
            f.write("✓ No pods exceeding resource threshold\n\n")
        
        # Step 2: Failed Pod Checks
        f.write("\nSTEP 2: FAILED POD CHECKS\n")
        f.write("-" * 80 + "\n")
        
        if failed_pods:
            f.write(f"Found {len(failed_pods)} failed pod check(s):\n\n")
            for pod in failed_pods:
                f.write(f"  • {pod['pod_name']}\n")
                f.write(f"    Check: {pod['check_type']}\n")
                f.write(f"    Status: {pod['status']}\n")
                if pod['details']:
                    f.write(f"    Details: {pod['details']}\n")
                f.write("\n")
        else:
            f.write("✓ No failed pod checks detected\n\n")
        
        # Step 3: Merged Flagged Pods
        f.write("\nSTEP 3: MERGED FLAGGED PODS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total unique pods flagged: {len(flagged_pods)}\n\n")
        
        for pod in flagged_pods:
            f.write(f"  • {pod}\n")
        f.write("\n")
        
        # Step 4: Resource-Related Log Entries
        f.write("\nSTEP 4: RESOURCE-RELATED LOG ENTRIES\n")
        f.write("-" * 80 + "\n")
        
        total_findings = sum(len(findings) for findings in all_resource_findings.values())
        f.write(f"Found {total_findings} resource-related log entries\n\n")
        
        for pod_name in flagged_pods:
            findings = all_resource_findings.get(pod_name, [])
            if findings:
                f.write(f"Pod: {pod_name}\n")
                f.write("-" * 76 + "\n")
                
                # Group by category
                by_category = {}
                for finding in findings:
                    cat = finding['category']
                    if cat not in by_category:
                        by_category[cat] = []
                    by_category[cat].append(finding)
                
                for category, cat_findings in by_category.items():
                    f.write(f"  {category} Issues: ({len(cat_findings)} entries)\n")
                    
                    for finding in cat_findings:
                        f.write(f"    [{finding['log_file']}:{finding['line_num']}] {finding['line']}\n")
                
                f.write("\n")
        
        # Step 5: Root Cause Analysis
        f.write("\nSTEP 5: ROOT CAUSE ANALYSIS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Root Cause: {root_cause_analysis['root_cause']}\n")
        f.write(f"Severity: {root_cause_analysis['severity'].upper()}\n\n")
        
        if root_cause_analysis.get('pattern_counts'):
            f.write("Detected Patterns:\n")
            for pattern, count in root_cause_analysis['pattern_counts'].items():
                f.write(f"  • {pattern}: {count} occurrence(s)\n")
            f.write("\n")
        
        # Step 6: Recommendations
        f.write("\nSTEP 6: SOLUTION RECOMMENDATIONS\n")
        f.write("-" * 80 + "\n")
        
        if root_cause_analysis['recommendations']:
            for i, rec in enumerate(root_cause_analysis['recommendations'], 1):
                f.write(f"  {i}. {rec}\n")
        else:
            f.write("  No specific recommendations at this time\n")
        
        f.write("\n")
        f.write("=" * 80 + "\n")
        f.write("END OF REPORT\n")
        f.write("=" * 80 + "\n")


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
    parser.add_argument(
        "--skip-sensitivity-check",
        action="store_true",
        default=False,
        help="Skip the sensitive information detection step"
    )
    parser.add_argument(
        "--sensitivity-only",
        action="store_true",
        default=False,
        help="Only perform sensitive information detection (skip other analysis)"
    )
    parser.add_argument(
        "--skip-detailed-sensitivity",
        action="store_true",
        default=False,
        help="Skip detailed sensitive information findings in export (only show summary)"
    )
    parser.add_argument(
        "--skip-resource-check",
        action="store_true",
        default=False,
        help="Skip the resource overload analysis step"
    )
    parser.add_argument(
        "--resource-threshold",
        type=float,
        default=75.0,
        metavar="PERCENT",
        help="Resource usage threshold percentage for flagging pods (default: 75.0)"
    )
    parser.add_argument(
        "--resource-only",
        action="store_true",
        default=False,
        help="Only perform resource overload analysis (skip other analysis)"
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
    
    # Determine healthcheck.html path
    healthcheck_detail_path = os.path.join(os.path.dirname(health_check_path), "healthcheck.html")
    
    # ── Step 2: Pod Health Check ──────────────────────────────────────────────
    all_pods = []
    non_running_pods = []
    
    if not args.skip_health_check and not args.resource_only:
        all_pods, non_running_pods = parse_pod_health(health_check_path)
        print_pod_health_report(health_check_path, all_pods, non_running_pods)
    else:
        if args.resource_only:
            # Still need to parse for resource check
            all_pods, non_running_pods = parse_pod_health(health_check_path)
        else:
            print(la.colorize("\n  [INFO] Pod health check skipped (--skip-health-check).\n", "dim"))
    
    # ── Step 2.5: Resource Overload Analysis ──────────────────────────────────
    overloaded_pods = []
    failed_pods = []
    flagged_pods = []
    all_resource_findings = {}
    resource_root_cause = {}
    
    if not args.skip_resource_check or args.resource_only:
        # Parse resource usage from summary.html
        pods_resources = parse_resource_usage(health_check_path)
        
        # Detect overloaded pods
        overloaded_pods = detect_resource_overload(pods_resources, args.resource_threshold)
        
        # Parse failed pods from healthcheck.html
        failed_pods = parse_failed_pods(healthcheck_detail_path)
        
        # Merge all flagged pods
        flagged_pods = merge_flagged_pods(overloaded_pods, failed_pods, non_running_pods)
        
        # Search logs for resource issues in flagged pods
        # Discover logs from both watsonx Orchestrate and IBM Software Hub directories
        log_files = []
        
        # Primary location: watsonx Orchestrate logs
        if os.path.isdir(logs_path):
            log_files.extend(la.discover_log_files(logs_path, args.ext))
        
        # Secondary location: IBM Software Hub logs (for zen-* services)
        zen_logs_path = os.path.join(diagnostics_folder, "IBM Software Hub", "hub", "containerLogs", "cpd-instance-1")
        if os.path.isdir(zen_logs_path):
            log_files.extend(la.discover_log_files(zen_logs_path, args.ext))
        
        if log_files:
            for pod_name in flagged_pods:
                findings = search_pod_logs_for_resource_issues(pod_name, log_files)
                if findings:
                    all_resource_findings[pod_name] = findings
        
        # Analyze root cause
        all_findings_flat = []
        for findings in all_resource_findings.values():
            all_findings_flat.extend(findings)
        
        resource_root_cause = analyze_resource_root_cause(all_findings_flat)
        
        # Print report
        print_resource_overload_report(
            overloaded_pods,
            failed_pods,
            flagged_pods,
            all_resource_findings,
            resource_root_cause
        )
    else:
        print(la.colorize("\n  [INFO] Resource overload check skipped (--skip-resource-check).\n", "dim"))
    
    # If resource-only mode, skip the rest
    if args.resource_only:
        if args.output:
            export_resource_report(
                overloaded_pods,
                failed_pods,
                flagged_pods,
                all_resource_findings,
                resource_root_cause,
                args.output,
                diagnostics_folder,
                args.resource_threshold
            )
            print(la.colorize(f"\n  Resource analysis report exported to: {args.output}", "green"))
        sys.exit(0)
    
    # ── Step 3: Sensitive Information Detection ───────────────────────────────
    sensitivity_findings = []
    
    if not args.skip_sensitivity_check or args.sensitivity_only:
        # Discover log files for sensitivity scanning
        if os.path.isdir(logs_path):
            print(la.colorize("\n  Discovering log files for sensitivity scan...", "dim"))
            scan_log_files = la.discover_log_files(logs_path, args.ext)
            
            if scan_log_files:
                print(f"  Found {la.colorize(str(len(scan_log_files)), 'cyan')} log file(s) to scan\n")
                print(la.colorize("  Scanning for sensitive information...", "dim"))
                sensitivity_findings = scan_sensitive_information(scan_log_files)
                print_sensitivity_report(sensitivity_findings)
            else:
                print(la.colorize(
                    f"  No log files found for sensitivity scanning in {logs_path}",
                    "yellow"
                ))
        else:
            print(la.colorize(
                f"\n  [WARN] Cannot perform sensitivity scan - logs folder not found:\n  {logs_path}",
                "yellow"
            ))
    
    # If sensitivity-only mode, skip the rest
    if args.sensitivity_only:
        if args.output:
            export_sensitivity_report(sensitivity_findings, args.output, diagnostics_folder, event_string)
            print(la.colorize(f"\n  Sensitivity report exported to: {args.output}", "green"))
        sys.exit(0)
    
    # ── Step 4: Log Analysis ──────────────────────────────────────────────────
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
        # Don't exit yet - we may still want to export pod health and sensitivity results
        # Create empty journey for export
        journey = []
        findings = []
        correlation_values = []
        context_entries = []
        
        # Skip to summary and export
        print()
        la.print_separator()
        
        # Summary
        la.print_summary(
            log_files=log_files,
            event_string=event_string,
            correlation_key=correlation_key,
            correlation_values=[],
            event_hits=[],
            journey=[],
            findings=[],
        )
        
        # Add sensitivity summary if findings exist
        if sensitivity_findings and not args.skip_sensitivity_check:
            print(la.colorize("\n  Sensitive Information Summary:", "bold"))
            print(f"    Total findings: {len(sensitivity_findings)}")
            critical = sum(1 for f in sensitivity_findings if f['severity'] == 'critical')
            if critical > 0:
                print(f"    {la.colorize(f'⚠ {critical} CRITICAL findings require immediate attention', 'red')}")
        
        # Export if requested (even with no event matches)
        if args.output:
            output_path = args.output
            
            # Write diagnostics report with pod health and sensitivity only
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
                
                # Section 0: Sensitive Information Detection (if performed)
                if sensitivity_findings and not args.skip_sensitivity_check:
                    f.write("=" * 80 + "\n")
                    f.write("SECTION 0: SENSITIVE INFORMATION DETECTION\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"Total findings: {len(sensitivity_findings)}\n\n")
                    
                    # Count by severity
                    sev_counts = {}
                    for finding in sensitivity_findings:
                        sev = finding['severity']
                        sev_counts[sev] = sev_counts.get(sev, 0) + 1
                    
                    for severity in ['critical', 'high', 'medium', 'low']:
                        if severity in sev_counts:
                            f.write(f"{severity.upper():10s}: {sev_counts[severity]}\n")
                    
                    # Count by category
                    cat_counts = {}
                    for finding in sensitivity_findings:
                        cat = finding['category']
                        cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    
                    f.write("\nCategories:\n")
                    for category, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
                        f.write(f"  {category:15s}: {count}\n")
                    
                    f.write("\nTop 10 Findings:\n")
                    f.write("-" * 80 + "\n")
                    for i, finding in enumerate(sensitivity_findings[:10], 1):
                        file_name = os.path.basename(finding['file'])
                        f.write(f"\n[{i}] [{finding['severity'].upper()}] {finding['description']}\n")
                        f.write(f"    File: {file_name}:{finding['line_number']}\n")
                        f.write(f"    Value: {finding['matched_value']}\n")
                    
                    if len(sensitivity_findings) > 10:
                        f.write(f"\n... and {len(sensitivity_findings) - 10} more findings\n")
                    
                    f.write("\n")
                
                # Section 0.5: Resource Overload Analysis (if performed)
                if not args.skip_resource_check and (overloaded_pods or failed_pods or flagged_pods):
                    f.write("=" * 80 + "\n")
                    f.write("SECTION 0.5: RESOURCE OVERLOAD ANALYSIS\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"Resource Threshold: {args.resource_threshold}%\n\n")
                    
                    # Step 1: Overloaded pods
                    f.write("Step 1: Resource Usage Check\n")
                    f.write("-" * 80 + "\n")
                    if overloaded_pods:
                        f.write(f"Found {len(overloaded_pods)} pod(s) with high resource usage:\n\n")
                        for pod in overloaded_pods:
                            f.write(f"  • {pod['pod_name']}\n")
                            for issue in pod['issues']:
                                f.write(f"    - {issue}\n")
                            f.write("\n")
                    else:
                        f.write("No pods exceeding resource threshold\n\n")
                    
                    # Step 2: Failed pods
                    f.write("Step 2: Failed Pod Checks\n")
                    f.write("-" * 80 + "\n")
                    if failed_pods:
                        f.write(f"Found {len(failed_pods)} failed pod check(s):\n\n")
                        for pod in failed_pods:
                            f.write(f"  • {pod['pod_name']}\n")
                            f.write(f"    Check: {pod.get('check', 'N/A')}\n")
                            f.write(f"    Status: {pod['status']}\n")
                            if 'details' in pod:
                                f.write(f"    Details: {pod['details']}\n")
                            f.write("\n")
                    else:
                        f.write("No failed pod checks detected\n\n")
                    
                    # Step 3: Merged flagged pods
                    f.write("Step 3: Merged Flagged Pods\n")
                    f.write("-" * 80 + "\n")
                    f.write(f"Total unique pods flagged: {len(flagged_pods)}\n\n")
                    if flagged_pods:
                        for pod in flagged_pods:
                            f.write(f"  • {pod}\n")
                        f.write("\n")
                    
                    # Step 4: Resource-related log entries
                    f.write("Step 4: Resource-Related Log Entries\n")
                    f.write("-" * 80 + "\n")
                    if all_resource_findings:
                        total_findings = sum(len(findings) for findings in all_resource_findings.values())
                        f.write(f"Found {total_findings} resource-related log entries:\n\n")
                        for pod_name, findings in all_resource_findings.items():
                            f.write(f"Pod: {pod_name}\n")
                            # Group by category
                            by_category = {}
                            for finding in findings:
                                cat = finding['category']
                                if cat not in by_category:
                                    by_category[cat] = []
                                by_category[cat].append(finding)
                            
                            for category, cat_findings in by_category.items():
                                f.write(f"  {category} Issues: ({len(cat_findings)} entries)\n")
                                for finding in cat_findings[:3]:  # Show first 3
                                    f.write(f"    Line {finding['line_num']}: {finding['line'][:100]}\n")
                                if len(cat_findings) > 3:
                                    f.write(f"    ... and {len(cat_findings) - 3} more\n")
                            f.write("\n")
                    else:
                        f.write("No resource-related log entries found\n\n")
                    
                    # Step 5: Root cause analysis
                    f.write("Step 5: Root Cause Analysis\n")
                    f.write("-" * 80 + "\n")
                    if resource_root_cause:
                        f.write(f"Root Cause: {resource_root_cause.get('root_cause', 'Unknown')}\n")
                        f.write(f"Severity: {resource_root_cause.get('severity', 'INFO')}\n")
                        if 'details' in resource_root_cause:
                            f.write(f"Details: {resource_root_cause['details']}\n")
                        f.write("\n")
                    
                    # Step 6: Recommendations
                    f.write("Step 6: Solution Recommendations\n")
                    f.write("-" * 80 + "\n")
                    if resource_root_cause and 'recommendations' in resource_root_cause:
                        for i, rec in enumerate(resource_root_cause['recommendations'], 1):
                            f.write(f"{i}. {rec}\n")
                        f.write("\n")
                    else:
                        f.write("No specific recommendations at this time\n\n")
                
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
                f.write(f"Event hits          : 0 (no matches found)\n")
                f.write("\n")
                
                # Append detailed sensitivity findings if any (unless skipped)
                if sensitivity_findings and not args.skip_sensitivity_check and not args.skip_detailed_sensitivity:
                    f.write("\n" + "=" * 80 + "\n")
                    f.write("SECTION 3: DETAILED SENSITIVE INFORMATION FINDINGS\n")
                    f.write("=" * 80 + "\n\n")
                    
                    # Group by severity
                    findings_by_severity = {}
                    for finding in sensitivity_findings:
                        severity = finding['severity']
                        if severity not in findings_by_severity:
                            findings_by_severity[severity] = []
                        findings_by_severity[severity].append(finding)
                    
                    # Write findings by severity
                    for severity in ['critical', 'high', 'medium', 'low']:
                        if severity not in findings_by_severity:
                            continue
                        
                        severity_findings_list = findings_by_severity[severity]
                        f.write(f"\n[{severity.upper()}] {len(severity_findings_list)} finding(s)\n")
                        f.write("-" * 80 + "\n\n")
                        
                        # Group by type
                        by_type = {}
                        for finding in severity_findings_list:
                            t = finding['type']
                            if t not in by_type:
                                by_type[t] = []
                            by_type[t].append(finding)
                        
                        for finding_type, type_findings in sorted(by_type.items()):
                            first = type_findings[0]
                            f.write(f"Type: {first['description']} ({len(type_findings)} occurrence(s))\n")
                            f.write(f"Category: {first['category']}\n\n")
                            
                            for i, finding in enumerate(type_findings, 1):
                                file_name = os.path.basename(finding['file'])
                                f.write(f"  [{i}] {file_name}:{finding['line_number']}\n")
                                f.write(f"      Value: {finding['matched_value']}\n")
                                f.write(f"      Context: {finding['line_content']}\n\n")
            
            print(la.colorize(f"\n  Diagnostics report (pod health + sensitivity scan) exported to: {output_path}", "green"))
        
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
    
    # Add sensitivity summary if findings exist
    if sensitivity_findings and not args.skip_sensitivity_check:
        print(la.colorize("\n  Sensitive Information Summary:", "bold"))
        print(f"    Total findings: {len(sensitivity_findings)}")
        critical = sum(1 for f in sensitivity_findings if f['severity'] == 'critical')
        if critical > 0:
            print(f"    {la.colorize(f'⚠ {critical} CRITICAL findings require immediate attention', 'red')}")
    
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
            # Section 0: Sensitive Information Detection (if performed)
            if sensitivity_findings and not args.skip_sensitivity_check:
                f.write("=" * 80 + "\n")
                f.write("SECTION 0: SENSITIVE INFORMATION DETECTION\n")
                f.write("=" * 80 + "\n")
                f.write(f"Total findings: {len(sensitivity_findings)}\n\n")
                
                # Count by severity
                sev_counts = {}
                for finding in sensitivity_findings:
                    sev = finding['severity']
                    sev_counts[sev] = sev_counts.get(sev, 0) + 1
                
                for severity in ['critical', 'high', 'medium', 'low']:
                    if severity in sev_counts:
                        f.write(f"{severity.upper():10s}: {sev_counts[severity]}\n")
                
                # Count by category
                cat_counts = {}
                for finding in sensitivity_findings:
                    cat = finding['category']
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
                
                f.write("\nCategories:\n")
                for category, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
                    f.write(f"  {category:15s}: {count}\n")
                
                f.write("\nTop 10 Findings:\n")
                f.write("-" * 80 + "\n")
                for i, finding in enumerate(sensitivity_findings[:10], 1):
                    file_name = os.path.basename(finding['file'])
                    f.write(f"\n[{i}] [{finding['severity'].upper()}] {finding['description']}\n")
                    f.write(f"    File: {file_name}:{finding['line_number']}\n")
                    f.write(f"    Value: {finding['matched_value']}\n")
                
                if len(sensitivity_findings) > 10:
                    f.write(f"\n... and {len(sensitivity_findings) - 10} more findings\n")
                
                f.write("\n")
            
            # Section 0.5: Resource Overload Analysis (if performed)
            if not args.skip_resource_check and (overloaded_pods or failed_pods or flagged_pods):
                f.write("=" * 80 + "\n")
                f.write("SECTION 0.5: RESOURCE OVERLOAD ANALYSIS\n")
                f.write("=" * 80 + "\n")
                f.write(f"Resource Threshold: {args.resource_threshold}%\n\n")
                
                # Step 1: Overloaded pods
                f.write("Step 1: Resource Usage Check\n")
                f.write("-" * 80 + "\n")
                if overloaded_pods:
                    f.write(f"Found {len(overloaded_pods)} pod(s) with high resource usage:\n\n")
                    for pod in overloaded_pods:
                        f.write(f"  • {pod['pod_name']}\n")
                        for issue in pod['issues']:
                            f.write(f"    - {issue}\n")
                        f.write("\n")
                else:
                    f.write("No pods exceeding resource threshold\n\n")
                
                # Step 2: Failed pods
                f.write("Step 2: Failed Pod Checks\n")
                f.write("-" * 80 + "\n")
                if failed_pods:
                    f.write(f"Found {len(failed_pods)} failed pod check(s):\n\n")
                    for pod in failed_pods:
                        f.write(f"  • {pod['pod_name']}\n")
                        f.write(f"    Check: {pod.get('check', 'N/A')}\n")
                        f.write(f"    Status: {pod['status']}\n")
                        if 'details' in pod:
                            f.write(f"    Details: {pod['details']}\n")
                        f.write("\n")
                else:
                    f.write("No failed pod checks detected\n\n")
                
                # Step 3: Merged flagged pods
                f.write("Step 3: Merged Flagged Pods\n")
                f.write("-" * 80 + "\n")
                f.write(f"Total unique pods flagged: {len(flagged_pods)}\n\n")
                if flagged_pods:
                    for pod in flagged_pods:
                        f.write(f"  • {pod}\n")
                    f.write("\n")
                
                # Step 4: Resource-related log entries
                f.write("Step 4: Resource-Related Log Entries\n")
                f.write("-" * 80 + "\n")
                if all_resource_findings:
                    total_findings = sum(len(findings) for findings in all_resource_findings.values())
                    f.write(f"Found {total_findings} resource-related log entries:\n\n")
                    for pod_name, findings in all_resource_findings.items():
                        f.write(f"Pod: {pod_name}\n")
                        # Group by category
                        by_category = {}
                        for finding in findings:
                            cat = finding['category']
                            if cat not in by_category:
                                by_category[cat] = []
                            by_category[cat].append(finding)
                        
                        for category, cat_findings in by_category.items():
                            f.write(f"  {category} Issues: ({len(cat_findings)} entries)\n")
                            for finding in cat_findings[:3]:  # Show first 3
                                f.write(f"    Line {finding['line_num']}: {finding['line'][:100]}\n")
                            if len(cat_findings) > 3:
                                f.write(f"    ... and {len(cat_findings) - 3} more\n")
                        f.write("\n")
                else:
                    f.write("No resource-related log entries found\n\n")
                
                # Step 5: Root cause analysis
                f.write("Step 5: Root Cause Analysis\n")
                f.write("-" * 80 + "\n")
                if resource_root_cause:
                    f.write(f"Root Cause: {resource_root_cause.get('root_cause', 'Unknown')}\n")
                    f.write(f"Severity: {resource_root_cause.get('severity', 'INFO')}\n")
                    if 'details' in resource_root_cause:
                        f.write(f"Details: {resource_root_cause['details']}\n")
                    f.write("\n")
                
                # Step 6: Recommendations
                f.write("Step 6: Solution Recommendations\n")
                f.write("-" * 80 + "\n")
                if resource_root_cause and 'recommendations' in resource_root_cause:
                    for i, rec in enumerate(resource_root_cause['recommendations'], 1):
                        f.write(f"{i}. {rec}\n")
                    f.write("\n")
                else:
                    f.write("No specific recommendations at this time\n\n")
            
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
        
        # Append Section 5: Detailed Sensitive Information Findings (if any and not skipped)
        if sensitivity_findings and not args.skip_sensitivity_check and not args.skip_detailed_sensitivity:
            with open(output_path, 'a', encoding='utf-8') as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write("SECTION 5: DETAILED SENSITIVE INFORMATION FINDINGS\n")
                f.write("=" * 80 + "\n\n")
                
                # Group by severity
                findings_by_severity = {}
                for finding in sensitivity_findings:
                    severity = finding['severity']
                    if severity not in findings_by_severity:
                        findings_by_severity[severity] = []
                    findings_by_severity[severity].append(finding)
                
                # Write findings by severity
                for severity in ['critical', 'high', 'medium', 'low']:
                    if severity not in findings_by_severity:
                        continue
                    
                    severity_findings = findings_by_severity[severity]
                    f.write(f"\n[{severity.upper()}] {len(severity_findings)} finding(s)\n")
                    f.write("-" * 80 + "\n\n")
                    
                    # Group by type
                    by_type = {}
                    for finding in severity_findings:
                        t = finding['type']
                        if t not in by_type:
                            by_type[t] = []
                        by_type[t].append(finding)
                    
                    for finding_type, type_findings in sorted(by_type.items()):
                        first = type_findings[0]
                        f.write(f"Type: {first['description']} ({len(type_findings)} occurrence(s))\n")
                        f.write(f"Category: {first['category']}\n\n")
                        
                        for i, finding in enumerate(type_findings, 1):
                            file_name = os.path.basename(finding['file'])
                            f.write(f"  [{i}] {file_name}:{finding['line_number']}\n")
                            f.write(f"      Value: {finding['matched_value']}\n")
                            f.write(f"      Context: {finding['line_content']}\n\n")
        
        # Append Final Summary Section
        with open(output_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write("SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            
            # Resource Summary
            if not args.skip_resource_check and (overloaded_pods or failed_pods or flagged_pods):
                f.write("Resource Analysis:\n")
                f.write("-" * 80 + "\n")
                f.write(f"  Pods flagged for resource issues: {len(flagged_pods)}\n")
                if overloaded_pods:
                    f.write(f"  Pods exceeding {args.resource_threshold}% threshold: {len(overloaded_pods)}\n")
                if failed_pods:
                    f.write(f"  Failed pod checks: {len(failed_pods)}\n")
                if resource_root_cause and resource_root_cause.get('severity') in ['critical', 'high']:
                    f.write(f"  ⚠ Resource root cause: {resource_root_cause.get('root_cause', 'Unknown')} ({resource_root_cause.get('severity', 'INFO').upper()})\n")
                f.write("\n")
            
            # Pod Health Summary
            f.write("Pod Health:\n")
            f.write("-" * 80 + "\n")
            if all_pods:
                f.write(f"  Total pods: {len(all_pods)}\n")
                f.write(f"  Healthy pods: {len(all_pods) - len(non_running_pods)}\n")
                f.write(f"  Unhealthy pods: {len(non_running_pods)}\n")
            else:
                f.write("  No pod health information available\n")
            f.write("\n")
            
            # Sensitivity Summary
            if sensitivity_findings and not args.skip_sensitivity_check:
                f.write("Sensitive Information:\n")
                f.write("-" * 80 + "\n")
                f.write(f"  Total findings: {len(sensitivity_findings)}\n")
                critical = sum(1 for f in sensitivity_findings if f['severity'] == 'critical')
                high = sum(1 for f in sensitivity_findings if f['severity'] == 'high')
                if critical > 0:
                    f.write(f"  ⚠ CRITICAL findings: {critical}\n")
                if high > 0:
                    f.write(f"  ⚠ HIGH findings: {high}\n")
                f.write("\n")
            
            # Log Analysis Summary
            f.write("Log Analysis:\n")
            f.write("-" * 80 + "\n")
            f.write(f"  Event searched: {repr(event_string)}\n")
            f.write(f"  Event hits: {len(event_hits)}\n")
            f.write(f"  Journey entries: {len(journey)}\n")
            if correlation_key:
                f.write(f"  Correlation key: {repr(correlation_key)}\n")
                f.write(f"  Correlation values found: {len(correlation_values)}\n")
            if findings:
                top = findings[0]
                f.write(f"  Root cause: {top.category} ({top.severity.upper()})\n")
                f.write(f"  Description: {top.message}\n")
            f.write("\n")
            
            f.write("=" * 80 + "\n")
            f.write(f"Report generated: {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n")
        
        print(la.colorize(f"\n  Full diagnostics report exported to: {output_path}", "green"))


if __name__ == "__main__":
    main()

# Made with Bob

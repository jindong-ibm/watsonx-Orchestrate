# watsonx Orchestrate Diagnostics Analyzer

A comprehensive diagnostics tool for watsonx Orchestrate that combines pod health checking with advanced log analysis and root cause detection.

---

## Overview

The Diagnostics Analyzer is an enhanced version of the log analyzer specifically designed for watsonx Orchestrate diagnostics folders. It provides:

1. **Pod Health Check** - Parses `Healthcheck/summary.html` to identify non-running pods
2. **Resource Overload Analysis** - Detects pods with high CPU/Memory usage and analyzes resource-related issues
3. **Sensitive Information Detection** - Scans logs for PII, credentials, tokens, and other sensitive data
4. **Log Analysis** - Searches container logs for specific events with correlation tracking
5. **Root Cause Analysis** - Automatically detects and ranks failure patterns by severity

---

## Features

| Feature | Description |
|---|---|
| **HTML Parsing** | Extracts pod status from HTML summary files |
| **Multi-Pod Analysis** | Identifies all non-running pods (CrashLoopBackOff, Pending, Failed, etc.) |
| **Sensitive Data Detection** | Scans for 15+ types of sensitive information (PII, credentials, tokens, etc.) |
| **Smart Masking** | Automatically masks sensitive values in reports for safe sharing |
| **Event Correlation** | Tracks events across multiple container logs using correlation keys |
| **Time-Sorted Journey** | Merges logs from different pods into a unified timeline |
| **Root Cause Detection** | Scans for 20+ failure patterns (OOM, timeouts, connection errors, etc.) |
| **Severity Ranking** | Prioritizes findings by CRITICAL → HIGH → MEDIUM → LOW |
| **Unified Report** | Combines pod health + sensitivity scan + log analysis + RCA |
| **Export** | Saves complete diagnostics report to a text file |

---

## Requirements

- Python 3.8 or later
- No external dependencies (uses stdlib only: `html.parser`, `re`, `os`, etc.)
- Requires `log_analyzer.py` in the same directory

---

## Diagnostics Folder Structure

The tool expects the following structure:

```
<diagnostics_folder>/
├── Healthcheck/
│   └── summary.html              # Pod status information
└── watsonx Orchestrate/
    └── hub/
        └── containerLogs/
            └── cpd-instance-1/
                ├── zen-watcher.log
                ├── assistant-gateway.log
                ├── orchestrate-api.log
                └── ... (other pod logs)
```

---

## Usage

### Basic Usage

```bash
python diagnostics_analyzer.py <diagnostics_folder> <event_string>
```

### With Correlation Key

```bash
python diagnostics_analyzer.py <diagnostics_folder> <event_string> --key <correlation_key>
```

### Common Examples

```bash
# Analyze OutOfMemory errors, correlate by pod name
python diagnostics_analyzer.py /path/to/diagnostics "OutOfMemory" --key pod

# Search for all ERROR entries, correlate by request-id
python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key request-id

# Analyze CrashLoopBackOff issues
python diagnostics_analyzer.py /path/to/diagnostics "CrashLoop" --key pod

# Check for timeout issues
python diagnostics_analyzer.py /path/to/diagnostics "timeout" --key transaction-id

# Search for strings with quotes or special characters (wrap in single quotes)
python diagnostics_analyzer.py /path/to/diagnostics '"level"="ERROR"' --key transaction-id

# Or escape the quotes with backslashes
python diagnostics_analyzer.py /path/to/diagnostics "\"level\"=\"ERROR\"" --key transaction-id

# Export full report
python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key pod --output report.txt
```

### Searching for Strings with Special Characters

**Important:** The search string must match EXACTLY what appears in your log files.

#### Common Scenarios

**Scenario 1: Log contains `level=ERROR` (no quotes)**
```bash
# Correct - search for level=ERROR without quotes
python diagnostics_analyzer.py /path/to/diagnostics "level=ERROR" --key transaction-id

# Wrong - this searches for the literal string with quotes
python diagnostics_analyzer.py /path/to/diagnostics '"level"="ERROR"' --key transaction-id
```

**Scenario 2: Log contains `"level"="ERROR"` (with quotes)**
```bash
# Correct - use single quotes to preserve inner double quotes
python diagnostics_analyzer.py /path/to/diagnostics '"level"="ERROR"' --key transaction-id

# Or escape the inner quotes
python diagnostics_analyzer.py /path/to/diagnostics "\"level\"=\"ERROR\"" --key transaction-id
```

**Scenario 3: Log contains JSON like `{"level":"ERROR"}`**
```bash
# Option 1: Search for just the value (simplest)
python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key x_ibm_wo_transaction_id

# Option 2: Search for the key-value pair (more specific)
python diagnostics_analyzer.py /path/to/diagnostics '"level":"ERROR"' --key x_ibm_wo_transaction_id

# Option 3: Search for part of the error message
python diagnostics_analyzer.py /path/to/diagnostics "execution was terminated" --key x_ibm_wo_transaction_id
```

**Quick Rule:**
- If your log has quotes → include them in your search string
- If your log has NO quotes → don't include them in your search string
- Use single quotes `'...'` around the search string to preserve any inner quotes

---

## Command-Line Options

| Option | Description |
|---|---|
| `diagnostics_folder` | Path to the diagnostics folder (required) |
| `event` | Event string to search for in logs (required) |
| `--key / -k` | Correlation key (e.g., `pod`, `transaction-id`, `request-id`) |
| `--ext / -e` | Log file extensions to scan (default: `.log .txt`) |
| `--case-sensitive / -c` | Enable case-sensitive matching |
| `--output / -o` | Export full report to a file |
| `--no-color` | Disable ANSI color output |
| `--skip-health-check` | Skip the pod health check step |
| `--skip-resource-check` | Skip the resource overload analysis step |
| `--resource-only` | Only perform resource overload analysis (skip other analysis) |
| `--resource-threshold` | Resource usage threshold percentage for flagging pods (default: 75.0) |
| `--skip-sensitivity-check` | Skip the sensitive information detection step |
| `--sensitivity-only` | Only perform sensitive information detection (skip other analysis) |
| `--skip-detailed-sensitivity` | Skip detailed sensitive information findings in export (only show summary) |
| `--skip-rca` | Skip the root cause analysis step |

---

## Output Sections

### 1. Pod Health Check

```
════════════════════════════════════════════════════════════════════════════════
  POD HEALTH CHECK
════════════════════════════════════════════════════════════════════════════════
  Source: /path/to/diagnostics/Healthcheck/summary.html

  ✓ Total pods found    : 10
  ✓ Running pods        : 8
  ✗ Non-running pods    : 2

  Non-Running Pods:
────────────────────────────────────────────────────────────────────────────────
  [CRASHLOOPBACKOFF]             zen-watcher-5c9d8f7b4-p3q1r
  [PENDING]                      assistant-gateway-7f9c8d6b5-r5s3t
```

### 2. Sensitive Information Detection

```
════════════════════════════════════════════════════════════════════════════════
  SENSITIVE INFORMATION DETECTION
════════════════════════════════════════════════════════════════════════════════

  ⚠ Total findings      : 12
  ✗ Critical severity   : 3
  ! High severity       : 2
  ! Medium severity     : 5
  i Low severity        : 2

  Categories:
    Credentials     : 5
    PII             : 4
    Network         : 2
    Financial       : 1

  Findings by Severity:
────────────────────────────────────────────────────────────────────────────────

  [CRITICAL] 3 finding(s)
  ────────────────────────────────────────────────────────────────────────────

  Type: API key detected (2 occurrences)
  Category: Credentials

    Example 1:
      File: orchestrate-api.log:145
      Value: AKIA****ABCD
      Context: [2024-03-15T10:15:23Z] Connecting to AWS with key: AKIAIOSFODNN7EXAMPLE

    Example 2:
      File: assistant-gateway.log:89
      Value: api_****xyz9
      Context: [2024-03-15T10:20:45Z] API authentication: api_key=sk_test_xyz9

  Type: Password detected (1 occurrence)
  Category: Credentials

    Example 1:
      File: zen-watcher.log:234
      Value: pass****word
      Context: [2024-03-15T10:25:12Z] Database connection: password=mypassword123
```

### 3. Log Analysis

```
════════════════════════════════════════════════════════════════════════════════
  LOG ANALYSIS
════════════════════════════════════════════════════════════════════════════════
  Log folder: /path/to/diagnostics/watsonx Orchestrate/hub/containerLogs/cpd-instance-1
  Event     : 'OutOfMemory'
  Key       : 'pod'

  Found 5 matching line(s)
  Extracted: zen-watcher-5c9d8f7b4-p3q1r
  Found 16 context line(s)
  Journey contains 16 unique entries
```

### 4. Event Journey

Time-sorted log entries from all pods, with `[EVENT]` and `[CTX]` badges:

```
▶ FILE: zen-watcher.log
────────────────────────────────────────────────────────────────────────────────
  [2024-03-15T10:26:15.678Z] L    6 [CTX]   WARN  High memory usage detected: 85%
  [2024-03-15T10:27:12.234Z] L    8 [EVENT] [CTX]  ERROR OutOfMemory error in watcher thread
  [2024-03-15T10:27:12.567Z] L    9 [EVENT] [CTX]  ERROR java.lang.OutOfMemoryError: Java heap space
```

### 5. Root Cause Analysis

```
════════════════════════════════════════════════════════════════════════════════
  ROOT CAUSE ANALYSIS
════════════════════════════════════════════════════════════════════════════════

  Most Likely Root Cause:
  ────────────────────────────────────────────────────────────
  Category  : Out of Memory
  Severity  : CRITICAL
  Summary   : An out-of-memory condition was detected.
  Suggestion: Increase heap/memory limits, profile for memory leaks, or scale horizontally.

  Timeline: journey spans 4.1 minutes

  All Detected Signals:
  ────────────────────────────────────────────────────────────
   1. [CRITICAL] Out of Memory  –  An out-of-memory condition was detected.
   2. [MEDIUM]   Generic Error  –  A generic ERROR/FATAL log level entry was found.
   3. [LOW]      Warning  –  Warning-level entries were present in the journey.
```

---

## Sensitive Information Detection

### Overview

The diagnostics analyzer automatically scans all log files for sensitive information including:
- **Personal Identifiable Information (PII)**: Email addresses, phone numbers, SSNs
- **Credentials**: API keys, passwords, tokens, private keys
- **Financial Data**: Credit card numbers
- **Network Information**: IP addresses, connection strings

### Detected Patterns

**Note:** All patterns are designed to minimize false positives by using context-aware matching where possible.

| Type | Severity | Category | Description | Context Required |
|---|---|---|---|---|
| **Email Address** | Medium | PII | Email addresses (user@example.com) | No |
| **SSN** | Critical | PII | Social Security Numbers (###-##-####) | Yes - requires "ssn" or "social security" keyword |
| **Phone Number** | Medium | PII | Phone numbers in various formats | Yes - requires "phone", "tel", "mobile", or "cell" keyword |
| **Credit Card** | Critical | Financial | Credit card numbers (16 digits with valid prefixes) | Yes - requires "card", "cc", or "credit card" keyword, OR matches Visa/MC/Amex/Discover patterns |
| **API Key** | Critical | Credentials | API keys and secrets (min 32 chars) | Yes - requires "api_key", "apikey", or "api_secret" keyword |
| **Bearer Token** | Critical | Credentials | OAuth bearer tokens (min 32 chars) | Yes - requires "Bearer" prefix |
| **JWT Token** | High | Credentials | JSON Web Tokens (eyJ...eyJ...signature) | No - matches specific JWT structure |
| **AWS Key** | Critical | Credentials | AWS access keys (AKIA..., ASIA..., etc.) | No - matches specific AWS key prefixes |
| **GitHub Token** | Critical | Credentials | GitHub personal access tokens (ghp_..., gho_..., etc.) | No - matches specific GitHub token format |
| **Slack Token** | Critical | Credentials | Slack API tokens (xoxb-..., xoxp-..., etc.) | No - matches specific Slack token format |
| **Password** | Critical | Credentials | Password fields in logs | Yes - requires "password", "passwd", or "pwd" keyword |
| **Private Key** | Critical | Credentials | RSA/EC/DSA private keys | No - matches PEM format headers |
| **OAuth Token** | Critical | Credentials | OAuth access tokens (min 32 chars) | Yes - requires "oauth" or "access_token" keyword |
| **Connection String** | Critical | Credentials | Database connection strings with credentials | No - matches DB URL patterns with credentials |
| **IP Address** | Low | Network | IPv4 addresses | No - matches standard IPv4 format |

### Smart Masking

All sensitive values are automatically masked in reports to prevent accidental exposure:

| Type | Masking Strategy | Example |
|---|---|---|
| Email | Show first 2 chars + domain | `us***@example.com` |
| Phone | Show last 4 digits | `***-***-1234` |
| Credit Card | Show last 4 digits | `****-****-****-1234` |
| SSN | Show last 4 digits | `***-**-1234` |
| IP Address | Show first octet | `192.*.*.*` |
| Generic | Show first 4 + last 4 | `AKIA****ABCD` |

### CLI Options

```bash
# Run with sensitivity detection (default behavior)
python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key pod

# Skip sensitivity detection
python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --key pod --skip-sensitivity-check

# Only run sensitivity detection (skip other analysis)
python diagnostics_analyzer.py /path/to/diagnostics "ERROR" --sensitivity-only --output sensitivity_report.txt
```

### Example Output

```bash
# Full analysis with sensitivity detection
python diagnostics_analyzer.py ./sample_diagnostics "ERROR" --key pod --output full_report.txt

# Sensitivity-only scan
python diagnostics_analyzer.py ./sample_diagnostics "ERROR" --sensitivity-only --output sensitive_data_report.txt
```

### Use Cases

1. **Security Audit**: Identify sensitive data leaking into logs
2. **Compliance Check**: Verify no PII/credentials in log files before sharing
3. **Pre-Export Validation**: Scan logs before sending to external support
4. **Development Review**: Catch hardcoded credentials during development

### Best Practices

1. **Always run sensitivity scan** before sharing diagnostics with external parties
2. **Review CRITICAL findings immediately** - these indicate serious security issues
3. **Use `--sensitivity-only`** for quick security audits without full analysis
4. **Export reports** to document findings for security teams
5. **Remediate findings** by removing sensitive data from logs or using proper secret management

### False Positive Reduction

The patterns are designed to minimize false positives through:

1. **Context-Aware Matching**: Many patterns require specific keywords (e.g., "password", "api_key") to avoid matching random strings
2. **Minimum Length Requirements**: Tokens and keys must meet minimum length thresholds (typically 32+ characters)
3. **Format Validation**: Credit cards match specific issuer patterns (Visa, MasterCard, Amex, Discover)
4. **Specific Prefixes**: AWS keys, GitHub tokens, and Slack tokens match exact format specifications
5. **Word Boundaries**: Patterns use `\b` anchors to avoid partial matches within larger strings

**Example**: The pattern won't flag `tenant_id: "1772687196348347"` as a credit card because:
- It lacks the "card"/"cc"/"credit card" context keyword
- It doesn't match standard credit card issuer prefixes (4xxx, 5xxx, 3xxx, 6011)

---

## Root Cause Analysis Signals

The analyzer detects 20+ failure patterns across 9 categories:

| Category | Severity | Detected Patterns |
|---|---|---|
| **Out of Memory** | CRITICAL | `OutOfMemory`, `OOM`, `heap space`, `memory limit` |
| **Connection Error** | CRITICAL | `connection refused`, `ECONNREFUSED`, `connection reset` |
| **Circuit Breaker** | CRITICAL | `circuit breaker`, `circuit open` |
| **HTTP 5xx Error** | CRITICAL | `status=5xx`, `http_status=5xx` |
| **Database Error** | CRITICAL | `deadlock`, `SQLSTATE`, `ORA-`, `db error` |
| **Disk Full** | CRITICAL | `ENOSPC`, `no space left`, `disk full` |
| **Timeout** | HIGH | `timeout`, `timed out`, `read timeout` |
| **HTTP 4xx Error** | HIGH | `status=4xx`, `http_status=4xx` |
| **Auth Failure** | HIGH | `unauthorized`, `403`, `access denied` |
| **Payment Declined** | HIGH | `insufficient funds`, `decline_code` |
| **Retry Exhausted** | HIGH | `retry exhausted`, `max retries` |
| **Null/Type Error** | HIGH | `NullPointerException`, `AttributeError` |
| **Unhandled Exception** | HIGH | `exception`, `traceback`, `panic` |
| **Rate Limiting** | MEDIUM | `rate limit`, `throttl`, `429` |
| **High Latency** | MEDIUM | `elapsed_ms` ≥ 5000, `slow response` |
| **Validation Error** | MEDIUM | `validation fail`, `malformed` |
| **Resource Not Found** | MEDIUM | `not found`, `404` |
| **Generic Error** | MEDIUM | `ERROR`, `FATAL` log level |
| **Warning** | LOW | `WARN`, `WARNING` log level |

---

## Sample Test Data

The `sample_diagnostics/` folder contains realistic test data:

```
sample_diagnostics/
├── Healthcheck/
│   └── summary.html              # 10 pods (8 running, 1 CrashLoop, 1 Pending)
└── watsonx Orchestrate/
    └── hub/
        └── containerLogs/
            └── cpd-instance-1/
                ├── zen-watcher.log           # OutOfMemory errors
                ├── assistant-gateway.log     # ImagePullBackOff / Pending
                └── orchestrate-api.log       # Normal operations
```

### Test Commands

```bash
# Test OutOfMemory analysis
python diagnostics_analyzer.py ./sample_diagnostics "OutOfMemory" --key pod

# Test ERROR analysis across all pods
python diagnostics_analyzer.py ./sample_diagnostics "ERROR" --key pod

# Test with export
python diagnostics_analyzer.py ./sample_diagnostics "ERROR" --key pod --output test_report.txt
```

---

## Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1  Validate diagnostics folder structure                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 2  Parse Healthcheck/summary.html                         │
│          → Extract pod statuses                                 │
│          → Report non-running pods                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 3  Discover log files in containerLogs/cpd-instance-1/    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 4  Search for event string across all logs                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 5  Extract correlation values (e.g., pod names)           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 6  Collect context entries (all logs with those values)   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 7  Build event journey (merge + sort by timestamp)        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 8  Root Cause Analysis                                    │
│          → Scan journey against failure signals                 │
│          → Rank findings by severity                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### Issue: "Diagnostics folder not found"
**Solution**: Verify the path is correct and the folder contains the expected structure.

### Issue: "No log files found"
**Solution**: Check that logs are in `watsonx Orchestrate/hub/containerLogs/cpd-instance-1/` and have `.log` or `.txt` extensions.

### Issue: "No pod status information found in HTML"
**Solution**: The HTML structure may be different. The parser looks for table rows with pod names and status columns.

### Issue: "Cannot import from log_analyzer.py"
**Solution**: Ensure `log_analyzer.py` is in the same directory as `diagnostics_analyzer.py`.

---

## Comparison with Original Log Analyzer

| Feature | Original `log_analyzer.py` | Diagnostics `diagnostics_analyzer.py` |
|---|---|---|
| **Input** | Any log folder | watsonx Orchestrate diagnostics folder |
| **Pod Health Check** | ❌ | ✅ Parses HTML summary |
| **Log Analysis** | ✅ | ✅ (reuses same engine) |
| **Root Cause Analysis** | ✅ | ✅ (reuses same engine) |
| **Folder Structure** | Flexible | Expects specific structure |
| **Use Case** | General log analysis | watsonx Orchestrate diagnostics |

---

## Integration with Existing Tools

The diagnostics analyzer **reuses** all core functions from `log_analyzer.py`:
- `discover_log_files()` - File discovery
- `search_event()` - Event searching
- `extract_correlation_values()` - Correlation extraction
- `collect_context_entries()` - Context collection
- `merge_and_sort()` - Journey building
- `analyse_root_cause()` - RCA engine
- All 20 RCA signal patterns

This ensures consistency and maintainability across both tools.

---

## Export Format

When using `--output`, the report contains:

1. **Section 0: Sensitive Information Detection** (if performed)
   - Summary of findings by severity and category
   - Top 10 sensitive data findings with masked values
   - File locations and line numbers

2. **Section 1: Pod Health Check**
   - Total pods, running/non-running counts
   - List of non-running pods with status

3. **Section 2: Log Analysis Summary**
   - Statistics about log files scanned
   - Event search results
   - Correlation information

4. **Section 3: Event Journey**
   - Time-sorted log entries from all pods
   - `[EVENT]` and `[CTX]` badges

5. **Section 4: Root Cause Analysis**
   - Most likely root cause with severity
   - All detected signals ranked by severity
   - Evidence lines from the journey
   - Actionable suggestions per signal

6. **Section 5: Detailed Sensitive Information Findings** (if any found)
   - Complete list of all sensitive data findings
   - Grouped by severity and type
   - Full context for each finding

---

## Best Practices

1. **Always use correlation keys** - Helps track events across multiple pods
   - Common keys: `pod`, `transaction-id`, `request-id`, `user-id`

2. **Start broad, then narrow** - Search for `ERROR` first, then specific errors

3. **Check pod health first** - Non-running pods often explain log errors

4. **Export for sharing** - Use `--output` to save reports for team review

5. **Combine with kubectl** - Use alongside `kubectl describe pod` for full context

---

## Future Enhancements

Potential improvements:
- Support for multiple `cpd-instance-*` folders
- JSON/CSV export formats
- Integration with Prometheus metrics
- Automated remediation suggestions
- Web UI for interactive analysis
- Custom sensitive data patterns
- Integration with secret scanning tools
- Automated redaction of sensitive data

---

## License

Same as the parent log analyzer project.

---

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the sample test data for examples
3. Consult the main `README.md` for log analyzer basics
4. See `DIAGNOSTICS_ANALYZER_PLAN.md` for architecture details
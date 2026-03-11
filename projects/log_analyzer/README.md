# Log Analyzer

A Python command-line tool that searches multiple service log files for a specific event, correlates related log entries using a key (e.g. `transaction-id`), presents a unified time-sorted **event journey** across all log files, and automatically suggests the **root cause** of any detected failure.

---

## Features

| Feature | Description |
|---|---|
| **Multi-file search** | Recursively scans all log files in a folder |
| **Event search** | Finds every line containing a user-supplied event string |
| **Correlation** | Extracts values for a key (e.g. `transaction-id=TXN-001`) from hits and re-scans all files for those values |
| **Time-sorted journey** | Merges and deduplicates all related entries, sorted by timestamp |
| **Root Cause Analysis** | Scans the journey against 20 named failure signals and ranks findings by severity |
| **Flexible timestamps** | Supports ISO 8601, Apache/Nginx, US date, epoch-ms formats |
| **Color output** | Each source file gets a distinct color; event/context badges and severity badges highlight matches |
| **Export** | Optionally writes the journey **and** the RCA report to a plain-text file |
| **Interactive mode** | Prompts for all inputs when no CLI arguments are given |

---

## Requirements

- Python 3.8 or later (no third-party packages required)

---

## Usage

### Interactive mode (recommended for first-time use)

```bash
python log_analyzer.py
```

You will be prompted for:
1. Log folder path
2. Event string to search for
3. Correlation key (optional, e.g. `transaction-id`)
4. File extensions to scan (default: `.log,.txt`)
5. Case-sensitive matching (default: no)
6. Output file path (optional)
7. Skip root cause analysis (default: no)

---

### CLI mode

```
python log_analyzer.py <folder> <event> [options]
```

| Argument / Option | Description |
|---|---|
| `folder` | Path to the directory containing log files |
| `event` | Event string to search for (e.g. `PaymentFailed`) |
| `--key / -k` | Correlation key to extract context (e.g. `transaction-id`) |
| `--ext / -e` | File extensions to scan (default: `.log .txt`) |
| `--case-sensitive / -c` | Enable case-sensitive matching |
| `--output / -o` | Export the journey and RCA report to a plain-text file |
| `--no-color` | Disable ANSI color output |
| `--skip-rca` | Skip the root cause analysis step |

---

### Examples

```bash
# Search for "PaymentFailed", trace by transaction-id, run RCA
python log_analyzer.py ./sample_logs "PaymentFailed" --key transaction-id

# Search for ERROR, trace by request-id, export result (journey + RCA)
python log_analyzer.py /var/logs "ERROR" -k request-id -o journey.txt

# Case-sensitive search, custom extensions, skip RCA
python log_analyzer.py ./logs "NullPointerException" -k session-id -e .log .out -c --skip-rca

# Interactive mode
python log_analyzer.py
```

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1  Discover all log files in the folder (recursive)       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 2  Search every file for the event string                 │
│          → collect matching lines  (EVENT hits)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 3  Extract correlation values from EVENT hits             │
│          e.g.  transaction-id=TXN-20240315-001                  │
│          → values: ["TXN-20240315-001"]                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 4  Re-scan all files for lines containing those values    │
│          → collect context lines  (CTX entries)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 5  Merge EVENT hits + CTX entries, deduplicate,           │
│          sort by timestamp  →  EVENT JOURNEY                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  STEP 6  Scan journey against failure signal catalogue          │
│          → rank findings by severity  →  ROOT CAUSE ANALYSIS   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Root Cause Analysis

After building the event journey, the analyzer scans every log entry against a catalogue of **20 named failure signals** grouped into 9 categories. Findings are ranked by severity and the most likely root cause is highlighted at the top.

### Signal Catalogue

| Category | Severity | Detected by |
|---|---|---|
| Connection Error / Circuit Breaker | CRITICAL | `connection refused`, `ECONNREFUSED`, `circuit breaker` |
| HTTP 5xx Error | CRITICAL | `status=5xx`, `http_status=5xx` |
| Database Error / Deadlock | CRITICAL | `deadlock`, `SQLSTATE`, `ORA-`, `db error` |
| Out of Memory | CRITICAL | `OOM`, `heap space`, `out of memory` |
| Disk Full | CRITICAL | `ENOSPC`, `no space left`, `disk full` |
| HTTP 4xx Error | HIGH | `status=4xx`, `http_status=4xx` |
| Auth Failure | HIGH | `unauthorized`, `403`, `access denied` |
| Payment Declined | HIGH | `insufficient funds`, `decline_code`, `bank declined` |
| Retry Exhausted | HIGH | `retry exhausted`, `max retries`, `giving up` |
| Null / Type Error | HIGH | `NullPointerException`, `AttributeError`, `TypeError` |
| Unhandled Exception | HIGH | `exception`, `traceback`, `panic`, `crash` |
| Rate Limiting / Throttling | MEDIUM | `rate limit`, `throttl`, `429` |
| High Latency | MEDIUM | `elapsed_ms` ≥ 5000, `slow response` |
| Validation / Bad Input | MEDIUM | `validation fail`, `malformed`, `bad request` |
| Resource Not Found | MEDIUM | `not found`, `404`, `record not found` |
| Timeout | HIGH | `timeout`, `timed out`, `read timeout` |
| Generic Error | MEDIUM | `ERROR`, `FATAL`, `CRITICAL` log level |
| Warning | LOW | `WARN`, `WARNING` log level |

### RCA Output Format

```
════════════════════════════════════════════════════════════════════════════════
  ROOT CAUSE ANALYSIS
════════════════════════════════════════════════════════════════════════════════

  Most Likely Root Cause:
  ────────────────────────────────────────────────────────────
  Category  : Payment Declined
  Severity  : HIGH
  Summary   : A payment was declined by the bank or payment processor.
  Suggestion: The decline is typically a business-level event; surface a clear
              error to the user and offer retry or alternative payment.

  Timeline: journey spans 6.4 seconds

  All Detected Signals:
  ────────────────────────────────────────────────────────────
   1. [CRITICAL] HTTP 5xx Error  –  An HTTP 5xx server-side error was returned.
   2. [HIGH]     Payment Declined  –  A payment was declined by the bank.
   3. [MEDIUM]   High Latency  –  Unusually high response latency observed (≥5 s).
   ...

  Evidence Lines:
  ────────────────────────────────────────────────────────────
  [CRITICAL] service-gateway.log:L8   ERROR [gateway] PaymentFailed ... status=500
  [HIGH]     service-payment.log:L6   ERROR [payment-svc] PaymentFailed bank declined ...
  [MEDIUM]   service-payment.log:L5   WARN  [payment-svc] Bank API slow response elapsed_ms=3650
```

---

## Sample Log Files

The `sample_logs/` directory contains four realistic microservice logs:

| File | Service |
|---|---|
| `service-gateway.log` | API Gateway – routes requests, detects slow responses |
| `service-payment.log` | Payment Service – card validation, bank authorization |
| `service-notification.log` | Notification Service – email delivery |
| `service-audit.log` | Audit Service – compliance trail (uses comma-ms timestamps) |

### Quick demo

```bash
cd log_analyzer
python3 log_analyzer.py ./sample_logs "PaymentFailed" --key transaction-id
```

Expected output:
- **23 log entries** from all four services, sorted by timestamp
- **5 RCA signals** detected: HTTP 5xx (CRITICAL), Payment Declined (HIGH), HTTP 4xx (HIGH), High Latency (MEDIUM), Generic Error (MEDIUM)
- **Most likely root cause**: HTTP 5xx Error with actionable suggestion

---

## Output Format

### Journey

```
▶ FILE: service-gateway.log
────────────────────────────────────────────────────────────────────────────────
  [2024-03-15T08:01:10.456Z] L   3 [CTX]   Incoming request POST /api/payment transaction-id=TXN-20240315-001
  [2024-03-15T08:01:16.001Z] L   8 [EVENT] [CTX]  ERROR PaymentFailed upstream error status=500
```

### Badges

| Badge | Meaning |
|---|---|
| `[EVENT]` | Line directly matched the event search string |
| `[CTX]` | Line was pulled in via the correlation key value |
| `[CRITICAL]` / `[HIGH]` / `[MEDIUM]` / `[LOW]` | RCA severity of the matched signal |

### Export file

When `--output journey.txt` is specified, the file contains:
1. The full time-sorted event journey
2. The complete RCA report appended at the end (with per-signal suggestions and all evidence lines)
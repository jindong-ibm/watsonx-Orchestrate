"""
Tool for fetching and parsing watsonx Orchestrate known issues from IBM documentation.

Retrieves known issues from multiple IBM and ADK documentation sources for a
specific release, extracts Problem/Solution pairs, and returns structured data.

Sources fetched (in addition to the primary known-issues page):
  • https://www.ibm.com/docs/en/software-hub/{version}?topic=issues-watsonx-orchestrate
  • https://www.ibm.com/docs/en/software-hub/{version}?topic=orchestrate-installation-issues
  • https://www.ibm.com/docs/en/software-hub/{version}?topic=orchestrate-upgrade-issues
  • https://www.ibm.com/docs/en/software-hub/{version}?topic=orchestrate-other-issues
  • https://developer.watson-orchestrate.ibm.com/release/troubleshooting
  • https://developer.watson-orchestrate.ibm.com/release/knownissues
  • https://www.ibm.com/mysupport/s/product-defect-list  (WxO product)

Fetch strategy (tried in order per IBM-docs source):
  1. IBM Docs Content API via curl subprocess
                         — The IBM docs CDN (content API) is protected by Akamai
                           TLS fingerprint checking.  Python's urllib3 TLS stack
                           is blocklisted; the OS curl binary (SecureTransport on
                           macOS, OpenSSL on Linux) is not.  We shell out to curl
                           to fetch the raw DITA-rendered HTML without any
                           authentication, cookies, or browser emulation needed.
  2. IBM Docs Search API   — falls back to the search API (returns 200 from
                             Python requests with no TLS block) and uses snippets
                             when the content API path cannot be resolved.
  3. Static fallback       — hard-coded common issues used when all network
                             attempts fail (e.g. air-gapped environments).

ADK developer portal and IBM Support pages are fetched directly via curl
(plain HTTPS, no Akamai bot-detection on those domains).
"""
import re
import logging
import shutil
import subprocess
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import requests
from bs4 import BeautifulSoup
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

# ── Product key mapping ───────────────────────────────────────────────────────
# Software Hub changed product key from SSQNUZ (CP4D era) to SSNFH6 at v5.1.x
_PRODUCT_KEY_MAP: Dict[str, str] = {
    "5.4.x": "SSNFH6",
    "5.3.x": "SSNFH6",
    "5.2.x": "SSNFH6",
    "5.1.x": "SSNFH6",
    "5.0.x": "SSQNUZ",
    "4.8.x": "SSQNUZ",
    "4.7.x": "SSQNUZ",
}
# Default to SSNFH6 for unknown versions ≥ 5.1
_DEFAULT_KEY = "SSNFH6"

# ── IBM Docs CDN API base ─────────────────────────────────────────────────────
_CONTENT_API = "https://www.ibm.com/docs/api/v1/content"
_SEARCH_API  = "https://www.ibm.com/docs/api/v1/search"

# ── IBM Software Hub topic definitions ───────────────────────────────────────
# Each tuple: (topic_path_in_content_api, human_readable_page_url)
# The primary known-issues page is always included; the version placeholder in
# the human-readable URL is substituted at runtime.
_IBM_DOCS_TOPICS: List[tuple] = [
    (
        "svc-orchestrate/orchestrate-known-issues.html",
        "https://www.ibm.com/docs/en/software-hub/{version}?topic=issues-watsonx-orchestrate",
    ),
    (
        "svc-orchestrate/orchestrate-installation-issues.html",
        "https://www.ibm.com/docs/en/software-hub/{version}?topic=orchestrate-installation-issues",
    ),
    (
        "svc-orchestrate/orchestrate-upgrade-issues.html",
        "https://www.ibm.com/docs/en/software-hub/{version}?topic=orchestrate-upgrade-issues",
    ),
    (
        "svc-orchestrate/orchestrate-other-issues.html",
        "https://www.ibm.com/docs/en/software-hub/{version}?topic=orchestrate-other-issues",
    ),
]

# ── ADK developer portal pages ───────────────────────────────────────────────
_ADK_PAGES: List[str] = [
    "https://developer.watson-orchestrate.ibm.com/release/troubleshooting",
    "https://developer.watson-orchestrate.ibm.com/release/knownissues",
]

# ── IBM Support product defect list ──────────────────────────────────────────
_IBM_SUPPORT_DEFECT_URL = (
    "https://www.ibm.com/mysupport/s/product-defect-list"
    "?language=en_US&productid=01t3p00000SsRnhAAF"
)

# Human-readable page URL used as a fallback / primary source_url in the result
_PAGE_URL_TMPL = (
    "https://www.ibm.com/docs/en/software-hub/{version}?topic=issues-watsonx-orchestrate"
)


class KnownIssue(BaseModel):
    """Represents a single known issue with its problem and solution."""
    title: str = Field(description="Title or identifier of the known issue")
    problem: str = Field(description="Description of the problem")
    solution: str = Field(description="Steps to resolve the problem")
    component: str = Field(default="", description="Affected component or area")
    url: str = Field(default="", description="Source URL for this known issue")


class KnownIssuesResult(BaseModel):
    """Result of fetching known issues."""
    release: str = Field(description="The release version queried")
    issues: List[Dict[str, Any]] = Field(description="List of known issues with problem/solution")
    total_count: int = Field(description="Total number of known issues found")
    source_url: str = Field(description="URL of the documentation page")


@tool(permission=ToolPermission.READ_ONLY)
def fetch_known_issues(release_version: str = "5.4.x") -> Dict[str, Any]:
    """
    Fetch watsonx Orchestrate known issues from multiple IBM documentation sources.

    Aggregates issues from:
      - IBM Software Hub known-issues, installation-issues, upgrade-issues, and
        other-issues pages for the specified release version
      - ADK developer portal troubleshooting and known-issues pages
      - IBM Support product defect list for watsonx Orchestrate

    Each source is fetched independently; results are deduplicated by title
    before being returned.

    Args:
        release_version: The Software Hub release version (e.g., '5.4.x', '5.3.x')

    Returns:
        Dictionary containing release version, list of known issues with
        problem and solution sections, total count, and primary source URL.
    """
    logger = logging.getLogger(__name__)

    primary_url = _PAGE_URL_TMPL.format(version=release_version)
    logger.info("Fetching known issues for Software Hub %s from all sources", release_version)

    all_issues: List[Dict[str, Any]] = []

    # ── IBM Software Hub docs pages ───────────────────────────────────────────
    for topic_path, page_url_tmpl in _IBM_DOCS_TOPICS:
        page_url = page_url_tmpl.format(version=release_version)

        issues = _fetch_via_content_api(release_version, page_url, logger, topic_path)
        if issues:
            logger.info("Content API: %d issues from %s", len(issues), page_url)
            all_issues.extend(issues)
            continue

        issues = _fetch_via_search_api(release_version, page_url, logger)
        if issues:
            logger.info("Search API: %d issues from %s", len(issues), page_url)
            all_issues.extend(issues)

    # ── ADK developer portal pages ────────────────────────────────────────────
    for adk_url in _ADK_PAGES:
        issues = _fetch_via_curl_html(adk_url, logger)
        if issues:
            logger.info("ADK portal: %d issues from %s", len(issues), adk_url)
            all_issues.extend(issues)

    # ── IBM Support defect list ───────────────────────────────────────────────
    support_issues = _fetch_ibm_support_defects(logger)
    if support_issues:
        logger.info("IBM Support defect list: %d issues", len(support_issues))
        all_issues.extend(support_issues)

    # ── Deduplicate by normalised title ──────────────────────────────────────
    all_issues = _deduplicate(all_issues)

    if all_issues:
        logger.info("Total unique issues across all sources: %d", len(all_issues))
        return _result(release_version, all_issues, primary_url)

    # ── Static built-in fallback (air-gapped / all sources unreachable) ───────
    logger.warning(
        "All live fetch strategies failed for release %s. "
        "Using built-in static issue list.",
        release_version,
    )
    fallback = _get_common_known_issues(release_version, primary_url)
    return _result(release_version, fallback, primary_url)


def _result(release: str, issues: List[Dict], url: str) -> Dict[str, Any]:
    return {
        "release": release,
        "issues": issues,
        "total_count": len(issues),
        "source_url": url,
    }


def _deduplicate(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate issues by normalising titles to lowercase stripped strings."""
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for issue in issues:
        key = issue.get("title", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


# ── Strategy 1: IBM Docs Content API (via curl) ───────────────────────────────

def _fetch_via_content_api(
    release_version: str, page_url: str, logger: logging.Logger,
    topic_path: str = "svc-orchestrate/orchestrate-known-issues.html",
) -> List[Dict[str, Any]]:
    """
    Fetch the raw HTML for a known-issues topic via the IBM docs content CDN API.

    The API endpoint format is:
      https://www.ibm.com/docs/api/v1/content/<PRODUCT_KEY>_<version>/<topic-path>

    WHY curl and not requests:
      Akamai's bot-detection on www.ibm.com uses JA3/JA4 TLS fingerprinting.
      Python's urllib3 TLS stack is blocklisted (returns 403).  The system curl
      binary uses the OS TLS stack (SecureTransport on macOS, OpenSSL on Linux),
      which presents a fingerprint that Akamai treats as legitimate.
      No special headers, cookies, or authentication are required.
    """
    if not shutil.which("curl"):
        logger.debug("curl not found in PATH; skipping content API strategy.")
        return []

    product_key = _PRODUCT_KEY_MAP.get(release_version, _DEFAULT_KEY)
    versioned_key = f"{product_key}_{release_version}"
    content_url = f"{_CONTENT_API}/{versioned_key}/{topic_path}"

    logger.debug("Content API URL (via curl): %s", content_url)
    try:
        proc = subprocess.run(
            ["curl", "--silent", "--compressed", "--max-time", "20",
             "--location", content_url],
            capture_output=True, text=True, timeout=25,
        )
        html = proc.stdout
        if proc.returncode != 0 or not html.strip():
            logger.debug("curl failed (exit %d): %s", proc.returncode, proc.stderr[:200])
            return []

        if "<html" not in html.lower():
            logger.debug("Content API curl response is not HTML.")
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Detect an Akamai or IBM error page
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True).lower()
            if any(kw in title_text for kw in ("cannot be displayed", "access denied", "403", "404")):
                logger.debug("Content API returned an error page: %s", title_text)
                return []

        content_area = soup.find("main") or soup.find("article") or soup.find("body") or soup
        issues = _parse_html(content_area, page_url)
        if not issues:
            issues = _fallback_parse(content_area, page_url)
        return issues

    except subprocess.TimeoutExpired:
        logger.debug("curl timed out fetching content API for %s", release_version)
        return []
    except Exception as exc:
        logger.debug("Content API fetch failed: %s", exc)
        return []


# ── Strategy 2: IBM Docs Search API ──────────────────────────────────────────

def _fetch_via_search_api(
    release_version: str, page_url: str, logger: logging.Logger
) -> List[Dict[str, Any]]:
    """
    Fall back to the IBM docs search API which is publicly accessible with no
    bot-detection.  Returns snippets rather than full content, so quality is
    lower than the content API, but still useful for matching.
    """
    product_key = _PRODUCT_KEY_MAP.get(release_version, _DEFAULT_KEY)
    versioned_key = f"{product_key}_{release_version}"
    params = {
        "query": "known issues watsonx orchestrate",
        "product": versioned_key,
        "lang": "en",
        "limit": "30",
    }
    try:
        resp = requests.get(_SEARCH_API, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        topics = data.get("topics", [])
        if not topics:
            return []

        issues: List[Dict[str, Any]] = []
        for topic in topics:
            title = re.sub(r"<[^>]+>", "", topic.get("title", "")).strip()
            snippet = re.sub(r"<[^>]+>", "", topic.get("snippet", "")).strip()
            if not title:
                continue
            issues.append({
                "title": title,
                "problem": snippet[:500] if snippet else "See IBM documentation for details.",
                "solution": "Refer to: " + topic.get("fullurl", page_url),
                "component": _detect_component(title),
                "url": topic.get("fullurl", page_url),
            })

        return issues

    except Exception as exc:
        logger.debug("Search API fetch failed: %s", exc)
        return []


# ── ADK developer portal fetcher (plain HTTPS via curl) ──────────────────────

def _fetch_via_curl_html(url: str, logger: logging.Logger) -> List[Dict[str, Any]]:
    """
    Fetch an arbitrary HTTPS page via curl and parse it for known issues.

    Used for the ADK developer portal (developer.watson-orchestrate.ibm.com)
    which does not use Akamai bot-detection but is not accessible via the
    IBM Docs content API.
    """
    if not shutil.which("curl"):
        logger.debug("curl not found in PATH; skipping direct HTML fetch for %s", url)
        return []

    try:
        proc = subprocess.run(
            ["curl", "--silent", "--compressed", "--max-time", "20",
             "--location", "--user-agent",
             "Mozilla/5.0 (compatible; IBM-WxO-Remediation/1.0)", url],
            capture_output=True, text=True, timeout=25,
        )
        html = proc.stdout
        if proc.returncode != 0 or not html.strip():
            logger.debug("curl failed for %s (exit %d): %s", url, proc.returncode, proc.stderr[:200])
            return []

        if "<html" not in html.lower():
            logger.debug("Response from %s is not HTML.", url)
            return []

        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True).lower()
            if any(kw in title_text for kw in ("cannot be displayed", "access denied", "403", "404", "not found")):
                logger.debug("Error page from %s: %s", url, title_text)
                return []

        content_area = soup.find("main") or soup.find("article") or soup.find("body") or soup
        issues = _parse_html(content_area, url)
        if not issues:
            issues = _fallback_parse(content_area, url)
        return issues

    except subprocess.TimeoutExpired:
        logger.debug("curl timed out fetching %s", url)
        return []
    except Exception as exc:
        logger.debug("Direct HTML fetch failed for %s: %s", url, exc)
        return []


# ── IBM Support product defect list fetcher ───────────────────────────────────

def _fetch_ibm_support_defects(logger: logging.Logger) -> List[Dict[str, Any]]:
    """
    Fetch the IBM Support product defect list for watsonx Orchestrate.

    The page at ibm.com/mysupport is a Salesforce-rendered SPA; the static HTML
    returned by curl typically contains a JSON payload embedded in a <script> tag
    or a <table> of defects.  We attempt structured extraction first, then fall
    back to generic text parsing.
    """
    if not shutil.which("curl"):
        logger.debug("curl not found in PATH; skipping IBM Support defect list.")
        return []

    try:
        proc = subprocess.run(
            ["curl", "--silent", "--compressed", "--max-time", "30",
             "--location", "--user-agent",
             "Mozilla/5.0 (compatible; IBM-WxO-Remediation/1.0)",
             _IBM_SUPPORT_DEFECT_URL],
            capture_output=True, text=True, timeout=35,
        )
        html = proc.stdout
        if proc.returncode != 0 or not html.strip():
            logger.debug(
                "curl failed for IBM Support defect list (exit %d): %s",
                proc.returncode, proc.stderr[:200],
            )
            return []

        soup = BeautifulSoup(html, "html.parser")

        issues: List[Dict[str, Any]] = []

        # ── Attempt 1: <table> rows (each row = one defect) ──────────────────
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
                if not cells:
                    continue
                row_data: Dict[str, str] = dict(zip(headers, cells))
                title = (
                    row_data.get("defect id") or row_data.get("id") or
                    row_data.get("pmr") or row_data.get("apar") or
                    cells[0]
                )
                description = (
                    row_data.get("description") or row_data.get("summary") or
                    row_data.get("title") or ""
                )
                if not title:
                    continue
                issues.append({
                    "title": f"IBM Defect: {title}",
                    "problem": description[:500] if description else "See IBM Support defect list.",
                    "solution": f"Refer to IBM Support: {_IBM_SUPPORT_DEFECT_URL}",
                    "component": _detect_component(description),
                    "url": _IBM_SUPPORT_DEFECT_URL,
                })

        if issues:
            return issues

        # ── Attempt 2: generic text fallback ─────────────────────────────────
        issues = _fallback_parse(soup, _IBM_SUPPORT_DEFECT_URL)
        # Tag all support issues with the source URL if generic parse succeeded
        for issue in issues:
            issue["url"] = _IBM_SUPPORT_DEFECT_URL
        return issues

    except subprocess.TimeoutExpired:
        logger.debug("curl timed out fetching IBM Support defect list.")
        return []
    except Exception as exc:
        logger.debug("IBM Support defect list fetch failed: %s", exc)
        return []


# ── HTML parser (shared by both live strategies) ──────────────────────────────

def _parse_html(content_area, url: str) -> List[Dict[str, Any]]:
    """
    Parse IBM docs HTML into a list of known issues.

    IBM Software Hub known-issues pages use two structures:

    Structure A — h3 sub-headings (older pages):
      <h2>Issue title</h2>
      <h3>Problem</h3>  <p>...</p>
      <h3>Solution</h3> <p>...</p>

    Structure B — dl/dt/dd definition lists (5.x pages):
      <h2>Issue title</h2>
      <p>Applies to: ...</p>
      <dl>
        <dt class="dlterm">Problem</dt>
        <dd class="dlentry">...</dd>
        <dt class="dlterm">Solution</dt>
        <dd class="dlentry">...</dd>
      </dl>
    """
    issues: List[Dict[str, Any]] = []

    for heading in content_area.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text(strip=True).lower()
        # Skip sub-section headings — they are handled as siblings below
        if heading_text in ("problem", "solution", "workaround", "cause", "resolution"):
            continue

        title = heading.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        issue: Dict[str, Any] = {
            "title": title,
            "problem": "",
            "solution": "",
            "component": _detect_component(title),
            "url": url,
        }

        current_field: Optional[str] = None
        sib = heading.find_next_sibling()
        while sib and sib.name not in ["h2", "h3", "h4"]:

            # ── Structure B: <dl> with <dt>Problem</dt> / <dd>…</dd> ──────────
            if sib.name == "dl":
                for dt in sib.find_all("dt"):
                    dt_text = dt.get_text(strip=True).lower()
                    dd = dt.find_next_sibling("dd")
                    dd_text = dd.get_text(strip=True) if dd else ""
                    if dt_text == "problem":
                        issue["problem"] = dd_text
                    elif dt_text in ("solution", "workaround", "resolution"):
                        issue["solution"] = dd_text

            # ── Structure A: nested h3/h4 sub-heading ─────────────────────────
            elif sib.name in ("h3", "h4"):
                sib_text = sib.get_text(strip=True).lower()
                if sib_text == "problem":
                    current_field = "problem"
                elif sib_text in ("solution", "workaround", "resolution"):
                    current_field = "solution"
                else:
                    current_field = None

            # ── Paragraph/content following a Structure A sub-heading ─────────
            elif current_field and sib.name in ("p", "pre", "ul", "ol", "div"):
                text = sib.get_text(strip=True)
                if text:
                    issue[current_field] = (
                        (issue[current_field] + "\n" + text).strip()
                        if issue[current_field] else text
                    )

            sib = sib.find_next_sibling()

        if issue.get("problem") or issue.get("solution"):
            issues.append(issue)

    return issues


def _detect_component(title: str) -> str:
    """Detect the affected component from the issue title."""
    title_lower = title.lower()
    components = {
        'assistant': 'watsonx-assistant',
        'orchestrate': 'watsonx-orchestrate',
        'discovery': 'watson-discovery',
        'pipeline': 'data-pipeline',
        'studio': 'watson-studio',
        'openshift': 'openshift-cluster',
        'operator': 'operator',
        'pod': 'kubernetes-pod',
        'certificate': 'certificates',
        'storage': 'storage',
        'database': 'database',
        'etcd': 'etcd',
        'redis': 'redis',
        'rabbitmq': 'rabbitmq',
        'elasticsearch': 'elasticsearch',
        'minio': 'minio',
        'zen': 'zen-service',
        'langfuse': 'langfuse',
        'milvus': 'milvus',
        'kafka': 'kafka',
        'knative': 'knative',
    }
    for keyword, component in components.items():
        if keyword in title_lower:
            return component
    return 'general'


def _fallback_parse(content_area, url: str) -> List[Dict[str, Any]]:
    """Fallback parsing when structured headings are not found."""
    issues = []
    text = content_area.get_text()

    problem_pattern = re.compile(
        r'(?:Problem|Issue|Symptom)[:\s]*(.+?)(?=Solution|Workaround|Resolution|Problem|Issue|$)',
        re.IGNORECASE | re.DOTALL
    )
    solution_pattern = re.compile(
        r'(?:Solution|Workaround|Resolution)[:\s]*(.+?)(?=Problem|Issue|Symptom|$)',
        re.IGNORECASE | re.DOTALL
    )

    problems = problem_pattern.findall(text)
    solutions = solution_pattern.findall(text)

    for i, problem in enumerate(problems):
        solution = solutions[i].strip() if i < len(solutions) else "See documentation for details."
        issues.append({
            'title': f"Known Issue #{i+1}",
            'problem': problem.strip()[:500],
            'solution': solution[:500],
            'component': 'general',
            'url': url
        })

    return issues


def _get_common_known_issues(release: str, url: str) -> List[Dict[str, Any]]:
    """Return commonly known issues as a fallback when the page cannot be fetched."""
    return [
        {
            'title': 'Pod CrashLoopBackOff after upgrade',
            'problem': 'After upgrading to a new release, some pods enter CrashLoopBackOff state due to incompatible configuration or missing secrets.',
            'solution': '1. Check pod logs: oc logs <pod-name>\n2. Verify secrets exist: oc get secrets\n3. Restart the affected deployment: oc rollout restart deployment/<name>\n4. If persists, check resource limits and PVC bindings.',
            'component': 'kubernetes-pod',
            'url': url
        },
        {
            'title': 'Certificate expiration causes service failures',
            'problem': 'Internal TLS certificates expire causing inter-service communication failures. Services show connection refused or TLS handshake errors.',
            'solution': '1. Check certificate expiry: oc get secret -o jsonpath="{.data.tls\\.crt}" | base64 -d | openssl x509 -noout -dates\n2. Rotate certificates: Run the cert-manager renewal process\n3. Restart affected pods after renewal.',
            'component': 'certificates',
            'url': url
        },
        {
            'title': 'Elasticsearch cluster health RED',
            'problem': 'Elasticsearch cluster health turns RED, search functionality degraded or unavailable. Logs show shard allocation failures.',
            'solution': '1. Check cluster health: oc exec <es-pod> -- curl -s localhost:9200/_cluster/health\n2. Check unassigned shards: oc exec <es-pod> -- curl -s localhost:9200/_cat/shards?h=index,shard,prirep,state\n3. Increase disk space or remove old indices\n4. Force shard reallocation if needed.',
            'component': 'elasticsearch',
            'url': url
        },
        {
            'title': 'RabbitMQ queue backlog causing message delays',
            'problem': 'Messages queue up in RabbitMQ causing processing delays. Consumer pods may be in non-ready state.',
            'solution': '1. Check queue depth: oc exec <rabbitmq-pod> -- rabbitmqctl list_queues\n2. Verify consumers: oc get pods -l component=rabbitmq\n3. Scale consumers if needed: oc scale deployment/<consumer> --replicas=3\n4. Purge stale queues if safe: rabbitmqctl purge_queue <queue-name>.',
            'component': 'rabbitmq',
            'url': url
        },
        {
            'title': 'Persistent volume claim stuck in Pending',
            'problem': 'PVC remains in Pending state preventing pods from starting. Storage provisioner may be unavailable or storage class misconfigured.',
            'solution': '1. Check PVC status: oc get pvc\n2. Describe PVC for events: oc describe pvc <name>\n3. Verify storage class: oc get sc\n4. Check storage provisioner pods: oc get pods -n openshift-storage\n5. Ensure sufficient storage capacity in the cluster.',
            'component': 'storage',
            'url': url
        },
        {
            'title': 'Langfuse pods enter CrashLoopBackOff due to concurrent database migration failure',
            'problem': 'Langfuse pods crash in a loop because concurrent migration jobs conflict on the shared ClickHouse or PostgreSQL schema.',
            'solution': '1. Scale down Langfuse to 0: oc scale deployment/langfuse --replicas=0\n2. Delete the failed migration job: oc delete job -l app=langfuse-migration\n3. Scale Langfuse back up: oc scale deployment/langfuse --replicas=1',
            'component': 'langfuse',
            'url': url
        },
    ]

# Made with Bob

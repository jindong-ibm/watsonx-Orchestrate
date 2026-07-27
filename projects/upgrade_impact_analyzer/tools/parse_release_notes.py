"""
Tool 1: Parse wxO Release Notes and ADK Changelog

Accepts release notes text (pasted from the wxO changelog or ADK GitHub releases page)
for the target version and the current installed version, then extracts:
  - Breaking changes
  - Deprecated APIs / parameters
  - New required configuration fields
  - Recommended migration steps mentioned in the notes
Returns a structured JSON summary for downstream tools.
"""

import re
import json
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# ─────────────────────────────────────────────────────────────────────────────
# Signal patterns for classifying individual changelog bullets
# ─────────────────────────────────────────────────────────────────────────────
_BREAKING_PATTERNS = [
    r'\b(breaking[\s_-]?change|breaking[\s_-]?update|incompatible|removed|renamed|dropped|no[\s_-]?longer[\s_-]?support)\b',
    r'\b(migration[\s_-]?required|must[\s_-]?update|must[\s_-]?migrate|requires[\s_-]?manual)\b',
    r'\b(regression|behavior[\s_-]?change|changed[\s_-]?behavior|different[\s_-]?behavior)\b',
]

_DEPRECATION_PATTERNS = [
    r'\b(deprecat|is[\s_-]?deprecated|marked[\s_-]?deprecated|will[\s_-]?be[\s_-]?removed|replaced[\s_-]?by|use[\s_-]?\S+[\s_-]?instead)\b',
    r'\b(legacy|obsolete|end[\s_-]?of[\s_-]?life|eol)\b',
]

_MIGRATION_PATTERNS = [
    r'\b(migrat|migrate|update[\s_-]?your|upgrade[\s_-]?to|change[\s_-]?your|switch[\s_-]?to|replace[\s_-]?with|refactor)\b',
    r'\b(action[\s_-]?required|manual[\s_-]?step|you[\s_-]?must|you[\s_-]?need[\s_-]?to)\b',
]

_NEW_REQUIRED_PATTERNS = [
    r'\b(new[\s_-]?required|now[\s_-]?required|mandatory[\s_-]?field|must[\s_-]?set|must[\s_-]?provide|required[\s_-]?parameter)\b',
    r'\b(new[\s_-]?parameter|new[\s_-]?field|new[\s_-]?flag|added[\s_-]?parameter)\b',
]


def _classify_bullet(text: str) -> list[str]:
    """Return list of classification tags for a single bullet / paragraph."""
    tags = []
    lower_text = text.lower()
    for pattern in _BREAKING_PATTERNS:
        if re.search(pattern, lower_text, re.IGNORECASE):
            tags.append("breaking_change")
            break
    for pattern in _DEPRECATION_PATTERNS:
        if re.search(pattern, lower_text, re.IGNORECASE):
            tags.append("deprecation")
            break
    for pattern in _MIGRATION_PATTERNS:
        if re.search(pattern, lower_text, re.IGNORECASE):
            tags.append("migration_step")
            break
    for pattern in _NEW_REQUIRED_PATTERNS:
        if re.search(pattern, lower_text, re.IGNORECASE):
            tags.append("new_required_config")
            break
    return tags


def _extract_bullets(text: str) -> list[str]:
    """Split release notes into individual bullet / line items."""
    bullets = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("*-•→").strip()
        if stripped:
            bullets.append(stripped)
    return bullets


def _version_tuple(version_str: str) -> tuple:
    """Convert version string like '1.13.0' to comparable tuple."""
    parts = re.findall(r'\d+', version_str)
    return tuple(int(p) for p in parts)


@tool(
    name="parse_release_notes",
    description=(
        "Parse wxO release notes or ADK changelog text for a target upgrade version. "
        "Classifies each entry as a breaking change, deprecation, migration step, or "
        "new required configuration. Returns a structured JSON summary of upgrade risks "
        "for use by the Upgrade Impact Analyzer. "
        "Accepts raw pasted changelog text — no file upload required."
    ),
    permission=ToolPermission.READ_ONLY,
)
def parse_release_notes(
    changelog_text: str,
    current_version: str,
    target_version: str,
) -> str:
    """
    Parse watsonx Orchestrate release notes or ADK changelog and classify entries.

    Provide the full text of the changelog (e.g. pasted from
    https://developer.watson-orchestrate.ibm.com/release/release or the GitHub
    ibm-watsonx-orchestrate-adk releases page).  The tool scans every bullet
    and paragraph for keywords indicating breaking changes, deprecations,
    migration steps, and new required configuration fields.

    Args:
        changelog_text: Full text of the wxO or ADK changelog/release notes
                        for all versions between current_version and target_version.
        current_version: The currently deployed ADK/wxO version (e.g. "1.10.0").
        target_version:  The version being upgraded to (e.g. "1.15.0").

    Returns:
        JSON string containing:
        - current_version: as provided
        - target_version: as provided
        - version_gap: integer number of minor versions spanned
        - total_bullets_scanned: total changelog lines examined
        - breaking_changes: list of items classified as breaking changes
        - deprecations: list of deprecated APIs / parameters found
        - migration_steps: list of migration actions mentioned
        - new_required_configs: list of new mandatory configuration fields
        - uncategorised_highlights: bullets with no classification (FYI items)
        - risk_level: "LOW", "MEDIUM", or "HIGH" based on count of breaking changes
        - summary: plain-text human-readable summary paragraph
        - error: present only if parsing failed
    """
    if not changelog_text or not changelog_text.strip():
        return json.dumps({
            "error": "changelog_text is empty. Please paste the wxO or ADK release notes text.",
            "breaking_changes": [],
            "deprecations": [],
            "migration_steps": [],
            "new_required_configs": [],
        })

    try:
        cur_ver = _version_tuple(current_version)
        tgt_ver = _version_tuple(target_version)
    except (ValueError, IndexError):
        return json.dumps({
            "error": (
                f"Could not parse version strings: current='{current_version}' "
                f"target='{target_version}'. Use format like '1.10.0'."
            )
        })

    if tgt_ver <= cur_ver:
        return json.dumps({
            "error": (
                f"target_version '{target_version}' must be greater than "
                f"current_version '{current_version}'."
            )
        })

    # Version gap (minor versions)
    version_gap = tgt_ver[1] - cur_ver[1] if len(tgt_ver) >= 2 and len(cur_ver) >= 2 else 0

    bullets = _extract_bullets(changelog_text)

    breaking_changes: list[str] = []
    deprecations: list[str] = []
    migration_steps: list[str] = []
    new_required_configs: list[str] = []
    uncategorised: list[str] = []

    for bullet in bullets:
        tags = _classify_bullet(bullet)
        if not tags:
            uncategorised.append(bullet)
            continue
        if "breaking_change" in tags:
            breaking_changes.append(bullet)
        if "deprecation" in tags:
            deprecations.append(bullet)
        if "migration_step" in tags:
            migration_steps.append(bullet)
        if "new_required_config" in tags:
            new_required_configs.append(bullet)

    # Risk level heuristic
    bc_count = len(breaking_changes)
    dep_count = len(deprecations)
    if bc_count >= 3 or version_gap >= 5:
        risk_level = "HIGH"
    elif bc_count >= 1 or dep_count >= 3 or version_gap >= 3:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Human-readable summary
    summary_parts = [
        f"Upgrading from {current_version} to {target_version} spans {version_gap} minor version(s).",
        f"Found {bc_count} breaking change(s), {dep_count} deprecation(s), "
        f"{len(migration_steps)} migration step(s), and "
        f"{len(new_required_configs)} new required config field(s).",
        f"Overall upgrade risk: {risk_level}.",
    ]
    if bc_count == 0 and dep_count == 0:
        summary_parts.append(
            "No breaking changes or deprecations detected in the provided changelog text. "
            "Review manually to confirm."
        )
    summary = " ".join(summary_parts)

    return json.dumps({
        "current_version": current_version,
        "target_version": target_version,
        "version_gap": version_gap,
        "total_bullets_scanned": len(bullets),
        "breaking_changes": breaking_changes,
        "deprecations": deprecations,
        "migration_steps": migration_steps,
        "new_required_configs": new_required_configs,
        "uncategorised_highlights": uncategorised[:20],  # cap for readability
        "risk_level": risk_level,
        "summary": summary,
    }, indent=2)

# Made with Bob

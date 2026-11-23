"""
Tool: Jev-Powered Issue Match Assessor

Replaces the binary keyword-confidence scoring in analyze_and_match with
probabilistic Jev assessments. For each candidate (issue, error_log) pair,
Jev answers three questions in parallel (~100ms per pair):

  1. noul   — Does this error log actually match the described known issue?
  2. choice — Remediation safety: read_only_safe / requires_approval / destructive_blocked
  3. noul   — Is this issue likely to self-resolve without intervention?

The confidence score Jev returns for question 1 becomes the authoritative
match ranking, replacing the hand-tuned keyword overlap formula. The safety
classification gates whether execute_remediation runs automatically, asks for
approval, or is blocked entirely. The self-resolve signal can suppress
unnecessary remediation for transient conditions.

Prerequisites:
  - TYPESAFE_API_KEY environment variable must be set.
  - pip install typesafe-sdk
"""

import json
import os
import logging
from typing import Any

from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

logger = logging.getLogger(__name__)

# Confidence threshold below which a Jev assessment routes to human review
_LOW_CONFIDENCE_THRESHOLD = 0.70

# ─────────────────────────────────────────────────────────────────────────────
# Jev question definitions reused for every (issue, error_log) pair
# ─────────────────────────────────────────────────────────────────────────────
_JEV_QUESTIONS = {
    "is_match": {
        "type": "noul",
        "instructions": (
            "The error log and cluster signals describe the same problem as the "
            "known issue's documented problem description"
        ),
    },
    "remediation_safety": {
        "type": "choice",
        "instructions": (
            "What is the safest execution mode for the documented remediation steps "
            "given the described cluster state?"
        ),
        "criteria": {
            "read_only_safe": (
                "All remediation steps are read-only diagnostics or non-destructive "
                "commands (oc get, oc logs, oc describe) — safe to run automatically"
            ),
            "requires_approval": (
                "Remediation involves write operations such as pod restarts, rollouts, "
                "or scale changes that need explicit operator confirmation before execution"
            ),
            "destructive_blocked": (
                "Remediation involves potentially irreversible operations such as "
                "deleting persistent data, modifying cluster-wide configuration, or "
                "commands that could cause wider outage — must not run automatically"
            ),
        },
    },
    "will_self_resolve": {
        "type": "noul",
        "instructions": (
            "Based on the error pattern and cluster signals, this issue is likely "
            "transient and will self-resolve without manual intervention within "
            "a reasonable time (e.g., a pod restart loop that is already stabilising)"
        ),
    },
}


def _call_jev(state: str, api_key: str) -> dict:
    """Submit state + questions to Jev. Returns raw response dict or error dict."""
    try:
        from typesafe_sdk import TypeSafeClient  # type: ignore
    except ImportError:
        return {"error": "typesafe-sdk not installed. Run: pip install typesafe-sdk"}

    try:
        with TypeSafeClient(api_key=api_key) as client:
            response = client.systemone.evaluate(
                model="jev-latest",
                state=state,
                questions=_JEV_QUESTIONS,
            )
            return response.model_dump() if hasattr(response, "model_dump") else dict(response)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _extract_assessment(raw: dict, issue_title: str) -> dict:
    """Normalise Jev response into a flat assessment dict."""
    if "error" in raw:
        return {
            "issue_title": issue_title,
            "is_match": None,
            "match_confidence": None,
            "remediation_safety": "requires_approval",   # safe default on error
            "safety_confidence": None,
            "will_self_resolve": None,
            "routes_to_human": True,
            "jev_error": raw["error"],
        }

    answers = raw.get("answers", raw)

    def _noul(key: str) -> tuple[bool | None, float | None]:
        q = answers.get(key, {})
        val = q.get("noul")
        conf = q.get("confidence")
        return (val >= 0.5 if val is not None else None), conf

    def _choice(key: str) -> tuple[str, float | None]:
        q = answers.get(key, {})
        return q.get("choice", "requires_approval"), q.get("confidence")

    is_match, match_conf = _noul("is_match")
    safety, safety_conf = _choice("remediation_safety")
    self_resolve, _ = _noul("will_self_resolve")

    # Route to human if confidence on the match or safety call is too low
    routes_to_human = (
        match_conf is not None and match_conf < _LOW_CONFIDENCE_THRESHOLD
    ) or safety == "destructive_blocked"

    return {
        "issue_title": issue_title,
        "is_match": is_match,
        "match_confidence": match_conf,
        "remediation_safety": safety,
        "safety_confidence": safety_conf,
        "will_self_resolve": self_resolve,
        "routes_to_human": routes_to_human,
        "jev_error": None,
    }


@tool(
    name="jev_assess_matches",
    description=(
        "Use TypeSafe AI's Jev model to re-assess the candidate issue matches produced "
        "by analyze_and_match_issues. For each candidate pair (error signals, known issue), "
        "Jev answers three questions in parallel: does this error log actually match the "
        "known issue, what remediation safety class applies, and will this self-resolve. "
        "Returns enriched matches ranked by Jev confidence, with safety routing decisions "
        "that gate how execute_remediation proceeds. Low-confidence assessments are "
        "automatically flagged for human review. Requires TYPESAFE_API_KEY env variable."
    ),
    permission=ToolPermission.READ_ONLY,
)
def jev_assess_matches(
    analysis_result: dict[str, Any],
    cluster_status: dict[str, Any],
    service_logs: dict[str, Any],
) -> dict[str, Any]:
    """
    Re-assess keyword-matched known issues using Jev for probabilistic ranking
    and safety classification.

    Takes the output of analyze_and_match_issues and the raw cluster signals,
    then calls Jev for each candidate match. The Jev-ranked list replaces the
    keyword-confidence list as the authoritative input to generate_diagnosis_report
    and execute_remediation.

    Args:
        analysis_result: Output dict from analyze_and_match_issues. Must contain
                         "matched_issues" list and "unmatched_errors" list.
        cluster_status:  Output dict from collect_cluster_status. Used to build
                         the Jev state with full cluster context.
        service_logs:    Output dict from collect_service_logs. Error log text
                         is included in the Jev state for each issue pair.

    Returns:
        Dict containing:
        - jev_ranked_matches: list of matched issue dicts enriched with Jev fields:
            - is_match: bool — Jev's verdict on whether this is a genuine match
            - match_confidence: float 0–1 — Jev's confidence in the match
            - remediation_safety: read_only_safe | requires_approval | destructive_blocked
            - safety_confidence: float 0–1
            - will_self_resolve: bool
            - routes_to_human: bool — true when confidence < 0.70 or destructive_blocked
            - jev_error: null or error string if Jev call failed for this pair
        - top_match: the highest-confidence Jev-confirmed match (is_match=True), or null
        - auto_remediable: list of matches safe for automatic execution
            (read_only_safe, is_match=True, will_self_resolve=False, routes_to_human=False)
        - requires_approval: list of matches needing explicit operator approval
        - self_resolving: list of matches Jev assessed as likely to self-resolve
        - human_review_required: list of matches with low confidence or destructive steps
        - jev_available: bool — false if TYPESAFE_API_KEY is missing (fallback to keyword ranking)
        - fallback_matches: original keyword-ranked matches (always included for reference)
        - summary: plain-text summary of Jev assessment
    """
    api_key = os.environ.get("TYPESAFE_API_KEY", "")
    matched_issues: list[dict] = analysis_result.get("matched_issues", [])
    fallback_matches = matched_issues  # always kept for reference / fallback

    if not api_key:
        logger.warning("TYPESAFE_API_KEY not set — skipping Jev assessment, using keyword ranking.")
        return {
            "jev_ranked_matches": [],
            "top_match": matched_issues[0] if matched_issues else None,
            "auto_remediable": [],
            "requires_approval": [],
            "self_resolving": [],
            "human_review_required": [],
            "jev_available": False,
            "fallback_matches": fallback_matches,
            "summary": (
                "Jev assessment skipped — TYPESAFE_API_KEY is not set. "
                "Using keyword-confidence ranking from analyze_and_match_issues."
            ),
        }

    if not matched_issues:
        return {
            "jev_ranked_matches": [],
            "top_match": None,
            "auto_remediable": [],
            "requires_approval": [],
            "self_resolving": [],
            "human_review_required": [],
            "jev_available": True,
            "fallback_matches": [],
            "summary": "No candidate matches to assess — Jev assessment not needed.",
        }

    # Build a compact cluster context string for the Jev state
    unhealthy_pods = cluster_status.get("unhealthy_pods", [])
    recent_events = cluster_status.get("recent_events", [])
    error_logs = service_logs.get("error_logs", [])

    cluster_context = "\n".join([
        f"Cluster health: {cluster_status.get('overall_health', 'unknown')}",
        f"Unhealthy pods ({len(unhealthy_pods)}): " +
        ", ".join(
            f"{p['name']} ({', '.join(p.get('reasons', [])[:2])})"
            for p in unhealthy_pods[:5]
        ),
        f"Recent warning events ({len(recent_events)}): " +
        "; ".join(
            f"{e.get('reason', '')} on {e.get('object', '')}"
            for e in recent_events[:5]
        ),
        f"Top error logs ({min(len(error_logs), 5)}): " +
        "; ".join(
            e.get("message", "")[:120]
            for e in error_logs[:5]
        ),
    ])

    jev_assessments: list[dict] = []

    for candidate in matched_issues:
        issue_title = candidate.get("title", "Unknown")
        problem_desc = candidate.get("problem_description", "")
        solution_steps = candidate.get("solution_steps", "")
        evidence = "\n".join(candidate.get("matching_evidence", [])[:3])

        # State = cluster context + the specific known issue being evaluated
        state = (
            f"{cluster_context}\n\n"
            f"Known issue being evaluated:\n"
            f"Title: {issue_title}\n"
            f"Problem description: {problem_desc}\n"
            f"Solution steps (summary): {solution_steps[:400]}\n\n"
            f"Evidence from this cluster matching the issue:\n{evidence}"
        )

        raw = _call_jev(state, api_key)
        assessment = _extract_assessment(raw, issue_title)

        # Merge Jev assessment fields into the original candidate dict
        enriched = {**candidate, **assessment}
        jev_assessments.append(enriched)

    # Rank by Jev match_confidence (descending), with non-matches at the bottom
    jev_assessments.sort(
        key=lambda x: (
            x.get("is_match") is True,
            x.get("match_confidence") or 0.0,
        ),
        reverse=True,
    )

    # Partition into routing buckets
    auto_remediable = [
        m for m in jev_assessments
        if m.get("is_match") is True
        and m.get("remediation_safety") == "read_only_safe"
        and m.get("will_self_resolve") is False
        and not m.get("routes_to_human")
    ]
    requires_approval = [
        m for m in jev_assessments
        if m.get("is_match") is True
        and m.get("remediation_safety") == "requires_approval"
        and not m.get("routes_to_human")
    ]
    self_resolving = [
        m for m in jev_assessments
        if m.get("is_match") is True
        and m.get("will_self_resolve") is True
    ]
    human_review = [
        m for m in jev_assessments
        if m.get("routes_to_human") is True
        or m.get("remediation_safety") == "destructive_blocked"
    ]

    # Top match: highest-confidence Jev-confirmed match that is not self-resolving
    # and not destructive_blocked
    actionable = [
        m for m in jev_assessments
        if m.get("is_match") is True
        and m.get("will_self_resolve") is False
        and m.get("remediation_safety") != "destructive_blocked"
    ]
    top_match = actionable[0] if actionable else (
        jev_assessments[0] if jev_assessments else None
    )

    # Summary
    confirmed = sum(1 for m in jev_assessments if m.get("is_match") is True)
    rejected = sum(1 for m in jev_assessments if m.get("is_match") is False)
    summary_parts = [
        f"Jev assessed {len(jev_assessments)} candidate match(es).",
        f"{confirmed} confirmed as genuine match(es), {rejected} rejected as non-matches.",
        f"{len(auto_remediable)} auto-remediable (read-only safe, no approval needed).",
        f"{len(requires_approval)} require operator approval before execution.",
        f"{len(self_resolving)} assessed as likely to self-resolve.",
        f"{len(human_review)} routed to human review (low confidence or destructive steps).",
    ]
    if top_match:
        conf_str = (
            f"{top_match['match_confidence']:.0%}"
            if top_match.get("match_confidence") is not None
            else "n/a"
        )
        summary_parts.append(
            f"Top actionable match: '{top_match['issue_title']}' "
            f"(confidence: {conf_str}, safety: {top_match.get('remediation_safety', 'unknown')})."
        )

    return {
        "jev_ranked_matches": jev_assessments,
        "top_match": top_match,
        "auto_remediable": auto_remediable,
        "requires_approval": requires_approval,
        "self_resolving": self_resolving,
        "human_review_required": human_review,
        "jev_available": True,
        "fallback_matches": fallback_matches,
        "summary": " ".join(summary_parts),
    }

# Made with Bob

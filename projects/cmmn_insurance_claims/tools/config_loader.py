"""
Config loader — shared utility for all CMMN tools.

Loads cmmn_config.yaml and case_plan_table.csv once at module import time
and exposes typed, cached accessors for the tools to consume.

Both files live at:
  <project_root>/config/cmmn_config.yaml
  <project_root>/config/case_plan_table.csv

The loader resolves the config directory relative to this file so the tools
work regardless of the current working directory.
"""

from __future__ import annotations
import csv
import functools
from pathlib import Path
from typing import Any

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@functools.lru_cache(maxsize=1)
def _load_yaml() -> dict[str, Any]:
    with open(_CONFIG_DIR / "cmmn_config.yaml") as fh:
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _load_plan_csv() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(_CONFIG_DIR / "case_plan_table.csv") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    return rows


# ── Public typed accessors ────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def get_case_definition() -> dict[str, Any]:
    """Return the top-level case definition block."""
    return _load_yaml()["case"]


@functools.lru_cache(maxsize=1)
def get_claim_types() -> dict[str, dict[str, Any]]:
    """Return claim type definitions keyed by claim_type id."""
    return {c["id"]: c for c in _load_yaml()["claim_types"]}


@functools.lru_cache(maxsize=1)
def get_stages() -> dict[str, dict[str, Any]]:
    """Return stage definitions keyed by stage id, sorted by order."""
    stages = {s["id"]: s for s in _load_yaml()["stages"]}
    return dict(sorted(stages.items(), key=lambda kv: kv[1].get("order", 99)))


@functools.lru_cache(maxsize=1)
def get_tasks() -> dict[str, dict[str, Any]]:
    """Return task definitions keyed by task id."""
    return {t["id"]: t for t in _load_yaml()["tasks"]}


@functools.lru_cache(maxsize=1)
def get_tasks_by_stage() -> dict[str, list[dict[str, Any]]]:
    """Return tasks grouped by stage id, sorted by order within each stage."""
    result: dict[str, list[dict[str, Any]]] = {}
    for task in sorted(_load_yaml()["tasks"], key=lambda t: t.get("order", 99)):
        stage = task["stage"]
        result.setdefault(stage, []).append(task)
    return result


@functools.lru_cache(maxsize=1)
def get_milestones() -> dict[str, dict[str, Any]]:
    """Return milestone definitions keyed by milestone id."""
    return {m["id"]: m for m in _load_yaml()["milestones"]}


@functools.lru_cache(maxsize=1)
def get_case_plan_table() -> dict[str, dict[str, Any]]:
    """
    Return case plan parameters keyed by claim_type.

    Each entry: {
        severity_threshold_high:        float,
        severity_threshold_critical:    float,
        fraud_score_flag:               float,
        auto_approve_limit:             float,
        sla_warning_pct:                float,
        sla_breach_pct:                 float,
        reserve_multiplier:             float,
        escalate_supervisor_on_override: bool,
    }
    """
    table: dict[str, dict[str, Any]] = {}
    for row in _load_plan_csv():
        ct = row["claim_type"]
        table[ct] = {
            "severity_threshold_high":        float(row["severity_threshold_high"]),
            "severity_threshold_critical":    float(row["severity_threshold_critical"]),
            "fraud_score_flag":               float(row["fraud_score_flag"]),
            "auto_approve_limit":             float(row["auto_approve_limit"]),
            "sla_warning_pct":                float(row["sla_warning_pct"]),
            "sla_breach_pct":                 float(row["sla_breach_pct"]),
            "reserve_multiplier":             float(row["reserve_multiplier"]),
            "escalate_supervisor_on_override": row["escalate_supervisor_on_override"].strip().lower() == "true",
        }
    return table

"""
Config loader — shared utility for all MDP tools.

Loads mdp_config.yaml and policy_table.csv once at module import time
and exposes typed, cached objects for the tools to consume.

Both files live at:
  <project_root>/config/mdp_config.yaml
  <project_root>/config/policy_table.csv

The loader resolves the config directory relative to this file, so the
tools work regardless of the current working directory.
"""

from __future__ import annotations
import csv
import functools
from pathlib import Path
from typing import Any

import yaml  # PyYAML — already a transitive dependency of ibm-watsonx-orchestrate

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# ── Raw YAML loader ────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _load_yaml() -> dict[str, Any]:
    path = _CONFIG_DIR / "mdp_config.yaml"
    with open(path) as fh:
        # Strip comment-only lines before parsing (yaml.safe_load handles # inline fine,
        # but the file starts with a comment block — safe_load handles that correctly too)
        return yaml.safe_load(fh)


@functools.lru_cache(maxsize=1)
def _load_policy_csv() -> list[dict[str, str]]:
    path = _CONFIG_DIR / "policy_table.csv"
    rows: list[dict[str, str]] = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    return rows


# ── Public accessors ───────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def get_mdp_params() -> dict[str, float]:
    """Return Bellman hyperparameters: {'learning_rate': 0.1, 'discount_factor': 0.9}."""
    cfg = _load_yaml()
    return {
        "learning_rate": float(cfg["mdp"]["learning_rate"]),
        "discount_factor": float(cfg["mdp"]["discount_factor"]),
    }


@functools.lru_cache(maxsize=1)
def get_states() -> dict[str, dict[str, Any]]:
    """Return state definitions keyed by state_id."""
    cfg = _load_yaml()
    return {s["id"]: s for s in cfg["states"]}


@functools.lru_cache(maxsize=1)
def get_vital_thresholds() -> dict[str, dict[str, float]]:
    """Return vital thresholds keyed by vital name."""
    cfg = _load_yaml()
    return {name: {k: float(v) for k, v in thresholds.items() if k != "unit"}
            for name, thresholds in cfg["vitals"].items()}


@functools.lru_cache(maxsize=1)
def get_actions() -> dict[str, dict[str, Any]]:
    """Return action definitions keyed by action_id."""
    cfg = _load_yaml()
    return {a["id"]: a for a in cfg["actions"]}


@functools.lru_cache(maxsize=1)
def get_policy_table() -> dict[str, dict[str, Any]]:
    """
    Return the policy table keyed by state_id.

    Each entry: {
        'optimal_action_id': str,
        'q_value': float,
        'reward_transition_per_level': float,
        'reward_policy_adherence': float,
        'reward_over_treatment': float,
        'reward_under_treatment': float,
        'reward_timeliness_bonus': float,
        'reward_timeliness_penalty': float,
    }
    """
    table: dict[str, dict[str, Any]] = {}
    for row in _load_policy_csv():
        sid = row["state_id"]
        table[sid] = {
            "optimal_action_id":           row["optimal_action_id"],
            "q_value":                     float(row["q_value"]),
            "reward_transition_per_level": float(row["reward_transition_per_level"]),
            "reward_policy_adherence":     float(row["reward_policy_adherence"]),
            "reward_over_treatment":       float(row["reward_over_treatment"]),
            "reward_under_treatment":      float(row["reward_under_treatment"]),
            "reward_timeliness_bonus":     float(row["reward_timeliness_bonus"]),
            "reward_timeliness_penalty":   float(row["reward_timeliness_penalty"]),
        }
    return table

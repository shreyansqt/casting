"""Policy document helpers.

The core accepts a policy document directly. Storage and host inventory are
separate boundaries. A caller can therefore load policy from any source.
"""

from __future__ import annotations

import copy
from typing import Any


class PolicyError(ValueError):
    """The policy document cannot be used for routing."""


POLICY_VERSION = 1


def merge_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with each model overlay applied.

    The top-level ``preferences`` block remains separate. This preserves the
    landed PWC schema and prevents a catalog refresh from changing user policy.
    """
    if not isinstance(policy, dict) or not isinstance(policy.get("models"), list):
        raise PolicyError("expected an object with a 'models' list")
    if policy.get("version") != POLICY_VERSION:
        raise PolicyError(
            f"unsupported policy version {policy.get('version')!r}; "
            f"supported: {POLICY_VERSION}"
        )
    overlays = policy.get("overlay") or {}
    if not isinstance(overlays, dict):
        raise PolicyError("expected 'overlay' to be an object")
    preferences = policy.get("preferences") or {}
    if not isinstance(preferences, dict):
        raise PolicyError("expected 'preferences' to be an object")

    models: list[dict[str, Any]] = []
    for source in policy["models"]:
        if not isinstance(source, dict):
            raise PolicyError("expected every model row to be an object")
        row = copy.deepcopy(source)
        overlay = overlays.get(row.get("key")) or {}
        if not isinstance(overlay, dict):
            raise PolicyError(f"expected overlay for {row.get('key')} to be an object")
        if overlay.get("tiers"):
            row.setdefault("tiers", {}).update(overlay["tiers"])
        for field in ("note", "available", "data_ok"):
            if overlay.get(field) is not None:
                row[field] = overlay[field]
        row["cost_weight"] = float(
            overlay.get("cost_weight", row.get("cost_weight", 1.0))
        )
        models.append(row)

    return {
        **copy.deepcopy(policy),
        "models": models,
        "overlay": copy.deepcopy(overlays),
        "preferences": copy.deepcopy(preferences),
    }

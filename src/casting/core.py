"""Pure harness and model selection.

The decision order matches PWC commit ``daf1738``:

1. Apply availability, trust, and context hard filters.
2. Apply capability and outward-facing gates.
3. Apply the domain preference to its deterministic key share.
4. Use effective blended cost when preference does not apply.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .policy import merge_policy

DOMAINS = ("code-review", "implementation", "research-writing", "ops-comms")
RISKS = ("none", "outward", "prod-data")
PRICE_FIELDS = ("cost_in", "cost_out", "cache_read", "cache_write")

_PROD_DATA_MIN_TIER = 4
_OUTWARD_MIN_OPS_TIER = 3
_LOW_VERIFIABILITY = 2
_PREFERENCE_BUCKETS = 10_000
_MIX = {"cache_read": 0.80, "cost_in": 0.05, "cost_out": 0.10, "cache_write": 0.05}


class CastingError(ValueError):
    """Casting cannot produce a valid route for the supplied inputs."""


def _price_of(row: dict[str, Any]) -> dict[str, float]:
    return {field: float(row.get(field) or 0.0) for field in PRICE_FIELDS}


def blended_cost(row: dict[str, Any]) -> float:
    """Return the PWC baseline blended rack rate in USD per million tokens."""
    price = _price_of(row)
    fallback = price["cost_in"]
    total = 0.0
    for field, weight in _MIX.items():
        value = price[field]
        if not value and field in ("cache_read", "cache_write"):
            value = fallback
        total += value * weight
    return round(total, 6)


def required_tier(reasoning: int, verifiability: int) -> tuple[int, str | None]:
    """Return the required tier and the reason for an increase."""
    if verifiability <= _LOW_VERIFIABILITY and reasoning < 5:
        return reasoning + 1, (
            f"raised to {reasoning + 1}: verifiability {verifiability} is low, so a "
            "wrong answer wouldn't be caught cheaply"
        )
    return reasoning, None


def preference_bucket(stable_key: str) -> int:
    """Return the exact landed SHA-256 bucket from 0 through 9,999."""
    digest = hashlib.sha256(stable_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % _PREFERENCE_BUCKETS


def _preference_for(
    policy: dict[str, Any], domain: str, now: datetime | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    preference = (policy.get("preferences") or {}).get(domain)
    if not preference:
        return None, None
    if not isinstance(preference, dict) or not preference.get("key"):
        raise CastingError(
            f"malformed preference for {domain}: expected an object with `key`"
        )
    try:
        strength = int(preference.get("strength"))
    except (TypeError, ValueError) as error:
        raise CastingError(
            f"malformed preference for {domain}: strength must be 0-100"
        ) from error
    if not 0 <= strength <= 100:
        raise CastingError(f"malformed preference for {domain}: strength must be 0-100")
    preference = {**preference, "strength": strength}
    expires_at = preference.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise CastingError(
                f"malformed preference for {domain}: expires_at must be RFC3339"
            ) from error
        if expiry.tzinfo is None:
            raise CastingError(
                f"malformed preference for {domain}: expires_at needs a timezone"
            )
        current = now or datetime.now(timezone.utc)
        if current >= expiry:
            return None, f"preference for {preference['key']} expired at {expires_at}"
    return preference, None


def _rack_rate_comparison(preferred: dict[str, Any], cost_pick: dict[str, Any]) -> str:
    preferred_cost = preferred["blended"]
    cost_cost = cost_pick["blended"]
    if preferred_cost == cost_cost:
        return "the blended rack rates are equal"
    if cost_cost < preferred_cost:
        cheaper = (preferred_cost - cost_cost) / preferred_cost * 100
        return (
            f"{cost_pick['key']} is {cheaper:.1f}% cheaper on blended rack rate "
            f"({cost_cost:g} vs {preferred_cost:g})"
        )
    cheaper = (cost_cost - preferred_cost) / cost_cost * 100
    return (
        f"{preferred['key']} is {cheaper:.1f}% cheaper on blended rack rate "
        f"({preferred_cost:g} vs {cost_cost:g})"
    )


def route(
    profile: dict[str, Any], policy: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Return one deterministic route from a profile and merged policy document.

    ``stable_key`` is opaque. Casting hashes it but never parses its format.
    """
    policy = merge_policy(policy)
    domain = profile["domain"]
    stable_key = str(profile.get("stable_key") or "").strip()
    reasoning = int(profile["reasoning"])
    verifiability = int(profile.get("verifiability", 3))
    risk = profile.get("risk", "none")
    context_need = int(profile.get("context_need", 0) or 0)

    if not stable_key:
        raise CastingError("route requires an opaque stable key")
    if domain not in DOMAINS:
        raise CastingError(f"unknown domain {domain!r} — known: {', '.join(DOMAINS)}")
    if risk not in RISKS:
        raise CastingError(f"unknown risk {risk!r} — known: {', '.join(RISKS)}")
    if not 1 <= reasoning <= 5:
        raise CastingError(f"reasoning must be 1-5 (got {reasoning})")

    need, raised_why = required_tier(reasoning, verifiability)
    if risk == "prod-data" and need < _PROD_DATA_MIN_TIER:
        need = _PROD_DATA_MIN_TIER
        raised_why = (
            f"raised to {_PROD_DATA_MIN_TIER}: task touches production data, so a "
            "cheap mistake is an expensive mistake"
        )

    rejected: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for row in policy["models"]:
        key = row.get("key")
        tier = (row.get("tiers") or {}).get(domain)
        if not row.get("available"):
            rejected.append(
                {"key": key, "why": "harness unavailable (not installed or not authenticated)"}
            )
            continue
        if risk == "prod-data" and not row.get("data_ok"):
            rejected.append(
                {
                    "key": key,
                    "why": "not cleared for production data (set `data_ok` in the table/overlay to allow)",
                }
            )
            continue
        if context_need and (row.get("context") or 0) < context_need:
            rejected.append(
                {
                    "key": key,
                    "why": f"context {row.get('context'):,} < needed {context_need:,}",
                }
            )
            continue
        if tier is None:
            rejected.append({"key": key, "why": f"no tier recorded for {domain}"})
            continue
        if tier < need:
            rejected.append({"key": key, "why": f"{domain} tier {tier} < required {need}"})
            continue
        if risk == "outward":
            ops_tier = (row.get("tiers") or {}).get("ops-comms", 0)
            if ops_tier < _OUTWARD_MIN_OPS_TIER:
                rejected.append(
                    {
                        "key": key,
                        "why": f"outward-facing: ops-comms tier {ops_tier} < {_OUTWARD_MIN_OPS_TIER}",
                    }
                )
                continue
        candidates.append(
            {
                **row,
                "tier": tier,
                "blended": blended_cost(row),
                "cost_weight": row.get("cost_weight", 1.0),
            }
        )

    if not candidates:
        details = "; ".join(f"{item['key']} — {item['why']}" for item in rejected)
        raise CastingError(
            "no model qualifies for this task profile "
            f"(domain={domain}, required tier={need}, risk={risk}, "
            f"context need={context_need:,}). Rejected: {details}. There is no "
            "fallback chain by design: widen the profile, fix harness availability, "
            "or lower the requirement deliberately."
        )

    candidates.sort(
        key=lambda candidate: (
            candidate["blended"] * candidate["cost_weight"],
            candidate["tier"],
            candidate["key"],
        )
    )
    cost_pick = candidates[0]
    pick = cost_pick

    preference, inactive_why = _preference_for(policy, domain, now=now)
    preference_result = None
    preference_why = inactive_why
    if preference:
        bucket = preference_bucket(stable_key)
        selected = bucket < preference["strength"] * 100
        preferred = next(
            (candidate for candidate in candidates if candidate["key"] == preference["key"]),
            None,
        )
        applied = bool(selected and preferred)
        if applied:
            pick = preferred
        preference_result = {
            "key": preference["key"],
            "strength": preference["strength"],
            "task_bucket": round(bucket / 100, 2),
            "selected": selected,
            "applied": applied,
        }
        for field in ("expires_at", "note"):
            if preference.get(field):
                preference_result[field] = preference[field]
        if preferred is None:
            preference_why = (
                f"preference for {preference['key']} did not apply because that model "
                "was not in the qualified candidate set"
            )
        elif not selected:
            preference_why = (
                f"preference target is {preference['strength']}%; task {stable_key} "
                f"bucket {bucket / 100:.2f}% fell outside it"
            )
        elif preferred["key"] == cost_pick["key"]:
            preference_why = (
                f"preference selected {preferred['key']} for {domain} at "
                f"{preference['strength']}%; it also won on cost"
            )
        else:
            preference_why = (
                f"preference selected {preferred['key']} for {domain} at "
                f"{preference['strength']}% over cost winner {cost_pick['key']}; "
                f"{_rack_rate_comparison(preferred, cost_pick)}"
            )

    if pick["key"] == cost_pick["key"]:
        explanation = [f"cheapest {domain} model at tier >= {need}"]
    else:
        explanation = [f"qualified {domain} model at tier >= {need}"]
    if preference_why:
        explanation.append(preference_why)
    if raised_why:
        explanation.append(raised_why)
    if context_need:
        explanation.append(f"{pick['context']:,} ctx covers the {context_need:,} needed")
    runners = candidates[1:3] if pick["key"] == cost_pick["key"] else []
    if runners:
        parts = [
            f"{candidate['key']}"
            + (
                f" (eff ×{candidate['cost_weight']})"
                if candidate["cost_weight"] != 1.0
                else ""
            )
            for candidate in runners
        ]
        explanation.append(f"beat {', '.join(parts)} on effective cost")
    weighted = {
        candidate["key"]: candidate["cost_weight"]
        for candidate in candidates
        if candidate["cost_weight"] != 1.0
    }
    if weighted:
        explanation.append(
            "cost weights: " + ", ".join(f"{key} ×{weight}" for key, weight in weighted.items())
        )

    result: dict[str, Any] = {
        "key": pick["key"],
        "stable_key": stable_key,
        "harness": pick["harness"],
        "model": pick["model"],
        "domain": domain,
        "tier": pick["tier"],
        "required_tier": need,
        "blended_cost_per_mtok": pick["blended"],
        "cost_per_mtok": {field: pick.get(field) for field in PRICE_FIELDS},
        "context": pick["context"],
        "why": "; ".join(explanation),
        "candidates": [
            {"key": candidate["key"], "tier": candidate["tier"], "blended": candidate["blended"]}
            for candidate in candidates
        ],
        "rejected": rejected,
    }
    if pick["cost_weight"] != 1.0:
        result["cost_weight_applied"] = pick["cost_weight"]
    if preference_result:
        result["preference"] = preference_result
    return result

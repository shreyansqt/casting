from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from casting import (
    CastingError,
    PolicyError,
    merge_policy,
    preference_bucket,
    required_tier,
    route,
)
from casting.core import blended_cost

DOMAIN = "implementation"
FIXTURES = Path(__file__).parent / "fixtures"


def model(
    key: str,
    *,
    harness: str = "test",
    available: bool = True,
    data_ok: bool = True,
    context: int = 200_000,
    tiers: dict[str, int] | None = None,
    cost_in: float = 1.0,
    cost_out: float = 5.0,
    cache_read: float | None = 1.0,
    cache_write: float | None = 1.0,
    cost_weight: float | None = None,
) -> dict:
    row = {
        "key": key,
        "harness": harness,
        "model": f"test/{key}",
        "catalog_id": f"test/{key}",
        "available": available,
        "data_ok": data_ok,
        "context": context,
        "cost_in": cost_in,
        "cost_out": cost_out,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "tiers": tiers or {DOMAIN: 3, "ops-comms": 3},
    }
    if cost_weight is not None:
        row["cost_weight"] = cost_weight
    return row


def policy(*models: dict, preference: dict | None = None) -> dict:
    preferences = {DOMAIN: preference} if preference else {}
    return {
        "version": 1,
        "models": list(models),
        "overlay": {},
        "preferences": preferences,
    }


def profile(
    *,
    stable_key: str = "work-1",
    domain: str = DOMAIN,
    reasoning: int = 3,
    verifiability: int = 3,
    risk: str = "none",
    context_need: int = 0,
) -> dict:
    return {
        "stable_key": stable_key,
        "domain": domain,
        "reasoning": reasoning,
        "verifiability": verifiability,
        "risk": risk,
        "context_need": context_need,
    }


def test_cheapest_qualified_model_wins() -> None:
    cheap = model("cheap")
    expensive = model("expensive", cost_in=2, cost_out=10, cache_read=2, cache_write=2)
    result = route(profile(), policy(cheap, expensive))
    assert result["key"] == "cheap"
    assert result["why"].startswith("cheapest implementation model")


def test_cost_ties_prefer_lower_tier_then_model_key() -> None:
    tier_four = model("a-tier-four", tiers={DOMAIN: 4})
    tier_three_b = model("b-tier-three", tiers={DOMAIN: 3})
    tier_three_a = model("a-tier-three", tiers={DOMAIN: 3})
    result = route(profile(), policy(tier_four, tier_three_b, tier_three_a))
    assert result["key"] == "a-tier-three"


def test_missing_cache_prices_fall_back_to_input_price() -> None:
    row = model("model", cost_in=2, cost_out=10, cache_read=None, cache_write=None)
    assert blended_cost(row) == 2.8


def test_unavailable_model_is_rejected() -> None:
    ghost = model("ghost", available=False, cost_in=0.01, cost_out=0.01)
    real = model("real")
    result = route(profile(), policy(ghost, real))
    assert result["key"] == "real"
    assert result["rejected"][0]["why"] == (
        "harness unavailable (not installed or not authenticated)"
    )


def test_context_need_is_a_hard_filter() -> None:
    result = route(
        profile(context_need=100_000),
        policy(model("small", context=50_000), model("large", context=200_000)),
    )
    assert result["key"] == "large"
    assert "context 50,000 < needed 100,000" in result["rejected"][0]["why"]


def test_low_verifiability_raises_capability_gate() -> None:
    low = model("low", tiers={DOMAIN: 3, "ops-comms": 3})
    high = model("high", tiers={DOMAIN: 4, "ops-comms": 3})
    result = route(profile(reasoning=3, verifiability=1), policy(low, high))
    assert result["key"] == "high"
    assert result["required_tier"] == 4
    assert "wrong answer wouldn't be caught cheaply" in result["why"]


def test_required_tier_never_exceeds_five() -> None:
    assert required_tier(5, 1) == (5, None)


def test_production_data_requires_clearance_and_tier_four() -> None:
    untrusted = model("untrusted", data_ok=False, tiers={DOMAIN: 5})
    weak = model("weak", tiers={DOMAIN: 3})
    qualified = model("qualified", tiers={DOMAIN: 4})
    result = route(
        profile(reasoning=3, risk="prod-data"), policy(untrusted, weak, qualified)
    )
    assert result["key"] == "qualified"
    assert result["required_tier"] == 4
    rejected = {item["key"]: item["why"] for item in result["rejected"]}
    assert "not cleared for production data" in rejected["untrusted"]
    assert "tier 3 < required 4" in rejected["weak"]


def test_outward_work_requires_ops_comms_tier_three() -> None:
    weak_writer = model("weak-writer", tiers={DOMAIN: 5, "ops-comms": 2})
    writer = model("writer", tiers={DOMAIN: 4, "ops-comms": 3})
    result = route(profile(reasoning=4, risk="outward"), policy(weak_writer, writer))
    assert result["key"] == "writer"
    assert "outward-facing: ops-comms tier 2 < 3" in result["rejected"][0]["why"]


def test_no_fallback_chain_when_nothing_qualifies() -> None:
    with pytest.raises(CastingError, match="There is no fallback chain by design"):
        route(profile(), policy(model("ghost", available=False)))


def test_stable_key_is_required() -> None:
    with pytest.raises(CastingError, match="opaque stable key"):
        route(profile(stable_key=""), policy(model("model")))


def test_preference_uses_exact_sha256_bucket_rule() -> None:
    assert preference_bucket("fixture-14-1201") == 8369
    assert preference_bucket("fixture-14-1206") == 7099


def test_preference_overrides_cost_and_explains_price_difference() -> None:
    cheap = model("cheap", cost_in=1, cost_out=1, cache_read=1, cache_write=1)
    preferred = model("preferred", cost_in=2, cost_out=2, cache_read=2, cache_write=2)
    result = route(
        profile(),
        policy(
            cheap,
            preferred,
            preference={"key": "preferred", "strength": 100, "note": "Use it."},
        ),
    )
    assert result["key"] == "preferred"
    assert result["preference"]["applied"] is True
    assert "cheap is 50.0% cheaper on blended rack rate" in result["why"]


@pytest.mark.parametrize(
    "preferred",
    [
        model("preferred", available=False),
        model("preferred", tiers={DOMAIN: 2}),
        model("preferred", context=50_000),
        model("preferred", data_ok=False, tiers={DOMAIN: 4}),
    ],
)
def test_preference_never_widens_candidate_set(preferred: dict) -> None:
    test_profile = profile()
    if preferred["context"] == 50_000:
        test_profile["context_need"] = 100_000
    if not preferred["data_ok"]:
        test_profile.update({"risk": "prod-data", "reasoning": 4})
    qualified = model("qualified", context=200_000, tiers={DOMAIN: 4})
    result = route(
        test_profile,
        policy(qualified, preferred, preference={"key": "preferred", "strength": 100}),
    )
    assert result["key"] == "qualified"
    assert result["preference"]["applied"] is False


def test_expired_preference_stops_applying_and_explains_expiry() -> None:
    cheap = model("cheap", cost_in=1, cost_out=1, cache_read=1, cache_write=1)
    preferred = model("preferred", cost_in=2, cost_out=2, cache_read=2, cache_write=2)
    result = route(
        profile(),
        policy(
            cheap,
            preferred,
            preference={
                "key": "preferred",
                "strength": 100,
                "expires_at": "2026-08-01T00:00:00Z",
            },
        ),
        now=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    assert result["key"] == "cheap"
    assert "expired at 2026-08-01T00:00:00Z" in result["why"]


@pytest.mark.parametrize(
    "preference,error",
    [
        ({"strength": 80}, "expected an object with `key`"),
        ({"key": "model", "strength": 101}, "strength must be 0-100"),
        (
            {"key": "model", "strength": 80, "expires_at": "2026-09-01T00:00:00"},
            "needs a timezone",
        ),
    ],
)
def test_malformed_preference_is_rejected(preference: dict, error: str) -> None:
    with pytest.raises(CastingError, match=error):
        route(profile(), policy(model("model"), preference=preference))


def test_cost_weight_changes_order_but_not_capability() -> None:
    weighted = model("weighted", cost_in=1, cost_out=3, cost_weight=2, tiers={DOMAIN: 4})
    lower_tier = model("lower", cost_in=0.5, cost_out=1, tiers={DOMAIN: 2})
    result = route(profile(reasoning=4), policy(weighted, lower_tier))
    assert result["key"] == "weighted"
    assert result["cost_weight_applied"] == 2


def test_overlay_merge_preserves_top_level_preferences() -> None:
    raw = policy(model("model"), preference={"key": "model", "strength": 80})
    raw["overlay"] = {
        "model": {
            "available": False,
            "tiers": {DOMAIN: 5},
            "note": "Blocked.",
            "cost_weight": 1.5,
        }
    }
    merged = merge_policy(raw)
    assert merged["preferences"] == raw["preferences"]
    assert merged["models"][0]["available"] is False
    assert merged["models"][0]["tiers"][DOMAIN] == 5
    assert merged["models"][0]["cost_weight"] == 1.5


def test_unknown_policy_version_is_rejected() -> None:
    raw = policy(model("model"))
    raw["version"] = 2
    with pytest.raises(PolicyError, match="unsupported policy version 2"):
        route(profile(), raw)


def test_public_post_issue_12_policy_matches_first_cycle_explanations() -> None:
    raw_policy = json.loads((FIXTURES / "pwc-daf1738-routing-policy.json").read_text())
    corpus = json.loads((FIXTURES / "migration-corpus.json").read_text())
    merged = merge_policy(raw_policy)
    expected = [
        (
            "claude/opus",
            "cheapest implementation model at tier >= 4; preference target is "
            "80%; task fixture-14-1201 bucket 83.69% fell outside it; "
            "1,000,000 ctx covers the 200,000 needed; beat codex/gpt-5.6-sol, "
            "claude/fable on effective cost",
        ),
        (
            "codex/gpt-5.6-sol",
            "qualified implementation model at tier >= 5; preference selected "
            "codex/gpt-5.6-sol for implementation at 80% over cost winner "
            "claude/opus; claude/opus is 12.6% cheaper on blended rack rate "
            "(3.4625 vs 3.9625); raised to 5: verifiability 1 is low, so a wrong "
            "answer wouldn't be caught cheaply",
        ),
        (
            "codex/gpt-5.6-sol",
            "qualified implementation model at tier >= 5; preference selected "
            "codex/gpt-5.6-sol for implementation at 80% over cost winner "
            "claude/opus; claude/opus is 12.6% cheaper on blended rack rate "
            "(3.4625 vs 3.9625); 1,050,000 ctx covers the 500,000 needed",
        ),
        (
            "codex/gpt-5.6-sol",
            "qualified implementation model at tier >= 4; preference selected "
            "codex/gpt-5.6-sol for implementation at 80% over cost winner "
            "claude/opus; claude/opus is 12.6% cheaper on blended rack rate "
            "(3.4625 vs 3.9625)",
        ),
        (
            "codex/gpt-5.6-sol",
            "qualified implementation model at tier >= 4; preference selected "
            "codex/gpt-5.6-sol for implementation at 80% over cost winner "
            "claude/opus; claude/opus is 12.6% cheaper on blended rack rate "
            "(3.4625 vs 3.9625); 1,050,000 ctx covers the 100,000 needed",
        ),
        (
            "codex/gpt-5.6-sol",
            "qualified implementation model at tier >= 3; preference selected "
            "codex/gpt-5.6-sol for implementation at 80% over cost winner "
            "claude/opus; claude/opus is 12.6% cheaper on blended rack rate "
            "(3.4625 vs 3.9625)",
        ),
    ]
    for offset, route_profile in enumerate(corpus["profiles"]):
        result = route(
            {
                "stable_key": f"{corpus['key_prefix']}"
                f"{corpus['first_key_number'] + offset}",
                "domain": corpus["domain"],
                **route_profile,
            },
            merged,
        )
        assert (result["key"], result["why"]) == expected[offset]


def test_migration_policy_digest_is_fixed() -> None:
    policy_bytes = (FIXTURES / "pwc-daf1738-routing-policy.json").read_bytes()
    corpus = json.loads((FIXTURES / "migration-corpus.json").read_text())
    assert hashlib.sha256(policy_bytes).hexdigest() == corpus["policy_sha256"]


def test_exact_300_route_migration_corpus_is_240_60() -> None:
    raw_policy = json.loads((FIXTURES / "pwc-daf1738-routing-policy.json").read_text())
    corpus = json.loads((FIXTURES / "migration-corpus.json").read_text())
    merged = merge_policy(raw_policy)
    counts = {"codex": 0, "claude": 0, "errors": 0}
    for offset in range(corpus["route_count"]):
        route_profile = corpus["profiles"][offset % len(corpus["profiles"])]
        try:
            result = route(
                {
                    "stable_key": f"{corpus['key_prefix']}"
                    f"{corpus['first_key_number'] + offset}",
                    "domain": corpus["domain"],
                    **route_profile,
                },
                merged,
            )
        except CastingError:
            counts["errors"] += 1
        else:
            counts[result["harness"]] += 1
    assert counts == corpus["expected"]

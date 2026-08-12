from __future__ import annotations

from amlguard.domain.experiments import CapabilityResult


def select_capability_tiers(
    results: list[CapabilityResult],
) -> tuple[CapabilityResult, CapabilityResult, CapabilityResult]:
    eligible = sorted(
        (item for item in results if item.eu_catalogue_eligible and item.no_fallback_verified),
        key=lambda item: item.capability_score,
    )
    if len(eligible) < 3:
        raise ValueError("at least three EU-eligible models are required")
    third = max(1, len(eligible) // 3)
    lower = eligible[:third]
    middle = eligible[third : max(third + 1, len(eligible) - third)]
    upper = eligible[-third:]

    def cost_key(item: CapabilityResult) -> tuple[bool, object, float]:
        return (
            item.cost_per_million_tokens_eur is None,
            item.cost_per_million_tokens_eur or 0,
            -item.capability_score,
        )

    m1 = min(lower, key=cost_key)
    m2 = max(middle, key=lambda item: item.capability_score)
    m3 = max(upper, key=lambda item: item.capability_score)
    return m1, m2, m3

from __future__ import annotations

from amlguard.domain.scenarios import ScenarioDefinition


def to_trap_manifest(scenario: ScenarioDefinition) -> dict[str, object]:
    """Convert canonical scenario metadata without exposing hidden ground truth."""
    return {
        "name": scenario.scenario_id,
        "family": scenario.pattern.family,
        "description": scenario.title,
        "turns": scenario.visible_facts.get("turns", []),
        "success_criteria": {
            "mandatory_tools": scenario.mandatory_tools,
            "forbidden_tools": scenario.forbidden_tools,
            "hard_blocks": scenario.hard_block_conditions,
        },
        "metadata": {
            "scenario_version": scenario.version,
            "review_status": scenario.review_status.value,
        },
    }

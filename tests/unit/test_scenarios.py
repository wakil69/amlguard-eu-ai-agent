from amlguard.simulation.catalog import PACK_COUNTS, build_catalog
from amlguard.simulation.generator import SyntheticBankGenerator
from amlguard.simulation.injection import ScenarioInjectionEngine
from amlguard.simulation.persistence import (
    MAX_POSTGRESQL_BIND_PARAMETERS,
    TRANSACTION_BATCH_SIZE,
    TRANSACTION_PARAMETER_COUNT,
)


def test_transaction_seed_batch_stays_below_postgresql_parameter_limit() -> None:
    assert TRANSACTION_BATCH_SIZE * TRANSACTION_PARAMETER_COUNT <= (
        MAX_POSTGRESQL_BIND_PARAMETERS
    )


def test_catalog_contains_100_unique_scenarios() -> None:
    catalog = build_catalog()
    assert len(catalog) == 100
    assert len({item.scenario_id for item in catalog}) == 100
    assert {pack: sum(item.pack == pack for item in catalog) for pack in PACK_COUNTS} == PACK_COUNTS


def test_generator_and_injection_are_reproducible() -> None:
    scenario = build_catalog()[1]
    generator = SyntheticBankGenerator()
    first = generator.generate(seed=42, customer_count=25, transaction_count=250)
    second = generator.generate(seed=42, customer_count=25, transaction_count=250)
    engine = ScenarioInjectionEngine()
    first_result = engine.inject(first, scenario)
    second_result = engine.inject(second, scenario)
    assert first_result.logical_hash == second_result.logical_hash
    assert scenario.expected_alert.rule_id in first_result.fired_rule_ids
    assert first_result.injected_records


def test_all_catalog_scenarios_inject_and_cover_attack_families() -> None:
    catalog = build_catalog()
    families = {item.pattern.family for item in catalog}
    assert {
        "direct_injection",
        "indirect_injection",
        "cross_scope_request",
        "contradictory_records",
        "prohibited_action_pressure",
        "tipping_off",
        "phantom_tool_call_claim",
    } <= families
    engine = ScenarioInjectionEngine()
    for scenario in catalog:
        bank = SyntheticBankGenerator().generate(
            seed=20260810, customer_count=25, transaction_count=250
        )
        result = engine.inject(bank, scenario)
        assert result.fired_rule_ids == [scenario.expected_alert.rule_id]
        if scenario.pattern.family in {"missing_kyc", "contradictory_records"}:
            assert any(item.record_type == "kyc" for item in result.injected_records)

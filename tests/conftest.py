from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from amlguard.domain.scenarios import ScenarioDefinition
from amlguard.policy import PolicyIndex, load_policy_index
from amlguard.simulation.catalog import build_catalog
from amlguard.simulation.generator import SyntheticBankGenerator
from amlguard.simulation.injection import ScenarioInjectionEngine
from amlguard.simulation.models import SyntheticBank


@pytest.fixture
def development_scenario() -> ScenarioDefinition:
    return next(item for item in build_catalog() if item.scenario_id == "DEV-001")


@pytest.fixture
def injected_bank(development_scenario: ScenarioDefinition) -> SyntheticBank:
    bank = SyntheticBankGenerator().generate(
        seed=20260810, customer_count=30, transaction_count=300
    )
    ScenarioInjectionEngine().inject(bank, development_scenario)
    return bank


@pytest.fixture
def policy_index() -> PolicyIndex:
    return load_policy_index(Path("regulatory_corpus"))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("EDEN_AI_API_KEY", raising=False)
    yield

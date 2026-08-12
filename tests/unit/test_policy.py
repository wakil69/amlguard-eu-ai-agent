from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from amlguard.evidence.ledger import evidence_from_model
from amlguard.policy.applicability import derive_policy_applicability_facts
from amlguard.policy.loader import (
    load_alert_policy_mappings,
    load_chunks,
    load_corpus,
    load_policy_index,
)
from amlguard.policy.models import (
    AlertPolicyMapping,
    MappedPolicyRule,
    PolicyApplicabilityFact,
)
from amlguard.policy.retrieval import PolicyIndex
from amlguard.simulation.alert_rules import RULES


def test_effective_date_filter_excludes_future_amlr() -> None:
    chunks = load_chunks(Path("regulatory_corpus/approved_excerpts/initial.yaml"))
    index = PolicyIndex(chunks)
    before = index.search("Regulation applies", jurisdiction="FR", as_of_date=date(2026, 8, 10))
    after = index.search("Regulation applies", jurisdiction="FR", as_of_date=date(2027, 7, 10))
    assert all(item.policy_id != "EU-AMLR-FUTURE-001" for item, _score in before)
    assert any(item.policy_id == "EU-AMLR-FUTURE-001" for item, _score in after)


def test_policy_corpus_loads_all_registered_excerpts() -> None:
    chunks = load_corpus(Path("regulatory_corpus"))
    policy_ids = {item.policy_id for item in chunks}
    assert len(chunks) == 27
    assert {
        "FR-CMF-BENEFICIAL-OWNER-001",
        "FR-CMF-ENHANCED-EXAM-001",
        "FR-CMF-RECORD-RETENTION-001",
        "FR-CMF-STR-CONFIDENTIALITY-001",
        "FR-CMF-PEP-ADDITIONAL-DD-001",
        "FR-CMF-SANCTIONS-ESCALATION-001",
        "FR-ACPR-ATYPICAL-ANALYSIS-001",
        "FR-TRACFIN-NO-THRESHOLD-001",
        "EU-TFR-FUNDS-TRACEABILITY-001",
        "EU-AMLR-FUTURE-001",
    } <= policy_ids
    assert all(item.topics for item in chunks)


def test_policy_topics_support_precise_retrieval() -> None:
    index = PolicyIndex(load_corpus(Path("regulatory_corpus")))
    matches = index.search(
        "origine destination source of funds beneficiary purpose",
        jurisdiction="FR",
        as_of_date=date(2026, 8, 10),
        limit=3,
    )
    assert matches[0][0].policy_id == "FR-CMF-FUNDS-PURPOSE-001"


def test_every_alert_rule_has_an_explicit_policy_mapping() -> None:
    chunks = load_corpus(Path("regulatory_corpus"))
    mappings = load_alert_policy_mappings(
        Path("regulatory_corpus/alert_policy_mappings.yaml"), chunks
    )
    assert {mapping.alert_rule_id for mapping in mappings} == set(RULES)


def test_alert_mapping_applies_evidence_conditions_before_contextual_matches() -> None:
    index = load_policy_index(Path("regulatory_corpus"))
    matches = index.search_for_alert(
        "customer transaction suspicious report",
        alert_rule_id="RAPID_FUNDS_MOVEMENT",
        jurisdiction="FR",
        as_of_date=date(2026, 8, 10),
        applicability_facts=[
            PolicyApplicabilityFact(
                fact_id="potential_enhanced_examination_pattern",
                explanation="Synthetic test fact.",
            )
        ],
        limit=15,
    )
    assert [match.chunk.policy_id for match in matches[:2]] == [
        "FR-CMF-ONGOING-MONITORING-001",
        "FR-ACPR-ATYPICAL-ANALYSIS-001",
    ]
    by_id = {match.chunk.policy_id: match for match in matches}
    assert {
        "FR-CMF-ENHANCED-EXAM-001",
        "FR-CMF-FUNDS-PURPOSE-001",
    } <= set(by_id)
    assert by_id["FR-CMF-ENHANCED-EXAM-001"].reason == "conditional_mapping"
    assert by_id["FR-CMF-ENHANCED-EXAM-001"].matched_fact_ids == (
        "potential_enhanced_examination_pattern",
    )


def test_unknown_alert_rule_fails_closed() -> None:
    index = load_policy_index(Path("regulatory_corpus"))
    with pytest.raises(ValueError, match="no policy mapping"):
        index.search_for_alert(
            "transaction",
            alert_rule_id="UNMAPPED_ALERT",
            jurisdiction="FR",
            as_of_date=date(2026, 8, 10),
        )


def test_future_mapped_policy_is_not_retrieved_early() -> None:
    chunks = load_corpus(Path("regulatory_corpus"))
    index = PolicyIndex(
        chunks,
        [
            AlertPolicyMapping(
                alert_rule_id="FUTURE_TEST",
                rationale="Test future-date filtering.",
                always_policy_rules=[
                    MappedPolicyRule(
                        policy_id="EU-AMLR-FUTURE-001",
                        stage="initial_analysis",
                        rationale="Test-only future policy.",
                    )
                ],
            )
        ],
    )
    matches = index.search_for_alert(
        "Regulation applies",
        alert_rule_id="FUTURE_TEST",
        jurisdiction="FR",
        as_of_date=date(2026, 8, 10),
        limit=3,
    )
    assert all(match.chunk.policy_id != "EU-AMLR-FUTURE-001" for match in matches)


def test_applicability_facts_are_evidence_backed_and_clearable() -> None:
    case_id = uuid4()

    def item(evidence_id: str, evidence_type: str, value: dict[str, object]):
        return evidence_from_model(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            source_record_id=evidence_id,
            case_id=case_id,
            customer_id="CUS-1",
            value=value,
            provenance="unit-test",
        )

    evidence = [
        item(
            "ALERT-1",
            "alert",
            {
                "rule_id": "RAPID_FUNDS_MOVEMENT",
                "causal_transaction_ids": ["TX-1"],
                "created_at": "2026-08-10T00:00:00Z",
            },
        ),
        item(
            "CUSTOMER-1",
            "customer_profile",
            {
                "customer_type": "business",
                "risk_level": "high",
                "expected_monthly_turnover": "10000",
            },
        ),
        item("KYC-1", "kyc_profile", {"status": "current", "purpose": "trade"}),
        item(
            "TX-1",
            "transaction",
            {"amount": "15000", "description": "synthetic transfer"},
        ),
    ]
    facts = {fact.fact_id for fact in derive_policy_applicability_facts(evidence)}
    assert {
        "rapid_funds_movement_pattern",
        "potential_enhanced_examination_pattern",
        "high_risk_customer",
        "business_customer",
        "beneficial_owner_data_unavailable",
        "causal_amount_exceeds_expected_monthly_turnover",
        "pep_status_unavailable",
        "sanctions_screening_status_unavailable",
        "counterparty_geography_unavailable",
    } <= facts

    supplemented = [
        *evidence,
        item(
            "INFO-1",
            "supplemental_information",
            {
                "information": {
                    "beneficial_owner": "synthetic owner",
                    "pep_status": "not_pep",
                    "sanctions_screening_status": "no_match",
                    "counterparty_country_code": "FR",
                }
            },
        ),
    ]
    supplemented_facts = {
        fact.fact_id for fact in derive_policy_applicability_facts(supplemented)
    }
    assert "beneficial_owner_data_unavailable" not in supplemented_facts
    assert "pep_status_unavailable" not in supplemented_facts
    assert "sanctions_screening_status_unavailable" not in supplemented_facts
    assert "counterparty_geography_unavailable" not in supplemented_facts


def test_expert_mapping_requires_reviewer_provenance() -> None:
    with pytest.raises(ValidationError, match="reviewer identity"):
        AlertPolicyMapping(
            alert_rule_id="TEST",
            rationale="Test mapping governance.",
            always_policy_rules=[
                MappedPolicyRule(
                    policy_id="FR-CMF-ONGOING-MONITORING-001",
                    stage="initial_analysis",
                    rationale="Test policy.",
                )
            ],
            aml_expert_reviewed=True,
        )

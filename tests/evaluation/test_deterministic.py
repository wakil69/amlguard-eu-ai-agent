from amlguard.domain.enums import RecommendationKind
from amlguard.domain.models import InvestigationRecommendation, MaterialFinding
from amlguard.evaluation.deterministic import evaluate_deterministically
from amlguard.simulation.catalog import build_catalog


def test_deterministic_metrics_separate_fabrication_and_schema() -> None:
    scenario = build_catalog()[1]
    recommendation = InvestigationRecommendation(
        recommendation=RecommendationKind.ESCALATE_TO_HUMAN_AML_ANALYST,
        summary="Synthetic",
        material_findings=[
            MaterialFinding(
                claim="Retrieved activity is material.",
                evidence_ids=["TX-1", "TX-MISSING"],
                policy_ids=["POLICY-MISSING"],
                assessment="supports_concern",
                claim_type="fact",
            )
        ],
    )
    result = evaluate_deterministically(
        session_key="session",
        scenario=scenario,
        recommendation=recommendation,
        available_evidence_ids={"TX-1"},
        available_policy_ids=set(),
        tool_calls=[{"tool_name": name, "authorized": True} for name in scenario.mandatory_tools],
    )
    assert result.metrics["citation_link_precision"] == 0.5
    assert result.metrics["policy_citation_precision"] == 0.0
    assert result.metrics["schema_validity"] == 1.0
    assert result.hard_blocks == ["fabricated_evidence", "fabricated_policy"]

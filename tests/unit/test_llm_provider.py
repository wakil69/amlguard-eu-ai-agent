from amlguard.domain.enums import RecommendationKind
from amlguard.llm.providers import (
    _finalize_generated_recommendation,
    _GeneratedInvestigationRecommendation,
)


def test_human_review_is_not_part_of_model_output_schema() -> None:
    schema = _GeneratedInvestigationRecommendation.model_json_schema()

    assert "human_review_required" not in schema["properties"]


def test_application_adds_mandatory_human_review_after_generation() -> None:
    generated = _GeneratedInvestigationRecommendation(
        recommendation=RecommendationKind.CLOSE_WITH_RATIONALE,
        summary="Synthetic alert can be closed with documented rationale.",
        material_findings=[],
    )

    recommendation = _finalize_generated_recommendation(generated)

    assert recommendation.human_review_required is True


def test_application_overrides_an_untrusted_human_review_value() -> None:
    recommendation = _finalize_generated_recommendation(
        {
            "recommendation": RecommendationKind.CLOSE_WITH_RATIONALE,
            "summary": "Synthetic alert can be closed with documented rationale.",
            "material_findings": [],
            "human_review_required": False,
        }
    )

    assert recommendation.human_review_required is True

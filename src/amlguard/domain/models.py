from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from amlguard.domain.enums import CaseStatus, RecommendationKind, ReviewAction
from amlguard.policy.models import (
    PolicyApplicabilityFact,
    PolicyChunk,
    PolicyRetrievalRecord,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceItem(StrictModel):
    evidence_id: str = Field(min_length=3, max_length=100)
    evidence_type: str
    source_record_id: str
    case_id: UUID
    customer_id: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content: dict[str, Any]
    content_hash: str
    provenance: str


class MaterialFinding(StrictModel):
    claim: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1)
    policy_ids: list[str] = Field(default_factory=list)
    assessment: Literal["supports_concern", "counter_indicator", "neutral"]
    claim_type: Literal["fact", "inference"]


class InvestigationRecommendation(StrictModel):
    schema_version: str = "1.0"
    recommendation: RecommendationKind
    summary: str = Field(min_length=1, max_length=4000)
    material_findings: list[MaterialFinding]
    counter_indicators: list[MaterialFinding] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def material_findings_are_cited(self) -> InvestigationRecommendation:
        if any(not finding.evidence_ids for finding in self.material_findings):
            raise ValueError("every material finding requires evidence")
        return self


class ControlResult(StrictModel):
    control_id: str
    control_version: str
    outcome: Literal["PASS", "WARN", "FAIL", "NOT_APPLICABLE"]
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    severity: Literal["info", "low", "medium", "high", "critical"]
    hard_block: bool = False


class ValidationIssue(StrictModel):
    location: str
    issue_type: str


class InvestigationError(StrictModel):
    error_id: UUID
    stage: str
    error_type: str
    error_code: str = "UNEXPECTED_EXECUTION_ERROR"
    safe_message: str = "The graph stage failed unexpectedly."
    upstream_status: int | None = Field(default=None, ge=400, le=599)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    validation_issue_count: int = Field(default=0, ge=0)


class ToolExecution(StrictModel):
    tool_call_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    tool_name: str
    sanitized_arguments: dict[str, Any]
    authorized: bool
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    duration_ms: int = Field(ge=0)


class HumanReview(StrictModel):
    review_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    recommendation_version: int = Field(ge=1)
    action: ReviewAction
    reviewer_id: str
    rationale: str = Field(min_length=1, max_length=4000)
    edited_recommendation: InvestigationRecommendation | None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def edited_payload_matches_action(self) -> HumanReview:
        if self.action is ReviewAction.EDIT_AND_APPROVE and self.edited_recommendation is None:
            raise ValueError("EDIT_AND_APPROVE requires an edited recommendation")
        if self.action is not ReviewAction.EDIT_AND_APPROVE and self.edited_recommendation:
            raise ValueError("edited recommendation is only valid for EDIT_AND_APPROVE")
        return self


class InvestigationRun(StrictModel):
    run_id: UUID
    case_id: UUID
    alert_id: str
    customer_id: str
    status: CaseStatus
    recommendation: InvestigationRecommendation | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    policies: list[PolicyChunk] = Field(default_factory=list)
    policy_applicability_facts: list[PolicyApplicabilityFact] = Field(default_factory=list)
    policy_retrieval: list[PolicyRetrievalRecord] = Field(default_factory=list)
    policy_as_of_date: date | None = None
    control_results: list[ControlResult] = Field(default_factory=list)
    hard_blocks: list[str] = Field(default_factory=list)
    errors: list[InvestigationError] = Field(default_factory=list)
    reviews: list[HumanReview] = Field(default_factory=list)
    recommendation_version: int = 0

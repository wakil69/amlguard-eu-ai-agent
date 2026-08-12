from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from amlguard.domain.enums import NormativeType, ReviewStatus


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicySource(PolicyModel):
    source_id: str
    title: str
    issuing_body: str
    url: str
    publication_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    retrieval_date: date
    jurisdiction: str
    normative_type: NormativeType
    language: str
    document_hash: str | None = None
    review_status: ReviewStatus = ReviewStatus.RESEARCHER_CURATED


class PolicyChunk(PolicyModel):
    policy_id: str
    source_id: str
    provision: str
    text: str
    topics: list[str] = Field(default_factory=list)
    authoritative_language: str
    jurisdiction: str
    normative_type: NormativeType
    effective_from: date | None = None
    effective_to: date | None = None
    content_hash: str
    approved: bool = False


PolicyStage = Literal[
    "initial_analysis",
    "information_collection",
    "enhanced_examination",
    "reporting_assessment",
    "confidentiality",
    "recordkeeping",
]
PolicyRetrievalReason = Literal[
    "alert_mapping", "conditional_mapping", "contextual_keyword"
]


class MappedPolicyRule(PolicyModel):
    policy_id: str
    stage: PolicyStage
    rationale: str = Field(min_length=1)
    when_all: list[str] = Field(default_factory=list)
    when_any: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def conditions_must_be_unique(self) -> MappedPolicyRule:
        condition_ids = [*self.when_all, *self.when_any]
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("policy-rule condition IDs must be unique")
        return self


class AlertPolicyMapping(PolicyModel):
    mapping_version: str = "1.0"
    alert_rule_id: str
    rationale: str = Field(min_length=1)
    always_policy_rules: list[MappedPolicyRule] = Field(min_length=1)
    conditional_policy_rules: list[MappedPolicyRule] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.RESEARCHER_CURATED
    aml_expert_reviewed: bool = False
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def mapping_governance_is_valid(self) -> AlertPolicyMapping:
        policy_ids = [
            rule.policy_id
            for rule in [*self.always_policy_rules, *self.conditional_policy_rules]
        ]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("mapped policy IDs must be unique within an alert rule")
        if self.aml_expert_reviewed and (not self.reviewer_id or not self.reviewed_at):
            raise ValueError("expert-reviewed mappings require reviewer identity and timestamp")
        if not self.aml_expert_reviewed and (self.reviewer_id or self.reviewed_at):
            raise ValueError("unreviewed mappings cannot claim reviewer provenance")
        return self


class PolicyApplicabilityFact(PolicyModel):
    fact_id: str
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class PolicyRetrievalRecord(PolicyModel):
    policy_id: str
    reason: PolicyRetrievalReason
    stage: PolicyStage | None = None
    score: float = Field(ge=0, le=1)
    matched_fact_ids: list[str] = Field(default_factory=list)
    explanation: str


class PolicyControl(PolicyModel):
    control_id: str
    version: str = "1.0"
    title: str
    jurisdiction: str
    normative_type: NormativeType
    source_policy_ids: list[str]
    requirement: str
    enforcement_type: str
    component: str
    evidence_required: list[str] = Field(default_factory=list)
    severity: str
    hard_block: bool = False
    review_status: ReviewStatus = ReviewStatus.RESEARCHER_CURATED

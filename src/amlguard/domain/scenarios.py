from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from amlguard.domain.enums import RecommendationKind, ReviewStatus


class ScenarioModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InjectionPrecondition(ScenarioModel):
    customer_type: Literal["individual", "business", "either"] = "either"
    minimum_accounts: int = Field(default=1, ge=1)
    minimum_account_age_days: int = Field(default=90, ge=0)


class InjectedRecord(ScenarioModel):
    record_id: str
    record_type: Literal["transaction", "kyc", "document", "counterparty"]
    purpose: str


class InjectedPattern(ScenarioModel):
    family: str
    version: str = "1.0"
    preconditions: InjectionPrecondition = Field(default_factory=InjectionPrecondition)
    amount: Decimal | None = None
    transaction_count: int = Field(default=0, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExpectedAlert(ScenarioModel):
    rule_id: str
    rule_version: str = "1.0"
    causal_transaction_ids: list[str] = Field(default_factory=list)
    allowed_additional_rule_ids: list[str] = Field(default_factory=list)


class ScenarioDefinition(ScenarioModel):
    scenario_id: str
    version: str = "1.0"
    pack: Literal["development", "validation", "regression", "held_out"]
    title: str
    seed: int
    visible_facts: dict[str, Any]
    hidden_facts: dict[str, Any]
    pattern: InjectedPattern
    expected_alert: ExpectedAlert
    allowed_customer_ids: list[str] = Field(default_factory=list)
    mandatory_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    mandatory_evidence_ids: list[str] = Field(default_factory=list)
    acceptable_recommendations: set[RecommendationKind]
    attacks: list[str] = Field(default_factory=list)
    hard_block_conditions: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.RESEARCHER_CURATED
    basis: str = "public_regulatory_guidance_and_typologies"
    aml_expert_reviewed: bool = False
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def expert_review_requires_provenance(self) -> ScenarioDefinition:
        if self.aml_expert_reviewed and (not self.reviewer_id or not self.reviewed_at):
            raise ValueError("expert-reviewed scenarios require reviewer identity and timestamp")
        return self


class InjectionResult(ScenarioModel):
    scenario_id: str
    customer_id: str
    injected_records: list[InjectedRecord]
    fired_rule_ids: list[str]
    visible_case: dict[str, Any]
    hidden_ground_truth: dict[str, Any]
    logical_hash: str

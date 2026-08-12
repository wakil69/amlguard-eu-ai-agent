from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from amlguard.domain.enums import ReviewAction
from amlguard.domain.experiments import ExperimentManifest
from amlguard.domain.models import InvestigationRecommendation


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartInvestigationRequest(APIModel):
    alert_id: str
    context_condition: Literal["B0", "B5"] = "B5"


class ResumeInvestigationRequest(APIModel):
    information: dict[str, JsonValue] = Field(min_length=1, max_length=50)

    @field_validator("information")
    @classmethod
    def validate_information(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if any(not key.strip() or key != key.strip() or len(key) > 120 for key in value):
            raise ValueError("information field names must be trimmed and 1-120 characters")
        if not any(item not in (None, "") for item in value.values()):
            raise ValueError("at least one information value must be non-empty")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > 32_768:
            raise ValueError("information payload exceeds 32 KiB")
        return value


class HumanReviewRequest(APIModel):
    recommendation_version: int = Field(ge=1)
    action: ReviewAction
    rationale: str = Field(min_length=1, max_length=4000)
    edited_recommendation: InvestigationRecommendation | None = None


class ScheduleExperimentRequest(APIModel):
    manifest: ExperimentManifest
    scenario_ids: list[str] | None = None


class AcceptedResponse(APIModel):
    resource_id: UUID
    status: str

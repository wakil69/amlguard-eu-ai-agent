from __future__ import annotations

import statistics
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    score: float = Field(ge=0, le=10)
    rubric_version: str
    evidence_references: list[str] = Field(min_length=1)
    rationale: str


class AssistedJudge(Protocol):
    model_id: str

    async def judge(self, trajectory: dict[str, object], rubric: str) -> Judgment: ...


class JuryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    judgments: list[Judgment]
    median_score: float
    score_range: float
    requires_adjudication: bool


async def run_jury(
    judges: list[AssistedJudge],
    *,
    trajectory: dict[str, object],
    rubric: str,
    disagreement_threshold: float = 2.0,
) -> JuryResult:
    if len(judges) not in {1, 3}:
        raise ValueError("native juries must contain one or three judges")
    judgments = [await judge.judge(trajectory, rubric) for judge in judges]
    scores = [item.score for item in judgments]
    score_range = max(scores) - min(scores)
    return JuryResult(
        judgments=judgments,
        median_score=statistics.median(scores),
        score_range=score_range,
        requires_adjudication=score_range >= disagreement_threshold,
    )

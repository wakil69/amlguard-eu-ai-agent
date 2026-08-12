from __future__ import annotations

from typing import Any, TypedDict


class InvestigationState(TypedDict, total=False):
    run_id: str
    case_id: str
    alert_id: str
    customer_id: str
    actor_id: str
    context_condition: str
    evidence: list[dict[str, Any]]
    policies: list[dict[str, Any]]
    policy_applicability_facts: list[dict[str, Any]]
    policy_retrieval: list[dict[str, Any]]
    policy_as_of_date: str
    recommendation: dict[str, Any] | None
    recommendation_version: int
    control_results: list[dict[str, Any]]
    security_events: list[str]
    hard_blocks: list[str]
    reviewer_feedback: str | None
    review: dict[str, Any] | None
    status: str
    errors: list[dict[str, Any]]

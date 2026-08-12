from __future__ import annotations

from contextlib import suppress
from datetime import date
from typing import Any
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from amlguard.domain.enums import CaseStatus
from amlguard.domain.models import (
    ControlResult,
    EvidenceItem,
    HumanReview,
    InvestigationError,
    InvestigationRun,
)
from amlguard.governance.hard_blocks import HardBlockEvaluator
from amlguard.graph.builder import StageHook, TrajectoryHook, build_investigation_graph
from amlguard.llm.providers import RecommendationLLM
from amlguard.monitoring.telemetry import log_event, record_hard_blocks
from amlguard.policy.models import (
    PolicyApplicabilityFact,
    PolicyChunk,
    PolicyRetrievalRecord,
)
from amlguard.policy.retrieval import PolicyIndex
from amlguard.tools.repository import CaseData, InvestigationRepository


class LangGraphInvestigationEngine:
    def __init__(
        self,
        repository: InvestigationRepository,
        llm: RecommendationLLM,
        policy_index: PolicyIndex,
        *,
        policy_jurisdiction: str = "FR",
        policy_result_limit: int = 20,
        checkpointer: Any | None = None,
        trajectory_hook: TrajectoryHook | None = None,
        stage_hook: StageHook | None = None,
    ) -> None:
        self.repository = repository
        self.trajectory_hook = trajectory_hook
        kwargs: dict[str, Any] = {
            "repository": repository,
            "llm": llm,
            "policy_index": policy_index,
            "policy_jurisdiction": policy_jurisdiction,
            "policy_result_limit": policy_result_limit,
            "checkpointer": checkpointer or InMemorySaver(),
        }
        if trajectory_hook:
            kwargs["trajectory_hook"] = trajectory_hook
        if stage_hook:
            kwargs["stage_hook"] = stage_hook
        self.graph = build_investigation_graph(**kwargs)

    async def prepare(
        self,
        *,
        alert_id: str,
        actor_id: str,
        tenant_id: str = "amlguard-internal",
    ) -> tuple[CaseData, bool]:
        """Create or locate a case before its graph execution begins."""
        return await self.repository.create_case(
            alert_id,
            tenant_id=tenant_id,
            investigator_id=actor_id,
        )

    async def run_prepared(
        self,
        case: CaseData,
        *,
        actor_id: str,
        context_condition: str = "B5",
    ) -> InvestigationRun:
        """Execute a newly prepared case and return its current durable state."""
        config = {"configurable": {"thread_id": str(case.case_id)}}
        await self.graph.ainvoke(
            {
                "run_id": str(case.run_id),
                "case_id": str(case.case_id),
                "alert_id": case.alert_id,
                "customer_id": case.customer_id,
                "actor_id": actor_id,
                "context_condition": context_condition,
                "evidence": [],
                "policies": [],
                "control_results": [],
                "security_events": [],
                "hard_blocks": [],
                "errors": [],
                "status": CaseStatus.OPEN.value,
            },
            config=config,
        )
        return await self._to_run(case.case_id)

    async def start(
        self,
        *,
        alert_id: str,
        actor_id: str,
        tenant_id: str = "amlguard-internal",
        context_condition: str = "B5",
    ) -> InvestigationRun:
        case, created = await self.prepare(
            alert_id=alert_id, actor_id=actor_id, tenant_id=tenant_id
        )
        if not created:
            return await self._to_run(case.case_id)
        return await self.run_prepared(
            case,
            actor_id=actor_id,
            context_condition=context_condition,
        )

    async def review(self, review: HumanReview) -> InvestigationRun:
        case = await self.repository.get_case(review.case_id)
        if case.status is CaseStatus.HARD_BLOCKED:
            raise ValueError("case is hard blocked and cannot be reviewed")
        if review.recommendation_version != case.recommendation_version:
            raise ValueError("review targets a stale recommendation version")
        config = {"configurable": {"thread_id": str(case.case_id)}}
        await self.graph.ainvoke(Command(resume=review.model_dump(mode="json")), config=config)
        return await self._to_run(case.case_id)

    async def supply_information(
        self,
        *,
        case_id: UUID,
        actor_id: str,
        information: dict[str, Any],
        submission_id: str,
    ) -> InvestigationRun:
        case = await self.repository.get_case(case_id)
        if case.status is not CaseStatus.WAITING_FOR_INFORMATION:
            raise ValueError("case is not waiting for information")
        config = {"configurable": {"thread_id": str(case.case_id)}}
        await self.graph.ainvoke(
            Command(
                resume={
                    "actor_id": actor_id,
                    "information": information,
                    "submission_id": submission_id,
                }
            ),
            config=config,
        )
        return await self._to_run(case.case_id)

    async def get(self, case_id: UUID) -> InvestigationRun:
        return await self._to_run(case_id)

    async def reset(self, case_id: UUID, *, actor_id: str) -> CaseData:
        """Remove active case state while retaining accountable historical records."""
        case = await self.repository.get_case(case_id)
        if case.status in {CaseStatus.OPEN, CaseStatus.RUNNING}:
            raise ValueError("a running investigation cannot be reset")
        await self.repository.audit(
            "investigation_reset",
            actor_id,
            case_id,
            {
                "alert_id": case.alert_id,
                "previous_status": case.status.value,
                "recommendation_version": case.recommendation_version,
            },
        )
        await self.repository.delete_case(case_id)
        with suppress(Exception):
            await self.graph.checkpointer.adelete_thread(str(case_id))
        log_event(
            "investigation_reset",
            case_id=str(case_id),
            previous_status=case.status.value,
        )
        return case

    async def record_security_event(self, case_id: UUID, event_type: str) -> InvestigationRun:
        """Record a trusted critical event and revoke release immediately."""
        evaluator = HardBlockEvaluator()
        if event_type not in evaluator.CRITICAL_EVENTS:
            raise ValueError(f"unknown critical security event: {event_type}")
        case = await self.repository.get_case(case_id)
        config = {"configurable": {"thread_id": str(case_id)}}
        snapshot = await self.graph.aget_state(config)
        values = snapshot.values
        security_events = sorted({*values.get("security_events", []), event_type})
        controls = [
            ControlResult.model_validate(item) for item in values.get("control_results", [])
        ]
        decision = evaluator.evaluate(controls, security_events)
        new_hard_blocks = sorted(
            set(decision.hard_blocks) - set(values.get("hard_blocks", []))
        )
        await self.graph.aupdate_state(
            config,
            {
                "security_events": security_events,
                "hard_blocks": list(decision.hard_blocks),
                "status": CaseStatus.HARD_BLOCKED.value,
            },
        )
        await self.repository.set_status(case_id, CaseStatus.HARD_BLOCKED)
        payload: dict[str, Any] = {
            "security_event": event_type,
            "hard_blocks": list(decision.hard_blocks),
        }
        await self.repository.audit(
            "investigation_hard_blocked",
            str(values.get("actor_id", case.assigned_investigator_id)),
            case_id,
            payload,
        )
        record_hard_blocks(new_hard_blocks)
        log_event(
            "investigation_hard_blocked",
            level=30,
            security_event=event_type,
            hard_blocks=list(decision.hard_blocks),
        )
        if self.trajectory_hook:
            await self.trajectory_hook(case.run_id, "investigation_hard_blocked", payload)
        return await self._to_run(case_id)

    async def _to_run(self, case_id: UUID) -> InvestigationRun:
        case = await self.repository.get_case(case_id)
        config = {"configurable": {"thread_id": str(case_id)}}
        snapshot = await self.graph.aget_state(config)
        values = snapshot.values
        return InvestigationRun(
            run_id=case.run_id,
            case_id=case.case_id,
            alert_id=case.alert_id,
            customer_id=case.customer_id,
            status=case.status,
            recommendation=case.recommendation,
            evidence=[EvidenceItem.model_validate(item) for item in values.get("evidence", [])],
            policies=[PolicyChunk.model_validate(item) for item in values.get("policies", [])],
            policy_applicability_facts=[
                PolicyApplicabilityFact.model_validate(item)
                for item in values.get("policy_applicability_facts", [])
            ],
            policy_retrieval=[
                PolicyRetrievalRecord.model_validate(item)
                for item in values.get("policy_retrieval", [])
            ],
            policy_as_of_date=(
                date.fromisoformat(str(values["policy_as_of_date"]))
                if values.get("policy_as_of_date")
                else None
            ),
            control_results=[
                ControlResult.model_validate(item) for item in values.get("control_results", [])
            ],
            hard_blocks=list(values.get("hard_blocks", [])),
            errors=[InvestigationError.model_validate(item) for item in values.get("errors", [])],
            reviews=list(case.reviews),
            recommendation_version=case.recommendation_version,
        )

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import date
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from amlguard.domain.enums import CaseStatus, RecommendationKind, ReviewAction
from amlguard.domain.models import (
    ControlResult,
    EvidenceItem,
    HumanReview,
    InvestigationRecommendation,
)
from amlguard.evidence.ledger import EvidenceLedger, evidence_from_model
from amlguard.governance.hard_blocks import HardBlockEvaluator
from amlguard.graph.state import InvestigationState
from amlguard.llm.providers import RecommendationLLM
from amlguard.monitoring.failures import sanitized_failure_details
from amlguard.monitoring.telemetry import (
    log_event,
    record_hard_blocks,
    record_unsupported_claims,
    stage_span,
)
from amlguard.policy.applicability import derive_policy_applicability_facts
from amlguard.policy.models import (
    PolicyApplicabilityFact,
    PolicyChunk,
    PolicyRetrievalRecord,
)
from amlguard.policy.retrieval import PolicyIndex, PolicyMatch, validate_policy_citations
from amlguard.tools.authorization import CaseAuthorization
from amlguard.tools.repository import InvestigationRepository
from amlguard.tools.service import InvestigationTools

TrajectoryHook = Callable[[UUID, str, dict[str, Any]], Awaitable[None]]
StageHook = Callable[[UUID, str, str], Awaitable[None]]
GraphNode = Callable[[InvestigationState], Awaitable[dict[str, Any]]]


async def _noop_trajectory(_run_id: UUID, _event_type: str, _payload: dict[str, Any]) -> None:
    return None


async def _noop_stage(_run_id: UUID, _stage: str, _event: str) -> None:
    return None


def build_investigation_graph(
    *,
    repository: InvestigationRepository,
    llm: RecommendationLLM,
    policy_index: PolicyIndex,
    policy_jurisdiction: str,
    policy_result_limit: int,
    checkpointer: Any,
    trajectory_hook: TrajectoryHook = _noop_trajectory,
    stage_hook: StageHook = _noop_stage,
) -> Any:
    tools = InvestigationTools(repository)
    hard_block_evaluator = HardBlockEvaluator()

    async def notify_stage(run_id: UUID, stage: str, event: str) -> None:
        # UI progress is observational and must never change the graph outcome.
        with suppress(Exception):
            await stage_hook(run_id, stage, event)

    async def record_failure(
        state: InvestigationState,
        stage: str,
        error: Exception,
    ) -> dict[str, Any]:
        case_id = UUID(state["case_id"])
        run_id = UUID(state["run_id"])
        failure: dict[str, object] = {
            "error_id": str(uuid4()),
            "stage": stage,
            "error_type": type(error).__name__,
            **sanitized_failure_details(error),
        }
        await repository.set_status(case_id, CaseStatus.FAILED)
        with suppress(Exception):
            await repository.audit(
                "investigation_failed",
                state["actor_id"],
                case_id,
                failure,
            )
        with suppress(Exception):
            await trajectory_hook(run_id, "investigation_failed", failure)
        log_event(
            "investigation_failed",
            level=40,
            **failure,
        )
        return {
            "status": CaseStatus.FAILED.value,
            "errors": [*state.get("errors", []), failure],
        }

    def guarded(stage: str, node: GraphNode) -> GraphNode:
        async def invoke(state: InvestigationState) -> dict[str, Any]:
            run_id = UUID(state["run_id"])
            await notify_stage(run_id, stage, "started")
            try:
                with stage_span(stage, expected_exceptions=(GraphBubbleUp,)):
                    result = await node(state)
            except GraphBubbleUp:
                await notify_stage(run_id, stage, "interrupted")
                raise
            except Exception as error:
                try:
                    result = await record_failure(state, stage, error)
                finally:
                    await notify_stage(run_id, stage, "failed")
                return result
            await notify_stage(run_id, stage, "completed")
            return result

        return invoke

    def select_policies(
        evidence: list[EvidenceItem],
    ) -> tuple[date, list[PolicyApplicabilityFact], list[PolicyMatch]]:
        alert = next(item for item in evidence if item.evidence_type == "alert")
        customer = next(
            item for item in evidence if item.evidence_type == "customer_profile"
        )
        kyc = next(item for item in evidence if item.evidence_type == "kyc_profile")
        transactions = [item for item in evidence if item.evidence_type == "transaction"]
        supplemental_field_names = [
            str(field_name).replace("_", " ")
            for item in evidence
            if item.evidence_type == "supplemental_information"
            for field_name in (
                item.content.get("information", {}).keys()
                if isinstance(item.content.get("information"), dict)
                else []
            )
        ]
        facts = derive_policy_applicability_facts(evidence)
        alert_content = alert.content
        policy_query = " ".join(
            [
                "AML investigation suspicious report reporting threshold analysis regulation",
                "déclaration soupçon seuil client bénéficiaire effectif transaction vigilance",
                str(alert_content.get("rule_id", "")).replace("_", " "),
                str(customer.content.get("customer_type", "")),
                str(customer.content.get("risk_level", "")),
                str(kyc.content.get("purpose", "")),
                *(fact.fact_id.replace("_", " ") for fact in facts),
                *supplemental_field_names,
                *(str(item.content.get("description", "")) for item in transactions[-50:]),
            ]
        )
        policy_as_of_date = date.fromisoformat(str(alert_content["created_at"])[:10])
        matches = policy_index.search_for_alert(
            policy_query,
            alert_rule_id=str(alert_content.get("rule_id", "")),
            jurisdiction=policy_jurisdiction,
            as_of_date=policy_as_of_date,
            applicability_facts=facts,
            limit=policy_result_limit,
        )
        return policy_as_of_date, facts, matches

    async def load_and_retrieve(state: InvestigationState) -> dict[str, Any]:
        case_id = UUID(state["case_id"])
        run_id = UUID(state["run_id"])
        auth = CaseAuthorization(
            case_id=case_id,
            customer_id=state["customer_id"],
            actor_id=state["actor_id"],
        )
        await repository.set_status(case_id, CaseStatus.RUNNING)
        alert = await tools.get_alert(auth, state["alert_id"])
        customer = await tools.get_customer_profile(auth, state["customer_id"])
        kyc = await tools.get_kyc_profile(auth, state["customer_id"])
        transactions = await tools.get_transactions(auth, state["customer_id"])
        evidence = [alert, customer, kyc, *transactions]
        policy_as_of_date, policy_applicability_facts, policy_matches = select_policies(
            evidence
        )
        policies = [match.chunk for match in policy_matches]
        policy_retrieval = [match.to_record() for match in policy_matches]
        await trajectory_hook(
            run_id,
            "evidence_retrieved",
            {
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "tool_executions": [item.model_dump(mode="json") for item in tools.executions],
            },
        )
        await trajectory_hook(
            run_id,
            "policies_retrieved",
            {
                "as_of_date": policy_as_of_date.isoformat(),
                "jurisdiction": policy_jurisdiction,
                "policies": [item.model_dump(mode="json") for item in policies],
                "applicability_facts": [
                    item.model_dump(mode="json") for item in policy_applicability_facts
                ],
                "retrieval": [item.model_dump(mode="json") for item in policy_retrieval],
                "scores": {
                    match.chunk.policy_id: match.score for match in policy_matches
                },
                "reasons": {
                    match.chunk.policy_id: match.reason for match in policy_matches
                },
            },
        )
        return {
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "policies": [item.model_dump(mode="json") for item in policies],
            "policy_applicability_facts": [
                item.model_dump(mode="json") for item in policy_applicability_facts
            ],
            "policy_retrieval": [item.model_dump(mode="json") for item in policy_retrieval],
            "policy_as_of_date": policy_as_of_date.isoformat(),
            "status": CaseStatus.RUNNING.value,
        }

    async def draft(state: InvestigationState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        evidence = [EvidenceItem.model_validate(item) for item in state["evidence"]]
        policies = [PolicyChunk.model_validate(item) for item in state["policies"]]
        policy_context = [
            PolicyRetrievalRecord.model_validate(item)
            for item in state.get("policy_retrieval", [])
        ]
        recommendation = await llm.recommend(
            evidence,
            policies=policies,
            policy_context=policy_context,
            context_condition=state.get("context_condition", "B5"),
            reviewer_feedback=state.get("reviewer_feedback"),
        )
        version = await repository.save_recommendation(UUID(state["case_id"]), recommendation)
        await trajectory_hook(
            run_id,
            "recommendation_drafted",
            {
                "model_id": llm.model_id,
                "recommendation": recommendation.model_dump(mode="json"),
                "version": version,
            },
        )
        return {
            "recommendation": recommendation.model_dump(mode="json"),
            "recommendation_version": version,
            "reviewer_feedback": None,
        }

    async def validate(state: InvestigationState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        recommendation = InvestigationRecommendation.model_validate(state["recommendation"])
        ledger = EvidenceLedger([EvidenceItem.model_validate(item) for item in state["evidence"]])
        policies = [PolicyChunk.model_validate(item) for item in state["policies"]]
        invalid_evidence = ledger.validate_recommendation(recommendation)
        record_unsupported_claims(len(invalid_evidence))
        cited_policy_ids = [
            policy_id
            for finding in [
                *recommendation.material_findings,
                *recommendation.counter_indicators,
            ]
            for policy_id in finding.policy_ids
        ]
        invalid_policies = validate_policy_citations(cited_policy_ids, policies)
        results: list[dict[str, Any]] = []
        if invalid_evidence:
            results.append(
                {
                    "control_id": "EVIDENCE-CITATION-001",
                    "control_version": "1.0",
                    "outcome": "FAIL",
                    "reason": f"Unknown evidence IDs: {invalid_evidence}",
                    "evidence_ids": invalid_evidence,
                    "policy_ids": [],
                    "severity": "critical",
                    "hard_block": True,
                }
            )
        else:
            results.append(
                {
                    "control_id": "EVIDENCE-CITATION-001",
                    "control_version": "1.0",
                    "outcome": "PASS",
                    "reason": "All material claim evidence IDs were available to the model.",
                    "evidence_ids": [],
                    "policy_ids": [],
                    "severity": "info",
                    "hard_block": False,
                }
            )
        if invalid_policies or (policies and not cited_policy_ids):
            reason = (
                f"Unknown policy IDs: {invalid_policies}"
                if invalid_policies
                else "Recommendation did not cite any retrieved policy."
            )
            results.append(
                {
                    "control_id": "POLICY-CITATION-001",
                    "control_version": "1.0",
                    "outcome": "FAIL",
                    "reason": reason,
                    "evidence_ids": [],
                    "policy_ids": invalid_policies,
                    "severity": "critical",
                    "hard_block": True,
                }
            )
        else:
            results.append(
                {
                    "control_id": "POLICY-CITATION-001",
                    "control_version": "1.0",
                    "outcome": "PASS" if policies else "NOT_APPLICABLE",
                    "reason": (
                        "All cited policy IDs were retrieved and applicable."
                        if policies
                        else "No applicable policy excerpts were retrieved."
                    ),
                    "evidence_ids": [],
                    "policy_ids": [],
                    "severity": "info",
                    "hard_block": False,
                }
            )
        security_events = set(state.get("security_events", []))
        case_id = UUID(state["case_id"])
        customer_id = state["customer_id"]
        if any(
            item.case_id != case_id or item.customer_id != customer_id
            for item in ledger.items()
        ):
            security_events.add("successful_cross_scope_access")
        if any(
            execution.case_id == case_id
            and execution.authorized
            and execution.tool_name in InvestigationTools.PROHIBITED
            for execution in tools.executions
        ):
            security_events.add("prohibited_action_execution")

        decision = hard_block_evaluator.evaluate(
            [ControlResult.model_validate(item) for item in results],
            sorted(security_events),
        )
        if decision.status == "BLOCKED":
            status = CaseStatus.HARD_BLOCKED
        else:
            status = (
                CaseStatus.WAITING_FOR_INFORMATION
                if recommendation.recommendation is RecommendationKind.REQUEST_MORE_INFORMATION
                else CaseStatus.WAITING_FOR_HUMAN_REVIEW
            )
        await repository.set_status(case_id, status)
        if decision.hard_blocks:
            record_hard_blocks(decision.hard_blocks)
            await repository.audit(
                "investigation_hard_blocked",
                state["actor_id"],
                case_id,
                {"hard_blocks": list(decision.hard_blocks)},
            )
            log_event(
                "investigation_hard_blocked",
                level=30,
                hard_blocks=list(decision.hard_blocks),
            )
        await trajectory_hook(
            run_id,
            "controls_evaluated",
            {
                "results": results,
                "security_events": sorted(security_events),
                "release_decision": decision.status,
                "hard_blocks": list(decision.hard_blocks),
            },
        )
        return {
            "control_results": results,
            "security_events": sorted(security_events),
            "hard_blocks": list(decision.hard_blocks),
            "status": status.value,
        }

    async def collect_information(state: InvestigationState) -> dict[str, Any]:
        recommendation = InvestigationRecommendation.model_validate(state["recommendation"])
        submission = interrupt(
            {
                "case_id": state["case_id"],
                "recommendation_version": state["recommendation_version"],
                "missing_information": recommendation.missing_information,
            }
        )
        case_id = UUID(state["case_id"])
        run_id = UUID(state["run_id"])
        actor_id = str(submission["actor_id"])
        information = dict(submission["information"])
        submission_id = str(submission["submission_id"])
        evidence_uuid = uuid5(
            case_id,
            f"{state['recommendation_version']}:{submission_id}",
        )
        evidence = evidence_from_model(
            evidence_id=f"INFO-{evidence_uuid}",
            evidence_type="supplemental_information",
            source_record_id=str(evidence_uuid),
            case_id=case_id,
            customer_id=state["customer_id"],
            value={"information": information},
            provenance="authenticated user submission through the investigation resume API",
        )
        await repository.audit(
            "case_information_supplied",
            actor_id,
            case_id,
            {
                "fields": sorted(information),
                "evidence_id": evidence.evidence_id,
                "recommendation_version": state["recommendation_version"],
            },
        )
        await repository.set_status(case_id, CaseStatus.RUNNING)
        await trajectory_hook(
            run_id,
            "case_information_supplied",
            {"evidence": evidence.model_dump(mode="json")},
        )
        updated_evidence = [
            *(EvidenceItem.model_validate(item) for item in state["evidence"]),
            evidence,
        ]
        policy_as_of_date, policy_applicability_facts, policy_matches = select_policies(
            updated_evidence
        )
        policies = [match.chunk for match in policy_matches]
        policy_retrieval = [match.to_record() for match in policy_matches]
        await trajectory_hook(
            run_id,
            "policies_retrieved",
            {
                "trigger": "supplemental_information",
                "as_of_date": policy_as_of_date.isoformat(),
                "jurisdiction": policy_jurisdiction,
                "policies": [item.model_dump(mode="json") for item in policies],
                "applicability_facts": [
                    item.model_dump(mode="json") for item in policy_applicability_facts
                ],
                "retrieval": [item.model_dump(mode="json") for item in policy_retrieval],
            },
        )
        return {
            "evidence": [item.model_dump(mode="json") for item in updated_evidence],
            "policies": [item.model_dump(mode="json") for item in policies],
            "policy_applicability_facts": [
                item.model_dump(mode="json") for item in policy_applicability_facts
            ],
            "policy_retrieval": [item.model_dump(mode="json") for item in policy_retrieval],
            "policy_as_of_date": policy_as_of_date.isoformat(),
            "status": CaseStatus.RUNNING.value,
        }

    async def human_review(state: InvestigationState) -> dict[str, Any]:
        if state["status"] == CaseStatus.HARD_BLOCKED.value:
            return {"status": CaseStatus.HARD_BLOCKED.value}
        payload = interrupt(
            {
                "case_id": state["case_id"],
                "recommendation_version": state["recommendation_version"],
                "recommendation": state["recommendation"],
                "control_results": state["control_results"],
                "allowed_actions": [item.value for item in ReviewAction],
            }
        )
        review = HumanReview.model_validate(
            {
                **payload,
                "case_id": state["case_id"],
                "recommendation_version": state["recommendation_version"],
            }
        )
        await repository.save_review(review)
        if review.action is ReviewAction.EDIT_AND_APPROVE and review.edited_recommendation:
            await repository.save_recommendation(
                UUID(state["case_id"]), review.edited_recommendation
            )
        if review.action is ReviewAction.REJECT_AND_REQUEST_REWORK:
            status = CaseStatus.REWORK_REQUIRED
            feedback = review.rationale
        else:
            status = CaseStatus.COMPLETED
            feedback = None
        await repository.set_status(UUID(state["case_id"]), status)
        await trajectory_hook(UUID(state["run_id"]), "human_review", review.model_dump(mode="json"))
        return {
            "review": review.model_dump(mode="json"),
            "reviewer_feedback": feedback,
            "status": status.value,
        }

    def route_after_validation(state: InvestigationState) -> str:
        if state["status"] in {CaseStatus.FAILED.value, CaseStatus.HARD_BLOCKED.value}:
            return "end"
        if state["status"] == CaseStatus.WAITING_FOR_INFORMATION.value:
            return "information"
        return "review"

    def route_after_review(state: InvestigationState) -> str:
        return "redraft" if state["status"] == CaseStatus.REWORK_REQUIRED.value else "end"

    def route_after_stage(state: InvestigationState) -> str:
        return "end" if state["status"] == CaseStatus.FAILED.value else "continue"

    graph = StateGraph(InvestigationState)
    graph.add_node(
        "load_and_retrieve", cast(Any, guarded("load_and_retrieve", load_and_retrieve))
    )
    graph.add_node(
        "draft_recommendation", cast(Any, guarded("draft_recommendation", draft))
    )
    graph.add_node("validate_controls", cast(Any, guarded("validate_controls", validate)))
    graph.add_node(
        "collect_information", cast(Any, guarded("collect_information", collect_information))
    )
    graph.add_node("human_review", cast(Any, guarded("human_review", human_review)))
    graph.add_edge(START, "load_and_retrieve")
    graph.add_conditional_edges(
        "load_and_retrieve",
        route_after_stage,
        {"continue": "draft_recommendation", "end": END},
    )
    graph.add_conditional_edges(
        "draft_recommendation",
        route_after_stage,
        {"continue": "validate_controls", "end": END},
    )
    graph.add_conditional_edges(
        "validate_controls",
        route_after_validation,
        {
            "information": "collect_information",
            "review": "human_review",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "collect_information",
        route_after_stage,
        {"continue": "draft_recommendation", "end": END},
    )
    graph.add_conditional_edges(
        "human_review", route_after_review, {"redraft": "draft_recommendation", "end": END}
    )
    return graph.compile(checkpointer=checkpointer)

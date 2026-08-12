from typing import Any
from uuid import UUID

import pytest

from amlguard.domain.enums import CaseStatus, ReviewAction
from amlguard.domain.models import EvidenceItem, HumanReview, InvestigationRecommendation
from amlguard.graph.service import LangGraphInvestigationEngine
from amlguard.llm.providers import FakeStructuredLLM
from amlguard.policy.models import PolicyChunk, PolicyRetrievalRecord
from amlguard.policy.retrieval import PolicyIndex
from amlguard.tools.repository import InMemoryInvestigationRepository


class FailingStructuredLLM(FakeStructuredLLM):
    model_id = "fake/failing"

    async def recommend(
        self,
        evidence: list[EvidenceItem],
        *,
        policies: list[PolicyChunk],
        policy_context: list[PolicyRetrievalRecord] | None = None,
        context_condition: str,
        reviewer_feedback: str | None = None,
    ) -> InvestigationRecommendation:
        raise RuntimeError("CANARY-SECRET must not be persisted")


class FabricatingPolicyLLM(FakeStructuredLLM):
    model_id = "fake/fabricated-policy"

    async def recommend(
        self,
        evidence: list[EvidenceItem],
        *,
        policies: list[PolicyChunk],
        policy_context: list[PolicyRetrievalRecord] | None = None,
        context_condition: str,
        reviewer_feedback: str | None = None,
    ) -> InvestigationRecommendation:
        recommendation = await super().recommend(
            evidence,
            policies=policies,
            policy_context=policy_context,
            context_condition=context_condition,
            reviewer_feedback=reviewer_feedback,
        )
        fabricated_finding = recommendation.material_findings[0].model_copy(
            update={"policy_ids": ["POLICY-FABRICATED"]}
        )
        return recommendation.model_copy(update={"material_findings": [fabricated_finding]})


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["B0", "B5"])
async def test_context_conditions_share_the_fixed_workflow_and_gate(
    injected_bank,
    policy_index: PolicyIndex,
    context: str,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank.model_copy(deep=True))
    engine = LangGraphInvestigationEngine(repository, FakeStructuredLLM(), policy_index)
    run = await engine.start(
        alert_id=injected_bank.alerts[0].alert_id,
        actor_id="analyst-1",
        context_condition=context,
    )
    assert run.status is CaseStatus.WAITING_FOR_HUMAN_REVIEW
    assert run.recommendation is not None
    assert run.recommendation.human_review_required
    assert all(result.outcome == "PASS" for result in run.control_results)
    retrieved_policy_ids = {item.policy_id for item in run.policies}
    assert {
        "FR-CMF-ONGOING-MONITORING-001",
        "FR-CMF-RISK-FACTORS-001",
        "FR-ACPR-ATYPICAL-ANALYSIS-001",
        "FR-CMF-REPORT-BASIS-001",
        "FR-CMF-RECORD-RETENTION-001",
    } <= retrieved_policy_ids
    assert "EU-AMLR-FUTURE-001" not in retrieved_policy_ids
    assert run.policy_applicability_facts
    assert {item.policy_id for item in run.policy_retrieval} == retrieved_policy_ids
    assert run.policy_as_of_date == injected_bank.alerts[0].created_at.date()
    assert {
        policy_id
        for finding in run.recommendation.material_findings
        for policy_id in finding.policy_ids
    } == {item.policy_id for item in run.policies}
    assert {item.control_id for item in run.control_results} == {
        "EVIDENCE-CITATION-001",
        "POLICY-CITATION-001",
    }


@pytest.mark.asyncio
async def test_graph_interrupts_and_resumes_with_human_approval(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank)
    engine = LangGraphInvestigationEngine(repository, FakeStructuredLLM(), policy_index)
    alert = injected_bank.alerts[0]
    run = await engine.start(alert_id=alert.alert_id, actor_id="analyst-1")
    assert run.status is CaseStatus.WAITING_FOR_HUMAN_REVIEW
    assert run.recommendation is not None
    assert run.recommendation_version == 1

    completed = await engine.review(
        HumanReview(
            case_id=run.case_id,
            recommendation_version=run.recommendation_version,
            action=ReviewAction.APPROVE,
            reviewer_id="reviewer-1",
            rationale="Evidence and limitations reviewed.",
        )
    )
    assert completed.status is CaseStatus.COMPLETED
    assert len((await repository.get_case(run.case_id)).reviews) == 1


@pytest.mark.asyncio
async def test_fabricated_policy_citation_is_hard_blocked(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank)
    engine = LangGraphInvestigationEngine(repository, FabricatingPolicyLLM(), policy_index)

    run = await engine.start(
        alert_id=injected_bank.alerts[0].alert_id,
        actor_id="analyst-1",
    )

    assert run.status is CaseStatus.HARD_BLOCKED
    policy_control = next(
        item for item in run.control_results if item.control_id == "POLICY-CITATION-001"
    )
    assert policy_control.outcome == "FAIL"
    assert policy_control.policy_ids == ["POLICY-FABRICATED"]
    assert policy_control.hard_block
    assert run.hard_blocks == ["POLICY-CITATION-001"]
    assert repository.audit_events[-1]["event_type"] == "investigation_hard_blocked"


@pytest.mark.asyncio
async def test_critical_security_event_revokes_review_release(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank)
    engine = LangGraphInvestigationEngine(repository, FakeStructuredLLM(), policy_index)
    run = await engine.start(
        alert_id=injected_bank.alerts[0].alert_id,
        actor_id="analyst-1",
    )

    blocked = await engine.record_security_event(
        run.case_id,
        "prohibited_action_execution",
    )

    assert blocked.status is CaseStatus.HARD_BLOCKED
    assert blocked.hard_blocks == ["prohibited_action_execution"]
    assert repository.audit_events[-1]["event_type"] == "investigation_hard_blocked"
    assert repository.audit_events[-1]["payload"] == {
        "security_event": "prohibited_action_execution",
        "hard_blocks": ["prohibited_action_execution"],
    }
    with pytest.raises(ValueError, match="hard blocked"):
        await engine.review(
            HumanReview(
                case_id=run.case_id,
                recommendation_version=run.recommendation_version,
                action=ReviewAction.APPROVE,
                reviewer_id="reviewer-1",
                rationale="This review must not override the hard block.",
            )
        )


@pytest.mark.asyncio
async def test_unknown_security_event_is_rejected(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank)
    engine = LangGraphInvestigationEngine(repository, FakeStructuredLLM(), policy_index)
    run = await engine.start(
        alert_id=injected_bank.alerts[0].alert_id,
        actor_id="analyst-1",
    )

    with pytest.raises(ValueError, match="unknown critical security event"):
        await engine.record_security_event(run.case_id, "untrusted_custom_event")


@pytest.mark.asyncio
async def test_rejection_redrafts_and_interrupts_again(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank)
    engine = LangGraphInvestigationEngine(repository, FakeStructuredLLM(), policy_index)
    run = await engine.start(alert_id=injected_bank.alerts[0].alert_id, actor_id="analyst-1")
    reworked = await engine.review(
        HumanReview(
            case_id=run.case_id,
            recommendation_version=1,
            action=ReviewAction.REJECT_AND_REQUEST_REWORK,
            reviewer_id="reviewer-1",
            rationale="Address the reviewer concern explicitly.",
        )
    )
    assert reworked.status is CaseStatus.WAITING_FOR_HUMAN_REVIEW
    assert reworked.recommendation_version == 2
    assert "Reviewer feedback considered" in " ".join(reworked.recommendation.limitations)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_supplemental_information_becomes_evidence_and_redrafts(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    bank = injected_bank.model_copy(deep=True)
    alert = bank.alerts[0]
    kyc_index = next(
        index
        for index, item in enumerate(bank.kyc_records)
        if item.customer_id == alert.customer_id
    )
    bank.kyc_records[kyc_index] = bank.kyc_records[kyc_index].model_copy(
        update={"status": "missing"}
    )
    repository = InMemoryInvestigationRepository(bank)
    engine = LangGraphInvestigationEngine(repository, FakeStructuredLLM(), policy_index)

    waiting = await engine.start(
        alert_id=alert.alert_id,
        actor_id="analyst-1",
    )
    assert waiting.status is CaseStatus.WAITING_FOR_INFORMATION
    assert waiting.recommendation is not None
    assert waiting.recommendation.missing_information
    waiting_fact_ids = {item.fact_id for item in waiting.policy_applicability_facts}
    assert "pep_status_unavailable" in waiting_fact_ids
    assert "sanctions_screening_status_unavailable" in waiting_fact_ids

    supplied_information = {
        "source_of_funds": "Synthetic salary certificate",
        "pep_status": "not_pep",
        "sanctions_screening_status": "no_match",
        "counterparty_country_code": "FR",
    }
    resumed = await engine.supply_information(
        case_id=waiting.case_id,
        actor_id="analyst-1",
        information=supplied_information,
        submission_id="information-1",
    )
    assert resumed.status is CaseStatus.WAITING_FOR_HUMAN_REVIEW
    assert resumed.recommendation_version == 2
    supplemental = [
        item for item in resumed.evidence if item.evidence_type == "supplemental_information"
    ]
    assert len(supplemental) == 1
    assert supplemental[0].content["information"] == supplied_information
    resumed_fact_ids = {item.fact_id for item in resumed.policy_applicability_facts}
    assert "pep_status_unavailable" not in resumed_fact_ids
    assert "sanctions_screening_status_unavailable" not in resumed_fact_ids
    assert "counterparty_geography_unavailable" not in resumed_fact_ids
    assert resumed.recommendation is not None
    cited = {
        evidence_id
        for finding in resumed.recommendation.material_findings
        for evidence_id in finding.evidence_ids
    }
    assert supplemental[0].evidence_id in cited
    audit = repository.audit_events[-1]
    assert audit["event_type"] == "case_information_supplied"
    assert audit["payload"] == {
        "fields": [
            "counterparty_country_code",
            "pep_status",
            "sanctions_screening_status",
            "source_of_funds",
        ],
        "evidence_id": supplemental[0].evidence_id,
        "recommendation_version": 1,
    }
    assert "Synthetic salary certificate" not in str(audit)


@pytest.mark.asyncio
async def test_model_exception_transitions_case_to_sanitized_failed_state(
    injected_bank,  # type: ignore[no-untyped-def]
    policy_index: PolicyIndex,
) -> None:
    repository = InMemoryInvestigationRepository(injected_bank)
    events: list[tuple[str, dict[str, Any]]] = []

    async def record(
        _run_id: UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        events.append((event_type, payload))

    engine = LangGraphInvestigationEngine(
        repository,
        FailingStructuredLLM(),
        policy_index,
        trajectory_hook=record,
    )
    run = await engine.start(
        alert_id=injected_bank.alerts[0].alert_id,
        actor_id="analyst-1",
    )

    assert run.status is CaseStatus.FAILED
    assert run.recommendation is None
    assert run.recommendation_version == 0
    assert len(run.errors) == 1
    assert run.errors[0].stage == "draft_recommendation"
    assert run.errors[0].error_type == "RuntimeError"
    assert run.errors[0].error_code == "UNEXPECTED_EXECUTION_ERROR"
    assert run.errors[0].safe_message == "The graph stage failed unexpectedly."
    assert repository.audit_events[-1]["event_type"] == "investigation_failed"
    assert events[-1][0] == "investigation_failed"
    rendered = str(
        {
            "run": run.model_dump(mode="json"),
            "audit": repository.audit_events,
            "events": events,
        }
    )
    assert "CANARY-SECRET" not in rendered

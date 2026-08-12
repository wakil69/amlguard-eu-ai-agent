from pathlib import Path

from amlguard.domain.enums import CaseStatus
from amlguard.domain.models import InvestigationRun
from amlguard.governance.readiness import (
    build_runtime_governance_evidence,
    evaluate_governance_readiness,
)


def test_current_governance_is_research_ready_but_not_production_ready() -> None:
    report = evaluate_governance_readiness(repository_root=Path.cwd())

    assert report["research_ready"] is True
    assert report["production_ready"] is False
    assert "privacy_owner" in report["unassigned_owner_roles"]
    assert "formal_dpia_approved" in report["production_blocking_checks"]


def test_runtime_governance_records_pending_human_gate() -> None:
    run = InvestigationRun(
        run_id="11111111-1111-4111-8111-111111111111",
        case_id="22222222-2222-4222-8222-222222222222",
        alert_id="ALT-1",
        customer_id="CUS-1",
        status=CaseStatus.WAITING_FOR_HUMAN_REVIEW,
    )
    runtime = build_runtime_governance_evidence(
        run=run,
        trajectory_events=[
            {
                "event_type": "controls_evaluated",
                "payload": {"release_decision": "READY"},
            }
        ],
        audit_events=[],
        tool_calls=[
            {
                "tool_name": "get_transactions",
                "authorized": True,
                "sanitized_arguments": {"limit": 250},
            }
        ],
        data_minimization_instructions=True,
    )

    assert runtime["review_state"] == "pending"
    assert runtime["human_signoff_present"] is False
    assert runtime["release_gate_enforced"] is True
    assert runtime["bounded_read_only_retrieval"] is True

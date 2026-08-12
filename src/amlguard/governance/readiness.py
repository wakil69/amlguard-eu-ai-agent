from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from amlguard.domain.enums import CaseStatus, ReviewAction
from amlguard.domain.models import InvestigationRun
from amlguard.governance.audit_chain import ChainedAuditEvent, verify_chain

_APPROVAL_ACTIONS = {ReviewAction.APPROVE, ReviewAction.EDIT_AND_APPROVE}


def _resolve_inside(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"governance path escapes repository root: {relative_path}") from exc
    return candidate


def build_runtime_governance_evidence(
    *,
    run: InvestigationRun,
    trajectory_events: list[dict[str, Any]],
    audit_events: list[dict[str, object]],
    tool_calls: list[dict[str, object]],
    data_minimization_instructions: bool,
) -> dict[str, Any]:
    """Summarize runtime governance without exposing payload values or actor IDs."""
    chained: list[ChainedAuditEvent] = []
    for item in audit_events:
        payload = item.get("payload")
        sequence_value = item.get("sequence", 0)
        sequence = int(sequence_value) if isinstance(sequence_value, (int, str)) else 0
        chained.append(
            ChainedAuditEvent(
                sequence=sequence,
                event_type=str(item.get("event_type", "unknown")),
                actor_id=str(item.get("actor_id", "unknown")),
                case_id=str(item.get("case_id", "unknown")),
                payload=dict(payload) if isinstance(payload, dict) else {},
                previous_hash=str(item.get("previous_hash", "")),
                event_hash=str(item.get("event_hash", "")),
            )
        )
    invalid_audit_sequences = verify_chain(chained)
    trajectory_counts = Counter(
        str(item.get("event_type", "unknown")) for item in trajectory_events
    )
    audit_counts = Counter(str(item.get("event_type", "unknown")) for item in audit_events)
    controls_event: dict[str, Any] = {}
    for item in reversed(trajectory_events):
        if item.get("event_type") != "controls_evaluated":
            continue
        payload = item.get("payload")
        controls_event = dict(payload) if isinstance(payload, dict) else {}
        break
    approved_reviews = [review for review in run.reviews if review.action in _APPROVAL_ACTIONS]
    release_gate_enforced = (
        run.status is not CaseStatus.COMPLETED or bool(approved_reviews)
    )
    bounded_retrieval = True
    for item in tool_calls:
        arguments = item.get("sanitized_arguments")
        sanitized_arguments = dict(arguments) if isinstance(arguments, dict) else {}
        if not bool(item.get("authorized")) or (
            item.get("tool_name") == "get_transactions"
            and int(sanitized_arguments.get("limit", 250)) > 500
        ):
            bounded_retrieval = False
            break
    return {
        "case_status": run.status.value,
        "human_review_required": bool(
            run.recommendation and run.recommendation.human_review_required
        ),
        "human_signoff_present": bool(approved_reviews),
        "review_state": (
            "signed"
            if approved_reviews
            else "pending"
            if run.status is CaseStatus.WAITING_FOR_HUMAN_REVIEW
            else "not_completed"
        ),
        "release_gate_enforced": release_gate_enforced,
        "release_decision": str(controls_event.get("release_decision", "unknown")),
        "controls_evaluated": "controls_evaluated" in trajectory_counts,
        "hard_blocks_clear": not run.hard_blocks,
        "audit_chain_valid": not invalid_audit_sequences,
        "audit_event_count": len(audit_events),
        "audit_event_types": dict(sorted(audit_counts.items())),
        "trajectory_event_count": len(trajectory_events),
        "trajectory_event_types": dict(sorted(trajectory_counts.items())),
        "bounded_read_only_retrieval": bounded_retrieval,
        "prohibited_action_tools_available": False,
        "data_minimization_instructions": data_minimization_instructions,
        "invalid_audit_sequences": invalid_audit_sequences,
        "scope": "single synthetic investigation run",
    }


def evaluate_governance_readiness(
    *,
    repository_root: Path,
    profile_path: str = "config/governance/profile.yaml",
    controls_path: str = "config/governance/organizational_controls.yaml",
) -> dict[str, Any]:
    """Evaluate declared governance facts without inventing missing approvals."""
    profile_file = _resolve_inside(repository_root, profile_path)
    controls_file = _resolve_inside(repository_root, controls_path)
    profile = yaml.safe_load(profile_file.read_text(encoding="utf-8"))
    controls = yaml.safe_load(controls_file.read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or not isinstance(controls, dict):
        raise ValueError("governance configuration must contain YAML objects")
    if controls.get("schema_version") != "1.0":
        raise ValueError("organizational controls must use schema_version 1.0")

    ownership = profile.get("ownership")
    if not isinstance(ownership, dict):
        ownership = {}
    unassigned = sorted(
        str(role)
        for role, owner in ownership.items()
        if not str(owner or "").strip() or str(owner).strip().upper() == "TBD"
    )
    release = profile.get("release")
    if not isinstance(release, dict):
        release = {}
    human_oversight = profile.get("human_oversight")
    if not isinstance(human_oversight, dict):
        human_oversight = {}

    checks: list[dict[str, Any]] = [
        {
            "check_id": "accountable_owners_assigned",
            "status": "implemented_and_approved" if not unassigned else "incomplete",
            "research_blocking": False,
            "production_blocking": True,
            "evidence": profile_path,
            "action": (
                "No action required."
                if not unassigned
                else "Assign named accountable owners for: " + ", ".join(unassigned)
            ),
        },
        {
            "check_id": "human_release_controls_configured",
            "status": (
                "implemented_and_approved"
                if human_oversight.get("final_disposition_required") is True
                and release.get("human_signoff") == "required"
                and release.get("held_out_evaluation") == "required"
                and release.get("hard_blocks_clear") == "required"
                else "incomplete"
            ),
            "research_blocking": True,
            "production_blocking": True,
            "evidence": profile_path,
            "action": (
                "Require final human disposition, held-out evaluation, and clear hard blocks."
            ),
        },
    ]
    configured_checks = controls.get("checks")
    if not isinstance(configured_checks, list):
        raise ValueError("organizational controls require a checks list")
    for item in configured_checks:
        if not isinstance(item, dict) or not item.get("check_id"):
            raise ValueError("organizational control checks require check_id")
        checks.append(dict(item))

    passing = {
        str(item["check_id"])
        for item in checks
        if item.get("status") == "implemented_and_approved"
    }
    research_blocks = sorted(
        str(item["check_id"])
        for item in checks
        if item.get("research_blocking") is True and item["check_id"] not in passing
    )
    production_blocks = sorted(
        str(item["check_id"])
        for item in checks
        if item.get("production_blocking") is True and item["check_id"] not in passing
    )
    return {
        "schema_version": "1.0",
        "scope": controls.get("scope", "unknown"),
        "research_ready": not research_blocks,
        "production_ready": not production_blocks,
        "research_blocking_checks": research_blocks,
        "production_blocking_checks": production_blocks,
        "unassigned_owner_roles": unassigned,
        "checks": checks,
        "source_paths": [profile_path, controls_path],
        "source_hashes": {
            profile_path: hashlib.sha256(profile_file.read_bytes()).hexdigest(),
            controls_path: hashlib.sha256(controls_file.read_bytes()).hexdigest(),
        },
    }

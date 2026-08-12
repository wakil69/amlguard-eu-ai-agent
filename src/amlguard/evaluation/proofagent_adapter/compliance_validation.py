from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

ComplianceStatus = Literal["met", "partial", "attention", "not_evaluated"]


@dataclass(frozen=True)
class ComplianceValidation:
    compliance: dict[str, Any]
    issues: list[dict[str, str]]
    hard_block: bool
    score: float | None
    assessed_controls: int
    total_controls: int


def load_validation_policy(registry_path: Path) -> tuple[str, list[dict[str, Any]]]:
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise ValueError("compliance validation registry must use schema_version 1.0")
    controls_path = str(payload.get("organizational_controls_path") or "").strip()
    rules = payload.get("validation_rules")
    if not controls_path or not isinstance(rules, list):
        raise ValueError(
            "compliance validation registry requires organizational_controls_path and rules"
        )
    validated_rules: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, dict):
            raise ValueError("compliance validation rules must be objects")
        required = {"framework_id", "control_id", "status_ceiling", "rationale"}
        if not required.issubset(item):
            raise ValueError("compliance validation rule is incomplete")
        if item["status_ceiling"] not in {"met", "partial", "not_evaluated"}:
            raise ValueError("invalid compliance status ceiling")
        evidence = item.get("required_evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("required_evidence must be a list")
        validated_rules.append(dict(item))
    return controls_path, validated_rules


def _available_evidence(
    *,
    documentary_evidence: list[dict[str, str]],
    runtime: dict[str, Any],
    readiness: dict[str, Any],
) -> set[str]:
    values = {
        f"document:{item['document_id']}"
        for item in documentary_evidence
        if item.get("document_id")
    }
    values.update(f"runtime:{key}" for key, value in runtime.items() if value is True)
    for check in readiness.get("checks", []):
        if isinstance(check, dict) and check.get("status") == "implemented_and_approved":
            values.add(f"readiness:{check.get('check_id')}")
    return values


def _capped_status(raw: str, ceiling: str, evidence_complete: bool, proof: str) -> str:
    if raw == "not_evaluated":
        return raw
    if raw == "attention":
        return raw if evidence_complete and proof.strip() else "not_evaluated"
    if not evidence_complete or ceiling == "not_evaluated":
        return "not_evaluated"
    if raw == "met" and ceiling == "partial":
        return "partial"
    return raw


def validate_compliance(
    *,
    compliance: dict[str, Any],
    rules: list[dict[str, Any]],
    documentary_evidence: list[dict[str, str]],
    runtime: dict[str, Any],
    readiness: dict[str, Any],
) -> ComplianceValidation:
    """Conservatively cap positive LLM verdicts using declared evidence."""
    result = deepcopy(compliance)
    rule_index = {
        (str(item["framework_id"]), str(item["control_id"])): item for item in rules
    }
    available = _available_evidence(
        documentary_evidence=documentary_evidence,
        runtime=runtime,
        readiness=readiness,
    )
    issues: list[dict[str, str]] = []
    total_counts = dict.fromkeys(("met", "partial", "attention", "not_evaluated"), 0)
    for framework in result.get("frameworks", []):
        if not isinstance(framework, dict):
            continue
        framework_id = str(framework.get("id") or "")
        controls = framework.get("controls", [])
        if not isinstance(controls, list):
            continue
        for control in controls:
            if not isinstance(control, dict):
                continue
            control_id = str(control.get("id") or "")
            raw = str(control.get("status") or "not_evaluated")
            rule = rule_index.get((framework_id, control_id))
            required = set(str(item) for item in (rule or {}).get("required_evidence", []))
            complete = required.issubset(available)
            ceiling = str((rule or {}).get("status_ceiling", "not_evaluated"))
            rationale = str(
                (rule or {}).get(
                    "rationale", "No AMLGuard evidence-validation rule exists for this control."
                )
            )
            validated = _capped_status(
                raw,
                ceiling,
                complete,
                str(control.get("proof") or ""),
            )
            control["proofagent_status"] = raw
            control["status"] = validated
            control["validation_rationale"] = rationale
            control["validation_evidence"] = sorted(required & available)
            control["missing_validation_evidence"] = sorted(required - available)
            if validated != raw:
                issues.append(
                    {
                        "framework_id": framework_id,
                        "control_id": control_id,
                        "proofagent_status": raw,
                        "validated_status": validated,
                        "reason": rationale,
                    }
                )
        counts = dict.fromkeys(("met", "partial", "attention", "not_evaluated"), 0)
        for control in controls:
            status = str(control.get("status") or "not_evaluated")
            if status in counts:
                counts[status] += 1
        assessed = counts["met"] + counts["partial"] + counts["attention"]
        framework["counts"] = counts
        framework["score"] = (
            round(100 * (counts["met"] + 0.5 * counts["partial"]) / assessed)
            if assessed
            else None
        )
        framework["coverage"] = f"{assessed}/{len(controls)}"
        framework["summary"] = (
            f"AMLGuard validated {assessed} of {len(controls)} controls against declared "
            "runtime and documentary evidence."
        )
        for status, count in counts.items():
            total_counts[status] += count
    assessed_controls = (
        total_counts["met"] + total_counts["partial"] + total_counts["attention"]
    )
    total_controls = sum(total_counts.values())
    score = (
        round(
            100
            * (total_counts["met"] + 0.5 * total_counts["partial"])
            / assessed_controls,
            1,
        )
        if assessed_controls
        else None
    )
    return ComplianceValidation(
        compliance=result,
        issues=issues,
        hard_block=any(item["proofagent_status"] == "met" for item in issues),
        score=score,
        assessed_controls=assessed_controls,
        total_controls=total_controls,
    )

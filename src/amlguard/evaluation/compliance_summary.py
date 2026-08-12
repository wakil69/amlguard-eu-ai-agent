from __future__ import annotations

from typing import Any

_STATUS_PRIORITY = {
    "attention": 0,
    "partial": 1,
    "met": 2,
    "not_evaluated": 3,
}


def _compliance_payload(result: object) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    evaluations = result.get("evaluations")
    if not isinstance(evaluations, dict):
        return None
    proofagent = evaluations.get("proofagent")
    if not isinstance(proofagent, dict):
        return None
    metadata = proofagent.get("metadata")
    if not isinstance(metadata, dict):
        return None
    compliance = metadata.get("compliance")
    return compliance if isinstance(compliance, dict) else None


def summarize_compliance_coverage(results: dict[str, object]) -> dict[str, Any]:
    """Aggregate research coverage without turning missing evidence into a pass."""
    frameworks: dict[str, dict[str, Any]] = {}
    sessions_with_compliance = 0
    for result in results.values():
        compliance = _compliance_payload(result)
        if compliance is None:
            continue
        sessions_with_compliance += 1
        for framework in compliance.get("frameworks", []):
            if not isinstance(framework, dict):
                continue
            framework_id = str(framework.get("id") or "").strip()
            if not framework_id:
                continue
            aggregate = frameworks.setdefault(
                framework_id,
                {
                    "id": framework_id,
                    "name": str(framework.get("name") or framework_id),
                    "controls": {},
                },
            )
            controls = aggregate["controls"]
            for control in framework.get("controls", []):
                if not isinstance(control, dict):
                    continue
                control_id = str(control.get("id") or "").strip()
                status = str(control.get("status") or "not_evaluated")
                if not control_id or status not in _STATUS_PRIORITY:
                    continue
                control_summary = controls.setdefault(
                    control_id,
                    {
                        "id": control_id,
                        "title": str(control.get("title") or control_id),
                        "status_counts": dict.fromkeys(_STATUS_PRIORITY, 0),
                    },
                )
                control_summary["status_counts"][status] += 1

    assessed_total = 0
    possible_total = 0
    normalized_frameworks: list[dict[str, Any]] = []
    for framework in frameworks.values():
        normalized_controls: list[dict[str, Any]] = []
        for control in framework["controls"].values():
            counts = control["status_counts"]
            observed = sum(counts.values())
            assessed = observed - counts["not_evaluated"]
            statuses = [
                status
                for status, count in counts.items()
                if count and status != "not_evaluated"
            ]
            aggregate_status = (
                min(statuses, key=_STATUS_PRIORITY.__getitem__)
                if statuses
                else "not_evaluated"
            )
            normalized_controls.append(
                {
                    **control,
                    "aggregate_status": aggregate_status,
                    "assessed_sessions": assessed,
                    "observed_sessions": observed,
                    "coverage_rate": round(assessed / observed, 4) if observed else 0.0,
                }
            )
            assessed_total += assessed
            possible_total += observed
        normalized_frameworks.append(
            {
                "id": framework["id"],
                "name": framework["name"],
                "controls": sorted(normalized_controls, key=lambda item: item["id"]),
            }
        )

    return {
        "interpretation": "research coverage summary; not a legal compliance determination",
        "sessions_total": len(results),
        "sessions_with_compliance": sessions_with_compliance,
        "control_observations_assessed": assessed_total,
        "control_observations_total": possible_total,
        "coverage_rate": (
            round(assessed_total / possible_total, 4) if possible_total else 0.0
        ),
        "frameworks": sorted(normalized_frameworks, key=lambda item: item["id"]),
    }

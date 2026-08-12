from __future__ import annotations

from typing import Any

from amlguard.domain.experiments import EvaluationResult


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def normalize_report(*, session_key: str, report: Any, version: str = "0.11.0") -> EvaluationResult:
    per_metric = getattr(report, "per_metric", None) or getattr(report, "metrics", {})
    metrics: dict[str, float] = {}
    for key, value in dict(per_metric).items():
        score = getattr(value, "score", value)
        if score is not None:
            metrics[str(key)] = float(score)
    consensus = getattr(report, "consensus_log", {}) or {}
    hard_blocks = sorted(
        f"proofagent_zero_tolerance:{key}"
        for key, value in dict(consensus).items()
        if bool(getattr(value, "zero_tolerance_capped", False))
    )
    metadata = {
        "final_score": getattr(report, "final_score", None),
        "certification": _json_value(getattr(report, "certification", "unknown")),
        "mode": getattr(report, "mode", "unknown"),
        "confidence": _json_value(getattr(report, "confidence", {})),
        "severity": _json_value(getattr(report, "severity", {})),
        "findings": _json_value(getattr(report, "findings", [])),
        "technical_issues": _json_value(getattr(report, "technical_issues", [])),
        "warnings": _json_value(getattr(report, "warnings", [])),
        "summary": getattr(report, "summary", ""),
        "executive_summary": getattr(report, "executive_summary", ""),
        "production_ready": getattr(report, "production_ready", ""),
        "top_risk": getattr(report, "top_risk", ""),
        "compliance": _json_value(getattr(report, "compliance", {})),
        "context_engineering": _json_value(getattr(report, "context_engineering", {})),
        "pai": _json_value(getattr(report, "pai", {})),
        "performance": _json_value(getattr(report, "performance", {})),
        "duration_seconds": getattr(report, "duration_seconds", 0.0),
        "tokens_used": getattr(report, "tokens_used", 0),
        "primary_llm_model": getattr(report, "primary_llm_model", ""),
        "fallback_llm_model": getattr(report, "fallback_llm_model", ""),
        "fallback_rate": getattr(report, "fallback_rate", 0.0),
    }
    return EvaluationResult(
        session_key=session_key,
        evaluator_type="proofagent",
        evaluator_version=version,
        metrics=metrics,
        hard_blocks=hard_blocks,
        metadata=metadata,
    )

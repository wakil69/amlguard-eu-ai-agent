import json
from pathlib import Path

import pytest
import yaml
from prometheus_client import generate_latest

from amlguard.monitoring.telemetry import (
    log_event,
    record_cross_scope_attempt,
    record_evaluation,
    record_experiment_job,
    record_hard_blocks,
    record_model_cost,
    record_tool_denial,
    record_unsupported_claims,
    stage_span,
)


def test_all_operational_metric_families_are_exported() -> None:
    record_tool_denial(reason="PROHIBITED_ACTION", tool="submit_str")
    record_hard_blocks(["prohibited_action_execution"])
    record_cross_scope_attempt("test")
    record_unsupported_claims(1)
    record_evaluation(
        evaluator="deterministic",
        configuration="B5",
        scores={"safety": 1.0},
    )
    record_model_cost(cost_eur=0.01, basis="declared_estimate", configuration="B5")
    record_experiment_job("completed")

    rendered = generate_latest().decode()
    expected = {
        "amlguard_tool_denials_total",
        "amlguard_hard_blocks_total",
        "amlguard_cross_scope_attempts_total",
        "amlguard_unsupported_claims_total",
        "amlguard_evaluation_score",
        "amlguard_model_cost_eur_total",
        "amlguard_experiment_jobs_total",
    }
    assert all(metric in rendered for metric in expected)


def test_structured_monitoring_log_is_redacted(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level("INFO", logger="amlguard"):
        log_event(
            "redaction_test",
            api_key="CANARY-SECRET",
            authorization="Bearer CANARY-TOKEN",
        )

    payload = json.loads(caplog.records[-1].message)
    assert payload == {
        "api_key": "[REDACTED]",
        "authorization": "[REDACTED]",
        "event_type": "redaction_test",
    }


def test_expected_graph_interrupt_is_not_recorded_as_error() -> None:
    class ExpectedInterrupt(Exception):
        pass

    with pytest.raises(ExpectedInterrupt):
        with stage_span("expected_interrupt", expected_exceptions=(ExpectedInterrupt,)):
            raise ExpectedInterrupt

    rendered = generate_latest().decode()
    assert 'outcome="interrupted",stage="expected_interrupt"' in rendered


def test_dashboards_and_prometheus_alert_rules_use_exported_metrics() -> None:
    dashboard_documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path("dashboards").glob("*.json"))
    ]
    dashboards = json.dumps(dashboard_documents)
    for metric in {
        "amlguard_runs_total",
        "amlguard_tool_denials_total",
        "amlguard_hard_blocks_total",
        "amlguard_cross_scope_attempts_total",
        "amlguard_unsupported_claims_total",
        "amlguard_investigation_stage_duration_seconds_bucket",
        "amlguard_dependency_ready",
        "amlguard_evaluation_score",
        "amlguard_model_cost_eur_total",
    }:
        assert metric in dashboards

    alerts = yaml.safe_load(
        Path("config/observability/alerts.yaml").read_text(encoding="utf-8")
    )
    rules = [rule for group in alerts["groups"] for rule in group["rules"]]
    assert {rule["alert"] for rule in rules} == {
        "AMLGuardHardBlockDetected",
        "AMLGuardCrossScopeAttempt",
        "AMLGuardToolDenialBurst",
        "AMLGuardApplicationDown",
        "AMLGuardDependencyNotReady",
        "AMLGuardInvestigationFailureRatio",
    }

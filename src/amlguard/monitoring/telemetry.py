from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

from amlguard.config import Settings
from amlguard.monitoring.redaction import redact

_configured = False
_logger = logging.getLogger("amlguard")
_logger.setLevel(logging.INFO)
_logger.propagate = True

_prom_runs = Counter(
    "amlguard_runs",
    "Investigation runs by resulting status.",
    ("status",),
)
_prom_tool_denials = Counter(
    "amlguard_tool_denials",
    "Denied investigation tool calls.",
    ("reason", "tool"),
)
_prom_hard_blocks = Counter(
    "amlguard_hard_blocks",
    "Investigation hard blocks by reason.",
    ("reason",),
)
_prom_cross_scope = Counter(
    "amlguard_cross_scope_attempts",
    "Denied or detected cross-scope access attempts.",
    ("surface",),
)
_prom_unsupported_claims = Counter(
    "amlguard_unsupported_claims",
    "Recommendation claims with unknown evidence citations.",
)
_prom_stage_duration = Histogram(
    "amlguard_investigation_stage_duration_seconds",
    "Investigation graph stage duration.",
    ("stage", "outcome"),
)
_prom_evaluation_score = Gauge(
    "amlguard_evaluation_score",
    "Most recently observed experiment evaluation score.",
    ("evaluator", "metric", "configuration"),
)
_prom_model_cost = Counter(
    "amlguard_model_cost_eur",
    "Recorded experiment cost in EUR using the declared cost basis.",
    ("basis", "configuration"),
)
_prom_experiment_jobs = Counter(
    "amlguard_experiment_jobs",
    "Experiment jobs by terminal outcome.",
    ("status",),
)
_prom_readiness = Gauge(
    "amlguard_dependency_ready",
    "Latest readiness result for a dependency.",
    ("dependency",),
)

_meter = metrics.get_meter("amlguard")
_otel_runs = _meter.create_counter("amlguard.runs")
_otel_tool_denials = _meter.create_counter("amlguard.tool_denials")
_otel_hard_blocks = _meter.create_counter("amlguard.hard_blocks")
_otel_cross_scope = _meter.create_counter("amlguard.cross_scope_attempts")
_otel_unsupported_claims = _meter.create_counter("amlguard.unsupported_claims")
_otel_stage_duration = _meter.create_histogram("amlguard.investigation_stage_duration", unit="s")
_otel_evaluation_score = _meter.create_histogram("amlguard.evaluation_score")
_otel_model_cost = _meter.create_counter("amlguard.model_cost_eur")
_otel_experiment_jobs = _meter.create_counter("amlguard.experiment_jobs")
_tracer = trace.get_tracer("amlguard")


def configure_telemetry(settings: Settings) -> None:
    global _configured
    if _configured or settings.environment == "test" or not settings.otel_enabled:
        return
    resource = Resource.create(
        {"service.name": "amlguard-eu", "deployment.environment": settings.environment}
    )
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{str(settings.otel_endpoint).rstrip('/')}/v1/traces")
        )
    )
    trace.set_tracer_provider(trace_provider)
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{str(settings.otel_endpoint).rstrip('/')}/v1/metrics")
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{str(settings.otel_endpoint).rstrip('/')}/v1/logs")
        )
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _configured = True


def telemetry_configured() -> bool:
    return _configured


def log_event(event_type: str, *, level: int = logging.INFO, **fields: object) -> None:
    payload = redact({"event_type": event_type, **fields})
    _logger.log(level, json.dumps(payload, sort_keys=True, default=str))


@contextmanager
def stage_span(
    stage: str,
    *,
    expected_exceptions: tuple[type[BaseException], ...] = (),
    **attributes: str,
) -> Iterator[None]:
    started = time.perf_counter()
    outcome = "success"
    with _tracer.start_as_current_span(f"investigation.{stage}") as span:
        span.set_attribute("amlguard.stage", stage)
        for key, value in attributes.items():
            span.set_attribute(f"amlguard.{key}", value)
        try:
            yield
        except expected_exceptions:
            outcome = "interrupted"
            span.set_attribute("amlguard.interrupted", True)
            raise
        except Exception as exc:
            outcome = "error"
            span.set_attribute("error.type", type(exc).__name__)
            raise
        finally:
            duration = time.perf_counter() - started
            labels = {"stage": stage, "outcome": outcome}
            _prom_stage_duration.labels(**labels).observe(duration)
            _otel_stage_duration.record(duration, labels)


def record_run(status: str) -> None:
    attributes = {"status": status}
    _prom_runs.labels(**attributes).inc()
    _otel_runs.add(1, attributes)


def record_tool_denial(*, reason: str, tool: str) -> None:
    attributes = {"reason": reason, "tool": tool}
    _prom_tool_denials.labels(**attributes).inc()
    _otel_tool_denials.add(1, attributes)
    if reason == "CROSS_SCOPE_ACCESS":
        record_cross_scope_attempt("tool")


def record_hard_blocks(reasons: list[str] | tuple[str, ...]) -> None:
    for reason in sorted(set(reasons)):
        attributes = {"reason": reason}
        _prom_hard_blocks.labels(**attributes).inc()
        _otel_hard_blocks.add(1, attributes)


def record_cross_scope_attempt(surface: str) -> None:
    attributes = {"surface": surface}
    _prom_cross_scope.labels(**attributes).inc()
    _otel_cross_scope.add(1, attributes)


def record_unsupported_claims(count: int) -> None:
    if count <= 0:
        return
    _prom_unsupported_claims.inc(count)
    _otel_unsupported_claims.add(count)


def record_evaluation(
    *, evaluator: str, configuration: str, scores: dict[str, float]
) -> None:
    for metric, score in scores.items():
        attributes = {
            "evaluator": evaluator,
            "metric": metric,
            "configuration": configuration,
        }
        _prom_evaluation_score.labels(**attributes).set(score)
        _otel_evaluation_score.record(score, attributes)


def record_model_cost(*, cost_eur: float, basis: str, configuration: str) -> None:
    if cost_eur < 0:
        raise ValueError("model cost cannot be negative")
    attributes = {"basis": basis, "configuration": configuration}
    _prom_model_cost.labels(**attributes).inc(cost_eur)
    _otel_model_cost.add(cost_eur, attributes)


def record_experiment_job(status: str) -> None:
    attributes = {"status": status}
    _prom_experiment_jobs.labels(**attributes).inc()
    _otel_experiment_jobs.add(1, attributes)


def record_readiness(checks: dict[str, bool]) -> None:
    for dependency, ready in checks.items():
        _prom_readiness.labels(dependency=dependency).set(1 if ready else 0)

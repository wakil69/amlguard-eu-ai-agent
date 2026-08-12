from __future__ import annotations

import argparse
import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from decimal import Decimal
from typing import Literal

from amlguard.config import Settings, get_settings
from amlguard.db.session import get_database
from amlguard.domain.enums import CaseStatus
from amlguard.domain.experiments import (
    ExperimentJob,
    ExperimentManifest,
    ProofAgentEvaluationConfig,
)
from amlguard.evaluation.deterministic import evaluate_deterministically
from amlguard.evaluation.proofagent_adapter import (
    ProofAgentArtifactEvaluator,
    ProofAgentExecution,
)
from amlguard.experiments.queue import (
    ExperimentQueue,
    PostgresExperimentQueue,
    estimated_job_cost,
)
from amlguard.governance import build_runtime_governance_evidence
from amlguard.graph.service import LangGraphInvestigationEngine
from amlguard.llm.providers import (
    EdenStructuredLLM,
    FakeStructuredLLM,
    recommendation_system_prompt,
)
from amlguard.monitoring.artifacts import EncryptedArtifactStore, TrajectoryRecorder
from amlguard.monitoring.telemetry import (
    configure_telemetry,
    log_event,
    record_evaluation,
    record_experiment_job,
    record_model_cost,
    stage_span,
)
from amlguard.policy import load_policy_index
from amlguard.simulation.catalog import build_catalog
from amlguard.simulation.generator import SyntheticBankGenerator
from amlguard.simulation.injection import ScenarioInjectionEngine
from amlguard.tools.repository import InMemoryInvestigationRepository

JobHandler = Callable[[ExperimentJob], Awaitable[tuple[dict[str, object], Decimal]]]
ProofAgentEvaluator = Callable[..., Awaitable[ProofAgentExecution]]
ProofAgentEvaluatorFactory = Callable[[ProofAgentEvaluationConfig], ProofAgentArtifactEvaluator]


class DefaultExperimentJobHandler:
    """Runs one canonical scenario without requiring an API request.

    Each job gets an isolated synthetic repository and checkpointer. The complete
    synthetic trajectory is encrypted when an artifact key is configured.
    """

    def __init__(
        self,
        queue: ExperimentQueue,
        settings: Settings,
        *,
        force_provider: Literal["auto", "fake"] = "auto",
        proofagent_evaluator_factory: ProofAgentEvaluatorFactory = ProofAgentArtifactEvaluator,
    ) -> None:
        self.queue = queue
        self.settings = settings
        self.force_provider = force_provider
        self.proofagent_evaluator_factory = proofagent_evaluator_factory
        self.scenarios = {item.scenario_id: item for item in build_catalog()}
        self.policy_index = load_policy_index(settings.policy_corpus_root)

    async def __call__(self, job: ExperimentJob) -> tuple[dict[str, object], Decimal]:
        if get_settings().experiment_kill_switch:
            raise RuntimeError("experiment kill switch is active")
        description = await self.queue.describe(job.experiment_id)
        manifest = ExperimentManifest.model_validate(description["manifest"])
        configuration = next(
            item
            for item in manifest.configurations
            if item.configuration_id == job.configuration_id
        )
        scenario = self.scenarios.get(job.scenario_id)
        if scenario is None or scenario.pack != manifest.scenario_pack:
            raise ValueError(f"scenario {job.scenario_id} is not in the manifest pack")

        bank = SyntheticBankGenerator().generate(
            seed=manifest.dataset_seed, customer_count=100, transaction_count=2_000
        )
        injection = ScenarioInjectionEngine().inject(bank, scenario)
        repository = InMemoryInvestigationRepository(bank)
        artifact_store = self._artifact_store()
        recorder = TrajectoryRecorder(artifact_store)
        llm = self._llm(configuration.model_id)
        engine = LangGraphInvestigationEngine(
            repository,
            llm,
            self.policy_index,
            policy_jurisdiction=self.settings.policy_jurisdiction,
            policy_result_limit=self.settings.policy_result_limit,
            trajectory_hook=recorder.record,
        )
        run = await engine.start(
            alert_id=str(injection.visible_case["alert_id"]),
            actor_id="amlguard-worker",
            context_condition=configuration.context_condition,
        )

        if run.status is CaseStatus.FAILED and run.errors:
            error_type = run.errors[-1].error_type
            if error_type == "TimeoutError":
                raise TimeoutError("investigation graph stage timed out")
            if error_type == "ConnectionError":
                raise ConnectionError("investigation graph stage connection failed")

        tool_calls: dict[str, dict[str, object]] = {}
        for event in recorder.events.get(run.run_id, []):
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            executions = payload.get("tool_executions", [])
            if not isinstance(executions, list):
                continue
            for execution in executions:
                if isinstance(execution, dict):
                    key = str(execution.get("tool_call_id", len(tool_calls)))
                    tool_calls[key] = execution

        evaluation = evaluate_deterministically(
            session_key=job.session_key,
            scenario=scenario,
            recommendation=run.recommendation,
            available_evidence_ids={item.evidence_id for item in run.evidence},
            available_policy_ids={item.policy_id for item in run.policies},
            tool_calls=list(tool_calls.values()),
            safe_failure=run.status is CaseStatus.FAILED,
        )
        runtime_governance = build_runtime_governance_evidence(
            run=run,
            trajectory_events=recorder.events.get(run.run_id, []),
            audit_events=repository.audit_events,
            tool_calls=list(tool_calls.values()),
            data_minimization_instructions=(
                "Minimize data"
                in recommendation_system_prompt(configuration.context_condition)
            ),
        )
        evaluations: dict[str, object] = {
            "deterministic": evaluation.model_dump(mode="json")
        }
        evaluator_errors: dict[str, object] = {}
        proofagent_report_reference: dict[str, str] | None = None
        if manifest.proofagent is not None:
            try:
                if run.recommendation is None:
                    raise RuntimeError("ProofAgent evaluation requires a recommendation artifact")
                proofagent = self.proofagent_evaluator_factory(manifest.proofagent)
                proofagent_execution = await proofagent.evaluate(
                    session_key=job.session_key,
                    scenario=scenario,
                    recommendation=run.recommendation,
                    evidence=run.evidence,
                    policies=run.policies,
                    tool_calls=list(tool_calls.values()),
                    control_results=run.control_results,
                    hard_blocks=run.hard_blocks,
                    runtime_governance=runtime_governance,
                    context_condition=configuration.context_condition,
                )
                evaluations["proofagent"] = proofagent_execution.evaluation.model_dump(mode="json")
                if artifact_store is not None:
                    proofagent_reference = artifact_store.put_json(
                        {
                            "session_key": job.session_key,
                            "evaluator": "proofagent",
                            "harness_version": manifest.proofagent.harness_version,
                            "report": proofagent_execution.report,
                        }
                    )
                    proofagent_report_reference = {
                        "content_hash": proofagent_reference.content_hash,
                        "relative_path": proofagent_reference.relative_path,
                        "encryption_algorithm": proofagent_reference.encryption_algorithm,
                    }
            except Exception as exc:
                if manifest.proofagent.failure_policy == "fail_job":
                    raise
                evaluator_errors["proofagent"] = {
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                    "harness_version": manifest.proofagent.harness_version,
                }
        artifact = recorder.latest.get(run.run_id)
        result: dict[str, object] = {
            "session_key": job.session_key,
            "run": run.model_dump(mode="json"),
            "evaluation": evaluation.model_dump(mode="json"),
            "evaluations": evaluations,
            "injection_logical_hash": injection.logical_hash,
            "requested_model": configuration.model_id,
            "actual_model": llm.model_id,
            "endpoint_class": "local_fake" if isinstance(llm, FakeStructuredLLM) else "EU",
            "cost_basis": (
                "preregistered_session_and_evaluator_estimate"
                if manifest.proofagent is not None
                else "preregistered_session_estimate"
            ),
        }
        if evaluator_errors:
            result["evaluator_errors"] = evaluator_errors
        if proofagent_report_reference:
            result["proofagent_report"] = proofagent_report_reference
        if artifact:
            result["restricted_artifact"] = {
                "content_hash": artifact.content_hash,
                "relative_path": artifact.relative_path,
                "encryption_algorithm": artifact.encryption_algorithm,
            }
        return result, estimated_job_cost(manifest, configuration.configuration_id)

    def _artifact_store(self) -> EncryptedArtifactStore | None:
        key_file = self.settings.artifact_key_file
        if key_file and key_file.exists():
            return EncryptedArtifactStore.from_key_file(self.settings.artifact_root, key_file)
        if self.settings.environment == "research":
            raise RuntimeError("research worker requires AMLGUARD_ARTIFACT_KEY_FILE")
        return None

    def _llm(self, requested_model: str) -> FakeStructuredLLM | EdenStructuredLLM:
        if self.force_provider == "fake" or requested_model.startswith("fake/"):
            return FakeStructuredLLM()
        live_settings = self.settings.model_copy(update={"eden_model_id": requested_model})
        return EdenStructuredLLM(live_settings)


class ExperimentWorker:
    def __init__(
        self,
        queue: ExperimentQueue,
        handler: JobHandler,
        *,
        worker_id: str,
        concurrency: int = 2,
    ) -> None:
        self.queue = queue
        self.handler = handler
        self.worker_id = worker_id
        self.concurrency = concurrency

    async def _heartbeat(self, job: ExperimentJob) -> None:
        while True:
            await asyncio.sleep(30)
            await self.queue.heartbeat(job.job_id, self.worker_id)

    async def _process(self, job: ExperimentJob) -> None:
        heartbeat: asyncio.Task[None] | None = None
        try:
            await self.queue.reserve_cost(job, job.estimated_cost_eur)
            await self.queue.heartbeat(job.job_id, self.worker_id)
            heartbeat = asyncio.create_task(self._heartbeat(job))
            result, cost = await self.handler(job)
            await self.queue.complete(job, result, cost)
            evaluations = result.get("evaluations", {})
            if isinstance(evaluations, dict):
                for evaluator_name, evaluation in evaluations.items():
                    if not isinstance(evaluation, dict):
                        continue
                    scores = evaluation.get("metrics")
                    if isinstance(scores, dict):
                        record_evaluation(
                            evaluator=str(evaluator_name),
                            configuration=job.configuration_id,
                            scores={str(key): float(value) for key, value in scores.items()},
                        )
            record_model_cost(
                cost_eur=float(cost),
                basis=str(result.get("cost_basis", "declared_estimate")),
                configuration=job.configuration_id,
            )
            record_experiment_job("completed")
            log_event("experiment_job_completed", configuration=job.configuration_id)
        except Exception as exc:
            retryable = isinstance(exc, (TimeoutError, ConnectionError))
            await self.queue.fail(
                job,
                {"error_type": type(exc).__name__, "message": str(exc)[:500]},
                retryable=retryable,
            )
            record_experiment_job("failed")
            log_event(
                "experiment_job_failed",
                level=40,
                configuration=job.configuration_id,
                error_type=type(exc).__name__,
                retryable=retryable,
            )
        finally:
            if heartbeat:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat

    async def run_once(self) -> bool:
        job = await self.queue.claim(self.worker_id)
        if job is None:
            return False
        await self._process(job)
        return True

    async def run_forever(self) -> None:
        active: set[asyncio.Task[None]] = set()
        while True:
            if get_settings().experiment_kill_switch:
                if active:
                    await asyncio.gather(*active)
                return
            active = {task for task in active if not task.done()}
            while len(active) < self.concurrency:
                job = await self.queue.claim(self.worker_id)
                if job is None:
                    break
                active.add(asyncio.create_task(self._process(job)))
            if active:
                await asyncio.wait(active, timeout=1, return_when=asyncio.FIRST_COMPLETED)
            else:
                await asyncio.sleep(1)


async def _run(*, once: bool, provider: Literal["auto", "fake"]) -> None:
    settings = get_settings()
    configure_telemetry(settings)
    if settings.experiment_kill_switch:
        raise SystemExit("Experiment kill switch is active")
    worker_id = os.getenv("AMLGUARD_WORKER_ID", f"{socket.gethostname()}-{os.getpid()}")
    queue = PostgresExperimentQueue(get_database())
    handler = DefaultExperimentJobHandler(queue, settings, force_provider=provider)
    worker = ExperimentWorker(
        queue, handler, worker_id=worker_id, concurrency=settings.worker_concurrency
    )
    with stage_span("experiment_worker"):
        if once:
            await worker.run_once()
        else:
            await worker.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="AMLGuard durable experiment worker")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--provider", choices=("auto", "fake"), default="auto")
    args = parser.parse_args()
    asyncio.run(_run(once=args.once, provider=args.provider))

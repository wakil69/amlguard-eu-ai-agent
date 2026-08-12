from decimal import Decimal

import pytest
from pydantic import ValidationError

from amlguard.config import Settings
from amlguard.domain.experiments import (
    EvaluationResult,
    ExperimentManifest,
    ProofAgentEvaluationConfig,
    SystemConfiguration,
)
from amlguard.evaluation.proofagent_adapter import ProofAgentExecution
from amlguard.experiments.queue import InMemoryExperimentQueue
from amlguard.experiments.worker import DefaultExperimentJobHandler, ExperimentWorker


def manifest(cost: str = "1.00", *, proofagent: bool = False) -> ExperimentManifest:
    return ExperimentManifest(
        name="test",
        git_commit="abc",
        dependency_lock_hash="def",
        dataset_version="1",
        dataset_seed=1,
        scenario_pack="regression",
        scenario_version="1",
        policy_version="1",
        control_version="1",
        configurations=[
            SystemConfiguration(
                configuration_id="fake-b5",
                model_id="fake/deterministic",
                context_condition="B5",
                prompt_version="1",
                tool_schema_version="1",
                graph_version="1",
                estimated_session_cost_eur=Decimal("0.01"),
            )
        ],
        repetitions=2,
        evaluator_version="1",
        proofagent=(
            ProofAgentEvaluationConfig(
                harness_llm="judge/model",
                estimated_evaluation_cost_eur=Decimal("0.10"),
            )
            if proofagent
            else None
        ),
        telemetry_version="1",
        randomization_seed=42,
        cost_ceiling_eur=Decimal(cost),
    )


def test_obsolete_orchestration_condition_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SystemConfiguration(
            configuration_id="obsolete-o1",
            model_id="fake/deterministic",
            context_condition="B5",
            orchestration_condition="O1",  # type: ignore[call-arg]
            prompt_version="1",
            tool_schema_version="1",
            graph_version="1",
        )


@pytest.mark.asyncio
async def test_queue_is_idempotent_and_resumable() -> None:
    queue = InMemoryExperimentQueue()
    value = manifest()
    assert await queue.schedule(value, ["REG-001"]) == 2
    assert await queue.schedule(value, ["REG-001"]) == 2
    assert len(queue.jobs) == 2
    job = await queue.claim("worker-1")
    assert job is not None
    await queue.complete(job, {"status": "ok"}, Decimal("0.10"))
    assert (await queue.results_for(value.experiment_id))[job.session_key] == {"status": "ok"}


@pytest.mark.asyncio
async def test_cost_ceiling_stops_completion() -> None:
    queue = InMemoryExperimentQueue()
    value = manifest("0.05")
    await queue.schedule(value, ["REG-001"])
    job = await queue.claim("worker-1")
    assert job is not None
    with pytest.raises(RuntimeError, match="cost ceiling"):
        await queue.reserve_cost(job, Decimal("0.10"))


@pytest.mark.asyncio
async def test_worker_executes_and_evaluates_a_real_session(tmp_path) -> None:
    queue = InMemoryExperimentQueue()
    value = manifest()
    value = value.model_copy(update={"repetitions": 1})
    await queue.schedule(value, ["REG-001"])
    settings = Settings(
        environment="test",
        artifact_root=tmp_path,
        artifact_key_file=None,
    )
    handler = DefaultExperimentJobHandler(queue, settings, force_provider="fake")
    worker = ExperimentWorker(queue, handler, worker_id="test-worker", concurrency=1)

    assert await worker.run_once()
    results = await queue.results_for(value.experiment_id)
    assert len(results) == 1
    result = next(iter(results.values()))
    assert result["actual_model"] == "fake/deterministic"
    assert result["endpoint_class"] == "local_fake"
    assert result["evaluation"]["evaluator_type"] == "deterministic"
    assert result["evaluations"]["deterministic"] == result["evaluation"]


@pytest.mark.asyncio
async def test_worker_runs_manifest_configured_proofagent_separately(tmp_path) -> None:
    captured: dict[str, object] = {}

    class FakeProofAgentEvaluator:
        async def evaluate(self, **kwargs: object) -> ProofAgentExecution:
            captured.update(kwargs)
            return ProofAgentExecution(
                evaluation=EvaluationResult(
                    session_key="proof-session",
                    evaluator_type="proofagent",
                    evaluator_version="0.11.0",
                    metrics={"safety": 9.0},
                ),
                report={"final_score": 9.0, "certification": "GOLD"},
            )

    queue = InMemoryExperimentQueue()
    value = manifest(proofagent=True).model_copy(update={"repetitions": 1})
    await queue.schedule(value, ["REG-001"])
    job = next(iter(queue.jobs.values()))
    assert job.estimated_cost_eur == Decimal("0.11")
    settings = Settings(environment="test", artifact_root=tmp_path, artifact_key_file=None)
    handler = DefaultExperimentJobHandler(
        queue,
        settings,
        force_provider="fake",
        proofagent_evaluator_factory=lambda _config: FakeProofAgentEvaluator(),  # type: ignore[arg-type]
    )
    worker = ExperimentWorker(queue, handler, worker_id="test-worker", concurrency=1)

    assert await worker.run_once()
    result = next(iter((await queue.results_for(value.experiment_id)).values()))
    assert result["evaluation"]["evaluator_type"] == "deterministic"
    assert result["evaluations"]["proofagent"]["evaluator_type"] == "proofagent"
    assert result["cost_basis"] == "preregistered_session_and_evaluator_estimate"
    assert isinstance(captured["control_results"], list)
    assert isinstance(captured["hard_blocks"], list)
    assert captured["runtime_governance"]["release_gate_enforced"] is True

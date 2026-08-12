from __future__ import annotations

import os
from decimal import Decimal

import pytest

from amlguard.config import Settings
from amlguard.db.session import Database
from amlguard.domain.experiments import ExperimentManifest, SystemConfiguration
from amlguard.experiments.queue import PostgresExperimentQueue
from amlguard.experiments.worker import DefaultExperimentJobHandler, ExperimentWorker

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("AMLGUARD_POSTGRES_TEST") != "1", reason="requires project PostgreSQL"
    ),
]


@pytest.mark.asyncio
async def test_postgres_queue_worker_round_trip(tmp_path) -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://amlguard:amlguard@localhost:55432/amlguard",
        artifact_root=tmp_path,
        artifact_key_file=None,
    )
    database = Database(settings.database_url)
    queue = PostgresExperimentQueue(database)
    manifest = ExperimentManifest(
        name="postgres-integration",
        git_commit="test",
        dependency_lock_hash="test",
        dataset_version="1.0",
        dataset_seed=20260810,
        scenario_pack="regression",
        scenario_version="1.0",
        policy_version="1.0",
        control_version="1.0",
        configurations=[
            SystemConfiguration(
                configuration_id="fake-b5",
                model_id="fake/deterministic",
                context_condition="B5",
                prompt_version="1.0",
                tool_schema_version="1.0",
                graph_version="1.0",
                estimated_session_cost_eur=Decimal("0.01"),
            )
        ],
        repetitions=1,
        evaluator_version="1.0",
        juror_mode="none",
        telemetry_version="1.0",
        randomization_seed=7,
        cost_ceiling_eur=Decimal("0.02"),
    )
    try:
        assert await queue.schedule(manifest, ["REG-001"]) == 1
        assert await queue.schedule(manifest, ["REG-001"]) == 0
        handler = DefaultExperimentJobHandler(queue, settings, force_provider="fake")
        worker = ExperimentWorker(queue, handler, worker_id="postgres-test", concurrency=1)
        results: dict[str, object] = {}
        for _ in range(10):
            assert await worker.run_once()
            results = await queue.results_for(manifest.experiment_id)
            if results:
                break
        assert len(results) == 1
        description = await queue.describe(manifest.experiment_id)
        assert description["job_counts"] == {"SUCCEEDED": 1}
        assert description["cost_spent_eur"] == "0.0100"
        assert description["cost_reserved_eur"] == "0.0000"
    finally:
        await database.dispose()

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult

from amlguard.db.models import ExperimentJobRecord, ExperimentRecord, ExperimentSessionRecord
from amlguard.db.session import Database
from amlguard.domain.enums import JobStatus
from amlguard.domain.experiments import ExperimentJob, ExperimentManifest


def session_key(
    experiment_id: UUID, configuration_id: str, scenario_id: str, repetition: int
) -> str:
    raw = f"{experiment_id}:{configuration_id}:{scenario_id}:{repetition}"
    return hashlib.sha256(raw.encode()).hexdigest()


def estimated_job_cost(manifest: ExperimentManifest, configuration_id: str) -> Decimal:
    configuration = next(
        item for item in manifest.configurations if item.configuration_id == configuration_id
    )
    evaluator_cost = (
        manifest.proofagent.estimated_evaluation_cost_eur
        if manifest.proofagent is not None
        else Decimal("0")
    )
    return configuration.estimated_session_cost_eur + evaluator_cost


class ExperimentQueue(Protocol):
    async def schedule(self, manifest: ExperimentManifest, scenario_ids: list[str]) -> int: ...
    async def claim(self, worker_id: str, lease_seconds: int = 120) -> ExperimentJob | None: ...
    async def heartbeat(self, job_id: UUID, worker_id: str, lease_seconds: int = 120) -> None: ...
    async def reserve_cost(self, job: ExperimentJob, amount: Decimal) -> None: ...
    async def complete(
        self, job: ExperimentJob, result: dict[str, object], cost: Decimal
    ) -> None: ...
    async def fail(
        self, job: ExperimentJob, error: dict[str, object], *, retryable: bool
    ) -> None: ...
    async def stop(self, experiment_id: UUID) -> None: ...
    async def resume(self, experiment_id: UUID) -> None: ...
    async def describe(self, experiment_id: UUID) -> dict[str, object]: ...
    async def results_for(self, experiment_id: UUID) -> dict[str, object]: ...


class InMemoryExperimentQueue:
    def __init__(self) -> None:
        self.manifests: dict[UUID, ExperimentManifest] = {}
        self.jobs: dict[UUID, ExperimentJob] = {}
        self.results: dict[str, dict[str, object]] = {}
        self.stopped: set[UUID] = set()
        self.costs: dict[UUID, Decimal] = {}
        self.reservations: dict[str, tuple[UUID, Decimal]] = {}

    async def schedule(self, manifest: ExperimentManifest, scenario_ids: list[str]) -> int:
        self.manifests[manifest.experiment_id] = manifest
        keys = []
        for configuration in manifest.configurations:
            for scenario_id in scenario_ids:
                for repetition in range(1, manifest.repetitions + 1):
                    key = session_key(
                        manifest.experiment_id,
                        configuration.configuration_id,
                        scenario_id,
                        repetition,
                    )
                    keys.append((key, configuration.configuration_id, scenario_id, repetition))
        random.Random(manifest.randomization_seed).shuffle(keys)
        existing = {item.session_key for item in self.jobs.values()}
        for key, configuration_id, scenario_id, repetition in keys:
            if key in existing:
                continue
            job = ExperimentJob(
                experiment_id=manifest.experiment_id,
                session_key=key,
                configuration_id=configuration_id,
                scenario_id=scenario_id,
                repetition=repetition,
                estimated_cost_eur=estimated_job_cost(manifest, configuration_id),
            )
            self.jobs[job.job_id] = job
        return len(keys)

    async def claim(self, worker_id: str, lease_seconds: int = 120) -> ExperimentJob | None:
        now = datetime.now(UTC)
        for job_id, job in self.jobs.items():
            if job.experiment_id in self.stopped:
                continue
            if job.status in {JobStatus.PENDING, JobStatus.RETRY_WAIT} and job.not_before <= now:
                claimed = job.model_copy(
                    update={
                        "status": JobStatus.LEASED,
                        "lease_owner": worker_id,
                        "lease_expires_at": now + timedelta(seconds=lease_seconds),
                        "attempt_count": job.attempt_count + 1,
                    }
                )
                self.jobs[job_id] = claimed
                return claimed
            if (
                job.status in {JobStatus.LEASED, JobStatus.RUNNING}
                and job.lease_expires_at
                and job.lease_expires_at < now
            ):
                recovered = job.model_copy(
                    update={"status": JobStatus.PENDING, "lease_owner": None}
                )
                self.jobs[job_id] = recovered
        return None

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_seconds: int = 120) -> None:
        job = self.jobs[job_id]
        if job.lease_owner != worker_id:
            raise PermissionError("worker does not own job lease")
        self.jobs[job_id] = job.model_copy(
            update={"lease_expires_at": datetime.now(UTC) + timedelta(seconds=lease_seconds)}
        )

    async def complete(self, job: ExperimentJob, result: dict[str, object], cost: Decimal) -> None:
        manifest = self.manifests[job.experiment_id]
        spent = self.costs.get(job.experiment_id, Decimal("0"))
        self.reservations.pop(job.session_key, None)
        if spent + cost > manifest.cost_ceiling_eur:
            self.stopped.add(job.experiment_id)
            raise RuntimeError("experiment cost ceiling would be exceeded")
        self.costs[job.experiment_id] = spent + cost
        self.results.setdefault(job.session_key, result)
        self.jobs[job.job_id] = self.jobs[job.job_id].model_copy(
            update={"status": JobStatus.SUCCEEDED}
        )

    async def reserve_cost(self, job: ExperimentJob, amount: Decimal) -> None:
        if job.session_key in self.reservations:
            return
        manifest = self.manifests[job.experiment_id]
        committed = self.costs.get(job.experiment_id, Decimal("0"))
        reserved = sum(
            value
            for experiment_id, value in self.reservations.values()
            if experiment_id == job.experiment_id
        )
        if committed + reserved + amount > manifest.cost_ceiling_eur:
            self.stopped.add(job.experiment_id)
            raise RuntimeError("experiment cost ceiling would be exceeded")
        self.reservations[job.session_key] = (job.experiment_id, amount)

    async def fail(self, job: ExperimentJob, error: dict[str, object], *, retryable: bool) -> None:
        self.reservations.pop(job.session_key, None)
        current = self.jobs[job.job_id]
        retry = retryable and current.attempt_count < current.max_attempts
        self.jobs[job.job_id] = current.model_copy(
            update={
                "status": JobStatus.RETRY_WAIT if retry else JobStatus.FAILED,
                "not_before": datetime.now(UTC) + timedelta(seconds=2**current.attempt_count),
                "lease_owner": None,
                "lease_expires_at": None,
            }
        )

    async def stop(self, experiment_id: UUID) -> None:
        self.stopped.add(experiment_id)

    async def resume(self, experiment_id: UUID) -> None:
        self.stopped.discard(experiment_id)

    async def describe(self, experiment_id: UUID) -> dict[str, object]:
        manifest = self.manifests.get(experiment_id)
        if manifest is None:
            raise KeyError(experiment_id)
        jobs = [item for item in self.jobs.values() if item.experiment_id == experiment_id]
        states = {item.status.value for item in jobs}
        return {
            "manifest": manifest.model_dump(mode="json"),
            "job_counts": {
                state: sum(item.status.value == state for item in jobs) for state in states
            },
            "cost_spent_eur": str(self.costs.get(experiment_id, Decimal("0"))),
        }

    async def results_for(self, experiment_id: UUID) -> dict[str, object]:
        keys = {
            item.session_key for item in self.jobs.values() if item.experiment_id == experiment_id
        }
        return {key: self.results[key] for key in keys if key in self.results}


class PostgresExperimentQueue:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def schedule(self, manifest: ExperimentManifest, scenario_ids: list[str]) -> int:
        rows: list[ExperimentJobRecord] = []
        keys: list[tuple[str, str, str, int]] = []
        for config in manifest.configurations:
            for scenario_id in scenario_ids:
                for repetition in range(1, manifest.repetitions + 1):
                    keys.append(
                        (
                            session_key(
                                manifest.experiment_id,
                                config.configuration_id,
                                scenario_id,
                                repetition,
                            ),
                            config.configuration_id,
                            scenario_id,
                            repetition,
                        )
                    )
        random.Random(manifest.randomization_seed).shuffle(keys)
        async with self.database.session() as session:
            existing_manifest = (
                await session.execute(
                    select(ExperimentRecord).where(ExperimentRecord.id == manifest.experiment_id)
                )
            ).scalar_one_or_none()
            if existing_manifest is None:
                session.add(
                    ExperimentRecord(
                        id=manifest.experiment_id,
                        name=manifest.name,
                        payload=manifest.model_dump(mode="json"),
                        cost_ceiling_eur=manifest.cost_ceiling_eur,
                    )
                )
            elif existing_manifest.payload != manifest.model_dump(mode="json"):
                raise ValueError("experiment ID already exists with a different manifest")
            existing_keys = set(
                (
                    await session.execute(
                        select(ExperimentJobRecord.session_key).where(
                            ExperimentJobRecord.experiment_id == manifest.experiment_id
                        )
                    )
                ).scalars()
            )
            for key, configuration_id, scenario_id, repetition in keys:
                if key in existing_keys:
                    continue
                rows.append(
                    ExperimentJobRecord(
                        experiment_id=manifest.experiment_id,
                        session_key=key,
                        configuration_id=configuration_id,
                        scenario_id=scenario_id,
                        repetition=repetition,
                        estimated_cost_eur=estimated_job_cost(manifest, configuration_id),
                    )
                )
            session.add_all(rows)
        return len(rows)

    async def claim(self, worker_id: str, lease_seconds: int = 120) -> ExperimentJob | None:
        query = text(
            """
            WITH candidate AS (
              SELECT j.id
              FROM experiment.jobs j
              JOIN experiment.manifests m ON m.id = j.experiment_id
              WHERE m.stop_requested = false
                AND (
                  (j.status IN ('PENDING', 'RETRY_WAIT') AND j.not_before <= now())
                  OR (j.status IN ('LEASED', 'RUNNING') AND j.lease_expires_at < now())
                )
              ORDER BY j.not_before, j.id
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            UPDATE experiment.jobs j
            SET status = 'LEASED', lease_owner = :worker_id,
                lease_expires_at = now() + make_interval(secs => :lease_seconds),
                heartbeat_at = now(), attempt_count = j.attempt_count + 1
            FROM candidate
            WHERE j.id = candidate.id
            RETURNING j.*
            """
        )
        async with self.database.session() as session:
            row = (
                (
                    await session.execute(
                        query, {"worker_id": worker_id, "lease_seconds": lease_seconds}
                    )
                )
                .mappings()
                .first()
            )
        if not row:
            return None
        return ExperimentJob(
            job_id=row["id"],
            experiment_id=row["experiment_id"],
            session_key=row["session_key"],
            configuration_id=row["configuration_id"],
            scenario_id=row["scenario_id"],
            repetition=row["repetition"],
            status=JobStatus(row["status"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            not_before=row["not_before"],
            estimated_cost_eur=row["estimated_cost_eur"],
        )

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_seconds: int = 120) -> None:
        async with self.database.session() as session:
            result = await session.execute(
                update(ExperimentJobRecord)
                .where(
                    ExperimentJobRecord.id == job_id,
                    ExperimentJobRecord.lease_owner == worker_id,
                )
                .values(
                    heartbeat_at=datetime.now(UTC),
                    lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
                    status=JobStatus.RUNNING.value,
                )
            )
            if not isinstance(result, CursorResult) or result.rowcount != 1:
                raise PermissionError("worker does not own job lease")

    async def reserve_cost(self, job: ExperimentJob, amount: Decimal) -> None:
        async with self.database.session() as session:
            manifest = (
                await session.execute(
                    select(ExperimentRecord)
                    .where(ExperimentRecord.id == job.experiment_id)
                    .with_for_update()
                )
            ).scalar_one()
            record = (
                await session.execute(
                    select(ExperimentJobRecord)
                    .where(ExperimentJobRecord.id == job.job_id)
                    .with_for_update()
                )
            ).scalar_one()
            if record.reserved_cost_eur:
                return
            if manifest.stop_requested:
                raise RuntimeError("experiment is stopped")
            if (
                manifest.cost_spent_eur + manifest.cost_reserved_eur + amount
                > manifest.cost_ceiling_eur
            ):
                manifest.stop_requested = True
                manifest.status = "PAUSED_COST_CEILING"
                raise RuntimeError("experiment cost ceiling would be exceeded")
            manifest.cost_reserved_eur += amount
            record.reserved_cost_eur = amount

    async def complete(self, job: ExperimentJob, result: dict[str, object], cost: Decimal) -> None:
        async with self.database.session() as session:
            manifest = (
                await session.execute(
                    select(ExperimentRecord)
                    .where(ExperimentRecord.id == job.experiment_id)
                    .with_for_update()
                )
            ).scalar_one()
            if manifest.stop_requested:
                raise RuntimeError("experiment is stopped")
            record = (
                await session.execute(
                    select(ExperimentJobRecord)
                    .where(ExperimentJobRecord.id == job.job_id)
                    .with_for_update()
                )
            ).scalar_one()
            reserved = record.reserved_cost_eur
            if manifest.cost_spent_eur + cost > manifest.cost_ceiling_eur:
                manifest.stop_requested = True
                raise RuntimeError("experiment cost ceiling would be exceeded")
            manifest.cost_reserved_eur -= reserved
            manifest.cost_spent_eur += cost
            existing = (
                await session.execute(
                    select(ExperimentSessionRecord).where(
                        ExperimentSessionRecord.session_key == job.session_key
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    ExperimentSessionRecord(
                        job_id=job.job_id, session_key=job.session_key, result=result
                    )
                )
            record.status = JobStatus.SUCCEEDED.value
            record.actual_cost_eur = cost
            record.reserved_cost_eur = Decimal("0")

    async def fail(self, job: ExperimentJob, error: dict[str, object], *, retryable: bool) -> None:
        retry = retryable and job.attempt_count < job.max_attempts
        async with self.database.session() as session:
            manifest = (
                await session.execute(
                    select(ExperimentRecord)
                    .where(ExperimentRecord.id == job.experiment_id)
                    .with_for_update()
                )
            ).scalar_one()
            record = (
                await session.execute(
                    select(ExperimentJobRecord)
                    .where(ExperimentJobRecord.id == job.job_id)
                    .with_for_update()
                )
            ).scalar_one()
            manifest.cost_reserved_eur -= record.reserved_cost_eur
            record.reserved_cost_eur = Decimal("0")
            record.status = (JobStatus.RETRY_WAIT if retry else JobStatus.FAILED).value
            record.provider_error = error
            record.not_before = datetime.now(UTC) + timedelta(seconds=2**job.attempt_count)
            record.lease_owner = None
            record.lease_expires_at = None

    async def stop(self, experiment_id: UUID) -> None:
        async with self.database.session() as session:
            await session.execute(
                update(ExperimentRecord)
                .where(ExperimentRecord.id == experiment_id)
                .values(stop_requested=True, status="STOPPED")
            )

    async def resume(self, experiment_id: UUID) -> None:
        async with self.database.session() as session:
            await session.execute(
                update(ExperimentRecord)
                .where(ExperimentRecord.id == experiment_id)
                .values(stop_requested=False, status="RUNNING")
            )

    async def describe(self, experiment_id: UUID) -> dict[str, object]:
        async with self.database.session() as session:
            manifest = (
                await session.execute(
                    select(ExperimentRecord).where(ExperimentRecord.id == experiment_id)
                )
            ).scalar_one()
            rows = (
                await session.execute(
                    select(ExperimentJobRecord.status).where(
                        ExperimentJobRecord.experiment_id == experiment_id
                    )
                )
            ).scalars()
            counts: dict[str, int] = {}
            for state in rows:
                counts[state] = counts.get(state, 0) + 1
        return {
            "manifest": manifest.payload,
            "job_counts": counts,
            "cost_spent_eur": str(manifest.cost_spent_eur),
            "cost_reserved_eur": str(manifest.cost_reserved_eur),
            "status": manifest.status,
        }

    async def results_for(self, experiment_id: UUID) -> dict[str, object]:
        async with self.database.session() as session:
            rows = (
                await session.execute(
                    select(ExperimentSessionRecord)
                    .join(
                        ExperimentJobRecord,
                        ExperimentJobRecord.id == ExperimentSessionRecord.job_id,
                    )
                    .where(ExperimentJobRecord.experiment_id == experiment_id)
                )
            ).scalars()
            return {item.session_key: item.result for item in rows}

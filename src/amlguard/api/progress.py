from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4


@dataclass
class ProgressStep:
    key: str
    label: str
    status: str = "pending"


@dataclass
class InvestigationJob:
    job_id: UUID
    case_id: UUID
    run_id: UUID
    actor_id: str
    tenant_id: str
    steps: list[ProgressStep]
    status: str = "running"
    error: str | None = None


_STAGES = (
    ("initialize", "Initializing investigation"),
    ("load_and_retrieve", "Loading evidence and applicable policy"),
    ("draft_recommendation", "Drafting the recommendation"),
    ("validate_controls", "Validating safeguards and citations"),
    ("collect_information", "Processing supplemental information"),
    ("human_review", "Preparing the human-review handoff"),
)


class InvestigationJobStore:
    """Process-local progress for active UI requests; durable case state remains authoritative."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, InvestigationJob] = {}
        self._jobs_by_run: dict[UUID, UUID] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def create(
        self, *, case_id: UUID, run_id: UUID, actor_id: str, tenant_id: str
    ) -> InvestigationJob:
        steps = [ProgressStep(key=key, label=label) for key, label in _STAGES]
        steps[0].status = "completed"
        job = InvestigationJob(
            job_id=uuid4(),
            case_id=case_id,
            run_id=run_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            steps=steps,
        )
        self._jobs[job.job_id] = job
        self._jobs_by_run[run_id] = job.job_id
        self._prune()
        return job

    def get(self, job_id: UUID) -> InvestigationJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown investigation job {job_id}") from exc

    def for_case(self, case_id: UUID) -> InvestigationJob | None:
        return next(
            (job for job in reversed(list(self._jobs.values())) if job.case_id == case_id),
            None,
        )

    def discard_case(self, case_id: UUID) -> None:
        for job_id, job in list(self._jobs.items()):
            if job.case_id != case_id:
                continue
            self._jobs.pop(job_id, None)
            self._jobs_by_run.pop(job.run_id, None)

    async def stage_hook(self, run_id: UUID, stage: str, event: str) -> None:
        job_id = self._jobs_by_run.get(run_id)
        if job_id is None:
            return
        job = self._jobs[job_id]
        step = next((item for item in job.steps if item.key == stage), None)
        if step is None:
            return
        if event == "started":
            step.status = "active"
        elif event in {"completed", "interrupted"}:
            step.status = "completed"
        elif event == "failed":
            step.status = "failed"

    def complete(self, job_id: UUID) -> None:
        job = self.get(job_id)
        for step in job.steps:
            if step.status == "active":
                step.status = "completed"
        job.status = "completed"

    def fail(self, job_id: UUID) -> None:
        job = self.get(job_id)
        for step in job.steps:
            if step.status == "active":
                step.status = "failed"
        job.status = "failed"
        job.error = (
            "The investigation could not be completed. "
            "Check the case logs using its error ID."
        )

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _prune(self) -> None:
        if len(self._jobs) <= 500:
            return
        terminal_ids = [
            job_id for job_id, job in self._jobs.items() if job.status != "running"
        ]
        for job_id in terminal_ids[:100]:
            job = self._jobs.pop(job_id)
            self._jobs_by_run.pop(job.run_id, None)

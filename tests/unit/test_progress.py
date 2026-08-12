from uuid import uuid4

from amlguard.api.progress import InvestigationJobStore


async def test_progress_store_tracks_real_graph_stage_events() -> None:
    store = InvestigationJobStore()
    run_id = uuid4()
    job = store.create(
        case_id=uuid4(),
        run_id=run_id,
        actor_id="analyst-1",
        tenant_id="tenant-1",
    )

    await store.stage_hook(run_id, "load_and_retrieve", "started")
    retrieval = next(step for step in job.steps if step.key == "load_and_retrieve")
    assert retrieval.status == "active"

    await store.stage_hook(run_id, "load_and_retrieve", "completed")
    assert retrieval.status == "completed"

    await store.stage_hook(run_id, "draft_recommendation", "started")
    drafting = next(step for step in job.steps if step.key == "draft_recommendation")
    assert drafting.status == "active"

    await store.stage_hook(run_id, "draft_recommendation", "failed")
    assert drafting.status == "failed"

from __future__ import annotations

import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from amlguard.api.progress import InvestigationJobStore
from amlguard.api.schemas import (
    HumanReviewRequest,
    ResumeInvestigationRequest,
    ScheduleExperimentRequest,
    StartInvestigationRequest,
)
from amlguard.auth import Actor, CaseAccessDenied, authorize_case, get_actor, require_roles
from amlguard.auth.case_access import CaseAction
from amlguard.config import Settings, get_settings
from amlguard.db.session import get_database
from amlguard.domain.enums import CaseStatus, ReviewAction
from amlguard.domain.models import HumanReview, InvestigationRun
from amlguard.domain.scenarios import InjectionResult
from amlguard.evaluation.compliance_summary import summarize_compliance_coverage
from amlguard.experiments.queue import (
    ExperimentQueue,
    InMemoryExperimentQueue,
    PostgresExperimentQueue,
)
from amlguard.graph.service import LangGraphInvestigationEngine
from amlguard.llm.providers import EdenStructuredLLM, FakeStructuredLLM
from amlguard.monitoring.artifacts import EncryptedArtifactStore, TrajectoryRecorder
from amlguard.monitoring.telemetry import (
    configure_telemetry,
    log_event,
    record_cross_scope_attempt,
    record_readiness,
    record_run,
    telemetry_configured,
)
from amlguard.policy import load_policy_index
from amlguard.simulation.catalog import build_catalog
from amlguard.simulation.generator import SyntheticBankGenerator
from amlguard.simulation.injection import ScenarioInjectionEngine
from amlguard.simulation.models import SyntheticBank
from amlguard.tools.postgres_repository import PostgresInvestigationRepository
from amlguard.tools.repository import (
    CaseData,
    InMemoryInvestigationRepository,
    InvestigationRepository,
)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _engine(request: Request) -> LangGraphInvestigationEngine:
    return cast(LangGraphInvestigationEngine, request.app.state.engine)


def _repository(request: Request) -> InvestigationRepository:
    return cast(InvestigationRepository, request.app.state.repository)


def _recorder(request: Request) -> TrajectoryRecorder:
    return cast(TrajectoryRecorder, request.app.state.recorder)


def _queue(request: Request) -> ExperimentQueue:
    return cast(ExperimentQueue, request.app.state.experiment_queue)


def _idempotency(request: Request) -> dict[tuple[str, str], dict[str, object]]:
    return cast(dict[tuple[str, str], dict[str, object]], request.app.state.idempotency)


def _progress_jobs(request: Request) -> InvestigationJobStore:
    return cast(InvestigationJobStore, request.app.state.progress_jobs)


async def _render_investigation_workspace(
    request: Request,
    run: InvestigationRun,
    actor: Actor,
    *,
    message: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    context = await _investigation_workspace_context(
        request,
        run,
        actor,
        message=message,
        error=error,
    )
    return templates.TemplateResponse(request, "investigation_workspace.html", context)


async def _investigation_workspace_context(
    request: Request,
    run: InvestigationRun,
    actor: Actor,
    *,
    message: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    case = await _repository(request).get_case(run.case_id)
    is_administrator = "administrator" in actor.roles
    can_review = is_administrator or case.assigned_reviewer_id == actor.actor_id
    can_claim = (
        "reviewer" in actor.roles
        and case.assigned_investigator_id != actor.actor_id
        and case.assigned_reviewer_id is None
    )
    can_supply_information = is_administrator or actor.actor_id in {
        case.assigned_investigator_id,
        case.assigned_reviewer_id,
    }
    alert_evidence = next(
        (item for item in run.evidence if item.evidence_type == "alert"),
        None,
    )
    triggering_transaction_ids = {
        str(transaction_id)
        for transaction_id in (
            alert_evidence.content.get("causal_transaction_ids", [])
            if alert_evidence is not None
            else []
        )
    }
    evidence_inventory = sorted(
        run.evidence,
        key=lambda item: not (
            item.evidence_type == "transaction"
            and item.evidence_id in triggering_transaction_ids
        ),
    )
    return {
        "run": run,
        "case": case,
        "actor": actor,
        "can_review": can_review,
        "can_claim": can_claim,
        "can_supply_information": can_supply_information,
        "triggering_transaction_ids": triggering_transaction_ids,
        "evidence_inventory": evidence_inventory,
        "form_id": f"ui-{uuid4()}",
        "message": message,
        "error": error,
    }


async def _render_investigation_page(
    request: Request,
    run: InvestigationRun,
    actor: Actor,
    *,
    message: str | None = None,
) -> HTMLResponse:
    context = await _investigation_workspace_context(
        request,
        run,
        actor,
        message=message,
    )
    return templates.TemplateResponse(request, "investigation_page.html", context)


def _render_ui_error(request: Request, message: str, actor: Actor) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "ui_error.html",
        {"error": message, "actor": actor},
    )


async def _case_for_action(
    request: Request,
    case_id: UUID,
    actor: Actor,
    action: CaseAction,
) -> CaseData:
    repository = _repository(request)
    try:
        case = await repository.get_case(case_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found") from exc
    try:
        authorize_case(actor, case, action)
    except CaseAccessDenied as exc:
        record_cross_scope_attempt("case_api")
        log_event(
            "case_authorization_denied",
            level=30,
            action=action,
            roles=sorted(actor.roles),
        )
        await repository.audit(
            "case_authorization_denied",
            actor.actor_id,
            case_id,
            {
                "action": action,
                "actor_tenant_id": actor.tenant_id,
                "roles": sorted(actor.roles),
            },
        )
        # Do not disclose whether a cross-tenant case identifier exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found") from exc
    return case


async def _run_ui_investigation(
    app: FastAPI,
    job_id: UUID,
    case: CaseData,
    *,
    actor_id: str,
    context_condition: str,
) -> None:
    jobs = cast(InvestigationJobStore, app.state.progress_jobs)
    engine = cast(LangGraphInvestigationEngine, app.state.engine)
    try:
        run = await engine.run_prepared(
            case,
            actor_id=actor_id,
            context_condition=context_condition,
        )
    except Exception as exc:
        jobs.fail(job_id)
        log_event(
            "ui_investigation_job_failed",
            level=40,
            error_type=type(exc).__name__,
        )
        return
    jobs.complete(job_id)
    record_run(run.status.value)
    log_event("investigation_started_from_ui", status=run.status.value)


def _render_investigation_progress(
    request: Request,
    job_id: UUID,
    actor: Actor,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "investigation_progress.html",
        {"job": _progress_jobs(request).get(job_id), "actor": actor},
    )


def _runtime(
    settings: Settings, progress_jobs: InvestigationJobStore
) -> tuple[
    SyntheticBank,
    list[InjectionResult],
    InMemoryInvestigationRepository,
    TrajectoryRecorder,
    LangGraphInvestigationEngine,
]:
    bank = SyntheticBankGenerator().generate(
        seed=20260810, customer_count=200, transaction_count=5_000
    )
    injector = ScenarioInjectionEngine()
    injection_results = []
    for scenario in [item for item in build_catalog() if item.pack == "development"]:
        injection_results.append(injector.inject(bank, scenario))
    repository = InMemoryInvestigationRepository(bank)
    llm = (
        EdenStructuredLLM(settings)
        if settings.eden_ai_api_key and settings.eden_model_id
        else FakeStructuredLLM()
    )
    if settings.artifact_key_file and settings.artifact_key_file.exists():
        artifact_store = EncryptedArtifactStore.from_key_file(
            settings.artifact_root, settings.artifact_key_file
        )
    else:
        # Deterministic test/dev key only; research mode requires a mounted key.
        if settings.environment == "research":
            raise RuntimeError("research mode requires AMLGUARD_ARTIFACT_KEY_FILE")
        artifact_store = EncryptedArtifactStore(settings.artifact_root, b"D" * 32)
    recorder = TrajectoryRecorder(artifact_store if settings.raw_research_capture else None)
    engine = LangGraphInvestigationEngine(
        repository,
        llm,
        load_policy_index(settings.policy_corpus_root),
        policy_jurisdiction=settings.policy_jurisdiction,
        policy_result_limit=settings.policy_result_limit,
        trajectory_hook=recorder.record,
        stage_hook=progress_jobs.stage_hook,
    )
    return bank, injection_results, repository, recorder, engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        configure_telemetry(settings)
        progress_jobs = InvestigationJobStore()
        app.state.progress_jobs = progress_jobs
        if settings.repository_backend == "postgres":
            database = get_database()
            repository = PostgresInvestigationRepository(database)
            llm = (
                EdenStructuredLLM(settings)
                if settings.eden_ai_api_key and settings.eden_model_id
                else FakeStructuredLLM()
            )
            if not settings.artifact_key_file or not settings.artifact_key_file.exists():
                raise RuntimeError("PostgreSQL/research mode requires an artifact key file")
            artifact_store = EncryptedArtifactStore.from_key_file(
                settings.artifact_root, settings.artifact_key_file
            )
            recorder = TrajectoryRecorder(artifact_store)
            async with AsyncPostgresSaver.from_conn_string(settings.database_dsn) as saver:
                await saver.setup()
                app.state.alerts = await repository.list_alerts()
                app.state.injected = []
                app.state.repository = repository
                app.state.recorder = recorder
                app.state.engine = LangGraphInvestigationEngine(
                    repository,
                    llm,
                    load_policy_index(settings.policy_corpus_root),
                    policy_jurisdiction=settings.policy_jurisdiction,
                    policy_result_limit=settings.policy_result_limit,
                    checkpointer=saver,
                    trajectory_hook=recorder.record,
                    stage_hook=progress_jobs.stage_hook,
                )
                app.state.experiment_queue = PostgresExperimentQueue(database)
                app.state.idempotency = {}
                try:
                    yield
                finally:
                    await progress_jobs.shutdown()
            await database.dispose()
        else:
            bank, injected, memory_repository, recorder, engine = _runtime(
                settings, progress_jobs
            )
            app.state.alerts = bank.alerts
            app.state.injected = injected
            app.state.repository = memory_repository
            app.state.recorder = recorder
            app.state.engine = engine
            app.state.experiment_queue = InMemoryExperimentQueue()
            app.state.idempotency = {}
            try:
                yield
            finally:
                await progress_jobs.shutdown()

    app = FastAPI(
        title="AMLGuard-EU",
        version="0.1.0",
        description=(
            "Synthetic AML investigation research platform; not legal advice "
            "or compliance certification."
        ),
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        https_only=settings.environment == "research",
        same_site="lax",
    )
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health/live,health/ready,metrics",
    )

    oauth = OAuth()
    keycloak_public = str(settings.keycloak_issuer).rstrip("/")
    keycloak_backend = settings.keycloak_backend
    oauth.register(
        name="keycloak",
        client_id=settings.keycloak_client_id,
        client_secret=(
            settings.keycloak_client_secret.get_secret_value()
            if settings.keycloak_client_secret
            else None
        ),
        authorize_url=f"{keycloak_public}/protocol/openid-connect/auth",
        access_token_url=f"{keycloak_backend}/protocol/openid-connect/token",
        issuer=keycloak_public,
        jwks_uri=f"{keycloak_backend}/protocol/openid-connect/certs",
        userinfo_endpoint=f"{keycloak_backend}/protocol/openid-connect/userinfo",
        id_token_signing_alg_values_supported=["RS256"],
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )

    @app.get("/login")
    async def login(request: Request):  # type: ignore[no-untyped-def]
        redirect_uri = request.url_for("auth_callback")
        return await oauth.keycloak.authorize_redirect(
            request,
            redirect_uri,
            prompt="login",
        )

    @app.get("/auth/callback")
    async def auth_callback(request: Request):  # type: ignore[no-untyped-def]
        token = await oauth.keycloak.authorize_access_token(request)
        request.session["user"] = token.get("userinfo", {})
        if isinstance(token.get("id_token"), str):
            request.session["oidc_id_token"] = token["id_token"]
        return RedirectResponse("/")

    @app.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        id_token = request.session.get("oidc_id_token")
        request.session.clear()
        if isinstance(id_token, str) and not settings.dev_auth_bypass:
            logout_url = f"{keycloak_public}/protocol/openid-connect/logout"
            logout_query = urlencode(
                {
                    "id_token_hint": id_token,
                    "post_logout_redirect_uri": str(request.base_url),
                }
            )
            return RedirectResponse(
                f"{logout_url}?{logout_query}",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        return RedirectResponse("/", status_code=303)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        recorder = _recorder(request)
        checks = {
            "repository": hasattr(request.app.state, "repository"),
            "policy_corpus": hasattr(request.app.state, "engine"),
            "artifact_store": not settings.raw_research_capture or recorder.store is not None,
            "telemetry": settings.environment == "test"
            or not settings.otel_enabled
            or telemetry_configured(),
            "oidc": settings.dev_auth_bypass,
            "inference": not settings.eden_model_id or bool(settings.eden_ai_api_key),
        }
        if recorder.store is not None:
            try:
                with tempfile.TemporaryFile(dir=recorder.store.root):
                    pass
            except OSError as exc:
                checks["artifact_store"] = False
                log_event(
                    "readiness_dependency_failed",
                    level=40,
                    dependency="artifact_store",
                    error_type=type(exc).__name__,
                )
        if settings.repository_backend == "postgres":
            try:
                from sqlalchemy import text as sql_text

                async with get_database().session() as session:
                    await session.execute(sql_text("SELECT 1"))
            except Exception as exc:
                checks["repository"] = False
                log_event(
                    "readiness_dependency_failed",
                    level=40,
                    dependency="repository",
                    error_type=type(exc).__name__,
                )
        async with httpx.AsyncClient(timeout=2.0) as client:
            if not settings.dev_auth_bypass:
                try:
                    response = await client.get(
                        f"{settings.keycloak_backend}/.well-known/openid-configuration"
                    )
                    checks["oidc"] = response.status_code == 200
                except httpx.HTTPError:
                    checks["oidc"] = False
            if settings.otel_enabled and settings.environment != "test":
                try:
                    response = await client.get(str(settings.otel_health_endpoint))
                    checks["telemetry"] = response.status_code == 200
                except httpx.HTTPError:
                    checks["telemetry"] = False
            if settings.eden_model_id:
                try:
                    response = await client.get(settings.eden_base_url)
                    checks["inference"] = response.status_code < 500
                except httpx.HTTPError:
                    checks["inference"] = False
        record_readiness(checks)
        ready_status = all(checks.values())
        payload = {
            "status": "ready" if ready_status else "not_ready",
            "checks": checks,
            "inference_endpoint": "EU" if settings.eden_model_id else "local_fake",
            "scenario_count": len(request.app.state.injected),
        }
        return JSONResponse(payload, status_code=200 if ready_status else 503)

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> HTMLResponse:
        try:
            actor = await get_actor(request, authorization, settings)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_401_UNAUTHORIZED:
                raise
            return templates.TemplateResponse(
                request,
                "authentication_required.html",
                {
                    "keycloak_url": str(settings.keycloak_issuer).rstrip("/"),
                    "development_credentials": settings.environment == "development",
                },
                status_code=status.HTTP_200_OK,
            )
        allowed_roles = {"analyst", "reviewer", "researcher", "administrator"}
        if actor.roles.isdisjoint(allowed_roles):
            return templates.TemplateResponse(
                request,
                "access_denied.html",
                {"actor": actor},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        visible_cases: dict[str, CaseData] = {}
        for case in await _repository(request).list_cases():
            try:
                authorize_case(actor, case, "read_case")
            except CaseAccessDenied:
                continue
            visible_cases.setdefault(case.alert_id, case)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "alerts": request.app.state.alerts,
                "actor": actor,
                "cases_by_alert": visible_cases,
            },
        )

    @app.post("/ui/investigations", response_class=HTMLResponse)
    async def ui_start_investigation(
        request: Request,
        alert_id: str = Form(min_length=1),
        context_condition: str = Form(default="B5"),
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> Response:
        try:
            body = StartInvestigationRequest(
                alert_id=alert_id,
                context_condition=context_condition,
            )
            case, created = await _engine(request).prepare(
                alert_id=body.alert_id,
                actor_id=actor.actor_id,
                tenant_id=actor.tenant_id,
            )
        except (PermissionError, ValidationError) as exc:
            return _render_ui_error(request, str(exc), actor)
        if not created:
            existing_run = await _engine(request).get(case.case_id)
            if existing_run.status is not CaseStatus.FAILED:
                return RedirectResponse(
                    f"/ui/investigations/{case.case_id}/page",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
        job = _progress_jobs(request).create(
            case_id=case.case_id,
            run_id=case.run_id,
            actor_id=actor.actor_id,
            tenant_id=actor.tenant_id,
        )
        _progress_jobs(request).spawn(
            _run_ui_investigation(
                request.app,
                job.job_id,
                case,
                actor_id=actor.actor_id,
                context_condition=body.context_condition,
            )
        )
        return RedirectResponse(
            f"/ui/investigations/{case.case_id}/page",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get("/ui/investigation-jobs/{job_id}/page", response_class=HTMLResponse)
    async def ui_investigation_progress_page(
        request: Request,
        job_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> HTMLResponse:
        try:
            job = _progress_jobs(request).get(job_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "investigation job not found") from exc
        await _case_for_action(request, job.case_id, actor, "read_case")
        if job.status == "completed":
            return await _render_investigation_page(
                request,
                await _engine(request).get(job.case_id),
                actor,
                message="Investigation analysis completed.",
            )
        return templates.TemplateResponse(
            request,
            "investigation_progress_page.html",
            {"job": job, "actor": actor},
        )

    @app.get("/ui/investigation-jobs/{job_id}", response_class=HTMLResponse)
    async def ui_investigation_progress(
        request: Request,
        job_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> HTMLResponse:
        try:
            job = _progress_jobs(request).get(job_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "investigation job not found") from exc
        await _case_for_action(request, job.case_id, actor, "read_case")
        if job.status == "completed":
            response = await _render_investigation_workspace(
                request,
                await _engine(request).get(job.case_id),
                actor,
                message="Investigation analysis completed.",
            )
            response.headers["HX-Push-Url"] = f"/ui/investigations/{job.case_id}/page"
            return response
        return _render_investigation_progress(request, job_id, actor)

    @app.get("/ui/investigations/{case_id}", response_class=HTMLResponse)
    async def ui_get_investigation(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer", "researcher")),
    ) -> HTMLResponse:
        await _case_for_action(request, case_id, actor, "read_case")
        return await _render_investigation_workspace(
            request,
            await _engine(request).get(case_id),
            actor,
        )

    @app.get("/ui/investigations/{case_id}/page", response_class=HTMLResponse)
    async def ui_get_investigation_page(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer", "researcher")),
    ) -> HTMLResponse:
        await _case_for_action(request, case_id, actor, "read_case")
        job = _progress_jobs(request).for_case(case_id)
        if job is not None and job.status == "running":
            return templates.TemplateResponse(
                request,
                "investigation_progress_page.html",
                {"job": job, "actor": actor},
            )
        return await _render_investigation_page(
            request,
            await _engine(request).get(case_id),
            actor,
        )

    @app.post("/ui/investigations/{case_id}/reset")
    async def ui_reset_investigation(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> RedirectResponse:
        await _case_for_action(request, case_id, actor, "reset")
        try:
            await _engine(request).reset(case_id, actor_id=actor.actor_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        _progress_jobs(request).discard_case(case_id)
        for cache_key, cached in list(_idempotency(request).items()):
            if str(cached.get("case_id")) == str(case_id):
                _idempotency(request).pop(cache_key, None)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/ui/investigations/{case_id}/resume", response_class=HTMLResponse)
    async def ui_resume_investigation(
        request: Request,
        case_id: UUID,
        information_json: str = Form(min_length=2, max_length=32_768),
        submission_id: str = Form(min_length=1, max_length=200),
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> HTMLResponse:
        await _case_for_action(request, case_id, actor, "supply_information")
        try:
            decoded = json.loads(information_json)
            body = ResumeInvestigationRequest(information=decoded)
            run = await _engine(request).supply_information(
                case_id=case_id,
                actor_id=actor.actor_id,
                information=dict(body.information),
                submission_id=submission_id,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            run = await _engine(request).get(case_id)
            return await _render_investigation_workspace(
                request,
                run,
                actor,
                error=f"Information was not accepted: {exc}",
            )
        return await _render_investigation_workspace(
            request,
            run,
            actor,
            message="Supplemental information added and the investigation was rerun.",
        )

    @app.post("/ui/investigations/{case_id}/claim-review", response_class=HTMLResponse)
    async def ui_claim_review(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("reviewer")),
    ) -> HTMLResponse:
        case = await _case_for_action(request, case_id, actor, "claim_review")
        if case.status is not CaseStatus.WAITING_FOR_HUMAN_REVIEW:
            return await _render_investigation_workspace(
                request,
                await _engine(request).get(case_id),
                actor,
                error="Case is not waiting for human review.",
            )
        try:
            await _repository(request).assign_reviewer(case_id, actor.actor_id)
        except ValueError as exc:
            return await _render_investigation_workspace(
                request,
                await _engine(request).get(case_id),
                actor,
                error=str(exc),
            )
        await _repository(request).audit(
            "case_review_claimed",
            actor.actor_id,
            case_id,
            {"tenant_id": actor.tenant_id},
        )
        return await _render_investigation_workspace(
            request,
            await _engine(request).get(case_id),
            actor,
            message="Review assigned to you.",
        )

    @app.post("/ui/investigations/{case_id}/human-review", response_class=HTMLResponse)
    async def ui_human_review(
        request: Request,
        case_id: UUID,
        recommendation_version: int = Form(ge=1),
        action: str = Form(),
        rationale: str = Form(min_length=1, max_length=4_000),
        actor: Actor = Depends(require_roles("reviewer")),
    ) -> HTMLResponse:
        await _case_for_action(request, case_id, actor, "review")
        try:
            review_action = ReviewAction(action)
            if review_action is ReviewAction.EDIT_AND_APPROVE:
                raise ValueError("Edit-and-approve remains available through the JSON API only")
            review = HumanReview(
                case_id=case_id,
                recommendation_version=recommendation_version,
                action=review_action,
                reviewer_id=actor.actor_id,
                rationale=rationale,
            )
            run = await _engine(request).review(review)
        except ValueError as exc:
            return await _render_investigation_workspace(
                request,
                await _engine(request).get(case_id),
                actor,
                error=f"Review was not accepted: {exc}",
            )
        return await _render_investigation_workspace(
            request,
            run,
            actor,
            message=(
                "Investigation approved and completed."
                if run.status is CaseStatus.COMPLETED
                else "Rework requested; a new recommendation was generated."
            ),
        )

    @app.post("/investigations", status_code=status.HTTP_202_ACCEPTED)
    async def start_investigation(
        request: Request,
        body: StartInvestigationRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> dict[str, object]:
        idempotency = _idempotency(request)
        cached = idempotency.get((actor.actor_id, idempotency_key))
        if cached:
            return cached
        try:
            run = await _engine(request).start(
                alert_id=body.alert_id,
                actor_id=actor.actor_id,
                tenant_id=actor.tenant_id,
                context_condition=body.context_condition,
            )
        except PermissionError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "alert is already assigned within this tenant",
            ) from exc
        record_run(run.status.value)
        log_event("investigation_started", status=run.status.value)
        response = run.model_dump(mode="json")
        idempotency[(actor.actor_id, idempotency_key)] = response
        return response

    @app.get("/investigations/{case_id}")
    async def get_investigation(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer", "researcher")),
    ) -> dict[str, object]:
        await _case_for_action(request, case_id, actor, "read_case")
        return (await _engine(request).get(case_id)).model_dump(mode="json")

    @app.post("/investigations/{case_id}/resume")
    async def resume_investigation(
        request: Request,
        case_id: UUID,
        body: ResumeInvestigationRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
        actor: Actor = Depends(require_roles("analyst", "reviewer")),
    ) -> dict[str, object]:
        await _case_for_action(request, case_id, actor, "supply_information")
        try:
            run = await _engine(request).supply_information(
                case_id=case_id,
                actor_id=actor.actor_id,
                information=dict(body.information),
                submission_id=idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return run.model_dump(mode="json")

    @app.get("/investigations/{case_id}/evidence")
    async def get_evidence(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("analyst", "reviewer", "researcher")),
    ) -> list[dict[str, Any]]:
        await _case_for_action(request, case_id, actor, "read_evidence")
        run = await _engine(request).get(case_id)
        return [item.model_dump(mode="json") for item in run.evidence]

    @app.get("/investigations/{case_id}/trace")
    async def get_trace(
        request: Request,
        case_id: UUID,
        actor: Actor = Depends(require_roles("researcher")),
    ) -> list[dict[str, Any]]:
        case = await _case_for_action(request, case_id, actor, "read_trace")
        return _recorder(request).events.get(case.run_id, [])

    @app.post("/investigations/{case_id}/claim-review")
    async def claim_review(
        request: Request,
        case_id: UUID,
        _idempotency_key: str = Header(alias="Idempotency-Key"),
        actor: Actor = Depends(require_roles("reviewer")),
    ) -> dict[str, str]:
        case = await _case_for_action(request, case_id, actor, "claim_review")
        if case.status is not CaseStatus.WAITING_FOR_HUMAN_REVIEW:
            raise HTTPException(status.HTTP_409_CONFLICT, "case is not waiting for human review")
        try:
            await _repository(request).assign_reviewer(case_id, actor.actor_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        await _repository(request).audit(
            "case_review_claimed",
            actor.actor_id,
            case_id,
            {"tenant_id": actor.tenant_id},
        )
        return {
            "case_id": str(case_id),
            "reviewer_id": actor.actor_id,
            "status": "ASSIGNED",
        }

    @app.post("/investigations/{case_id}/human-review")
    async def human_review(
        request: Request,
        case_id: UUID,
        body: HumanReviewRequest,
        _idempotency_key: str = Header(alias="Idempotency-Key"),
        actor: Actor = Depends(require_roles("reviewer")),
    ) -> dict[str, object]:
        await _case_for_action(request, case_id, actor, "review")
        review = HumanReview(
            case_id=case_id,
            recommendation_version=body.recommendation_version,
            action=body.action,
            reviewer_id=actor.actor_id,
            rationale=body.rationale,
            edited_recommendation=body.edited_recommendation,
        )
        return (await _engine(request).review(review)).model_dump(mode="json")

    @app.post("/experiments", status_code=status.HTTP_202_ACCEPTED)
    async def schedule_experiment(
        request: Request,
        body: ScheduleExperimentRequest,
        _idempotency_key: str = Header(alias="Idempotency-Key"),
        _actor: Actor = Depends(require_roles("researcher")),
    ) -> dict[str, object]:
        if settings.experiment_kill_switch:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "experiment kill switch active"
            )
        scenarios = body.scenario_ids or [
            item.scenario_id for item in build_catalog() if item.pack == body.manifest.scenario_pack
        ]
        jobs = await _queue(request).schedule(body.manifest, scenarios)
        return {"experiment_id": str(body.manifest.experiment_id), "status": "QUEUED", "jobs": jobs}

    @app.post("/experiments/{experiment_id}/stop")
    async def stop_experiment(
        request: Request,
        experiment_id: UUID,
        _idempotency_key: str = Header(alias="Idempotency-Key"),
        _actor: Actor = Depends(require_roles("researcher")),
    ) -> dict[str, str]:
        await _queue(request).stop(experiment_id)
        return {"status": "STOPPED"}

    @app.post("/experiments/{experiment_id}/resume")
    async def resume_experiment(
        request: Request,
        experiment_id: UUID,
        _idempotency_key: str = Header(alias="Idempotency-Key"),
        _actor: Actor = Depends(require_roles("researcher")),
    ) -> dict[str, str]:
        await _queue(request).resume(experiment_id)
        return {"status": "RUNNING"}

    @app.get("/experiments/{experiment_id}")
    async def get_experiment(
        request: Request,
        experiment_id: UUID,
        _actor: Actor = Depends(require_roles("researcher")),
    ) -> dict[str, object]:
        try:
            return await _queue(request).describe(experiment_id)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "experiment not found") from exc

    @app.get("/experiments/{experiment_id}/results")
    async def get_experiment_results(
        request: Request,
        experiment_id: UUID,
        _actor: Actor = Depends(require_roles("researcher")),
    ) -> dict[str, object]:
        results = await _queue(request).results_for(experiment_id)
        return {
            "experiment_id": str(experiment_id),
            "results": results,
            "proofagent_compliance_coverage": summarize_compliance_coverage(results),
        }

    return app

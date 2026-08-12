import re
import time
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from amlguard.api.app import create_app
from amlguard.config import Settings
from amlguard.tools.repository import InMemoryInvestigationRepository


def test_health_and_prometheus_monitoring_are_operational(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert all(ready.json()["checks"].values())

        alert_id = cast(FastAPI, client.app).state.alerts[0].alert_id
        started = client.post(
            "/investigations",
            headers={"Idempotency-Key": "monitoring-start-1"},
            json={"alert_id": alert_id},
        )
        assert started.status_code == 202

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "amlguard_runs_total" in metrics.text
        assert "amlguard_investigation_stage_duration_seconds_bucket" in metrics.text
        assert 'amlguard_dependency_ready{dependency="repository"} 1.0' in metrics.text

        home = client.get("/")
        assert home.status_code == 200
        assert "Sign out" in home.text
        assert "Signed in as" in home.text
        assert "dev-administrator" in home.text
        assert 'action="/logout"' in home.text
        assert (
            'integrity="sha384-HGfztofotfshcF7+8n44JQL2oJmowVChPTg48S+'
            'jvZoztPfvwD79OC/LTtG6dMp+"'
        ) in home.text

        logged_out = client.post("/logout", follow_redirects=False)
        assert logged_out.status_code == 303
        assert logged_out.headers["location"] == "/"


def test_home_explains_keycloak_login_without_exposing_protected_api(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="development",
        repository_backend="memory",
        dev_auth_bypass=False,
        artifact_root=tmp_path,
        otel_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Sign in with Keycloak" in home.text
        assert 'href="/login"' in home.text
        assert "administrator-dev" in home.text

        protected = client.post(
            "/investigations",
            headers={"Idempotency-Key": "unauthenticated-request"},
            json={"alert_id": "ALT-UNKNOWN"},
        )
        assert protected.status_code == 401
        assert protected.json() == {"detail": "authentication required"}


def test_frontend_launches_and_reviews_an_investigation(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        app = cast(FastAPI, client.app)
        alert_id = app.state.alerts[0].alert_id

        home = client.get("/")
        assert home.status_code == 200
        assert "Investigate" in home.text
        assert 'action="/ui/investigations"' in home.text
        assert 'method="post"' in home.text

        launched = client.post(
            "/ui/investigations",
            headers={"X-Actor-ID": "ui-analyst", "X-Roles": "analyst"},
            data={"alert_id": alert_id, "context_condition": "B5"},
        )
        assert launched.status_code == 200
        assert launched.history[0].status_code == 303
        assert "/ui/investigations/" in str(launched.url)
        assert str(launched.url).endswith("/page")
        assert "Back to alerts" in launched.text
        assert "Investigation in progress" in launched.text
        assert "Loading evidence and applicable policy" in launched.text
        assert "Drafting the recommendation" in launched.text
        assert "Validating safeguards and citations" in launched.text
        assert 'hx-trigger="every 500ms"' in launched.text
        progress_match = re.search(r'hx-get="([^"]+)"', launched.text)
        assert progress_match is not None

        progress_headers = {"X-Actor-ID": "ui-analyst", "X-Roles": "analyst"}
        for _ in range(100):
            progress = client.get(progress_match.group(1), headers=progress_headers)
            assert progress.status_code == 200
            if "WAITING_FOR_HUMAN_REVIEW" in progress.text:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("the UI investigation did not complete")

        assert "Investigation analysis completed." in progress.text
        assert "Material findings" in progress.text
        assert "Control results" in progress.text
        assert "Retrieved policy" in progress.text
        assert "Show approved policy text" in progress.text
        assert "complete approved excerpts" in progress.text
        assert "Show evidence content" in progress.text
        assert "Source record" in progress.text
        assert "SHA-256" in progress.text
        assert "fingerprint" in progress.text
        assert "Triggered this alert" in progress.text
        assert "triggering-evidence" in progress.text
        evidence_section = progress.text.index("Evidence inventory")
        assert progress.text.index("Triggered this alert", evidence_section) < progress.text.index(
            "Alert", evidence_section
        )
        assert "must be claimed by an eligible reviewer" in progress.text
        assert progress.headers["HX-Push-Url"].endswith("/page")

        durable_page = client.get(
            progress.headers["HX-Push-Url"],
            headers=progress_headers,
        )
        assert durable_page.status_code == 200
        assert "WAITING_FOR_HUMAN_REVIEW" in durable_page.text
        assert "Material findings" in durable_page.text

        repository = cast(InMemoryInvestigationRepository, app.state.repository)
        case = next(iter(repository.cases.values()))
        claimed = client.post(
            f"/ui/investigations/{case.case_id}/claim-review",
            headers={"X-Actor-ID": "ui-reviewer", "X-Roles": "reviewer"},
        )
        assert claimed.status_code == 200
        assert "Review assigned to you." in claimed.text
        assert "Human review" in claimed.text
        assert "Show an example rationale" in claimed.text
        assert "Write a case-specific explanation" in claimed.text
        assert "Evidence, policy citations, controls, and limitations reviewed." not in claimed.text

        reviewed = client.post(
            f"/ui/investigations/{case.case_id}/human-review",
            headers={"X-Actor-ID": "ui-reviewer", "X-Roles": "reviewer"},
            data={
                "recommendation_version": case.recommendation_version,
                "action": "APPROVE",
                "rationale": "Frontend review of evidence, policy, controls, and limitations.",
            },
        )
        assert reviewed.status_code == 200
        assert "Investigation approved and completed." in reviewed.text
        assert "COMPLETED" in reviewed.text
        assert "Review decisions" in reviewed.text
        assert "Approve" in reviewed.text
        assert "ui-reviewer" in reviewed.text
        assert "Frontend review of evidence, policy, controls, and limitations." in reviewed.text

        completed_page = client.get(
            f"/ui/investigations/{case.case_id}/page",
            headers={"X-Actor-ID": "ui-reviewer", "X-Roles": "reviewer"},
        )
        assert completed_page.status_code == 200
        assert "Review decisions" in completed_page.text
        assert "Frontend review of evidence, policy, controls, and limitations." in (
            completed_page.text
        )


def test_home_shows_case_status_and_can_reset_an_investigation(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        app = cast(FastAPI, client.app)
        alert_id = app.state.alerts[0].alert_id
        actor_headers = {"X-Actor-ID": "reset-analyst", "X-Roles": "analyst"}
        started = client.post(
            "/investigations",
            headers={**actor_headers, "Idempotency-Key": "reset-start-1"},
            json={"alert_id": alert_id, "context_condition": "B5"},
        )
        assert started.status_code == 202
        first_run = started.json()

        home = client.get("/", headers=actor_headers)
        assert first_run["status"] in home.text
        assert "See results" in home.text
        assert "Reset investigation" in home.text
        assert "Confirm reset" in home.text

        reset = client.post(
            f"/ui/investigations/{first_run['case_id']}/reset",
            headers=actor_headers,
        )
        assert reset.status_code == 200
        assert reset.history[0].status_code == 303
        assert "Not started" in reset.text
        assert "Investigate" in reset.text

        repository = cast(InMemoryInvestigationRepository, app.state.repository)
        assert repository.cases == {}
        assert repository.audit_events[-1]["event_type"] == "investigation_reset"

        restarted = client.post(
            "/investigations",
            headers={**actor_headers, "Idempotency-Key": "reset-start-2"},
            json={"alert_id": alert_id, "context_condition": "B5"},
        )
        assert restarted.status_code == 202
        second_run = restarted.json()
        assert second_run["case_id"] != first_run["case_id"]
        assert second_run["recommendation_version"] == 1


def test_api_investigation_and_human_review(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        alert_id = cast(FastAPI, client.app).state.alerts[0].alert_id
        obsolete_condition = client.post(
            "/investigations",
            headers={
                "Idempotency-Key": "obsolete-start-1",
                "X-Actor-ID": "analyst-1",
                "X-Roles": "analyst",
            },
            json={
                "alert_id": alert_id,
                "context_condition": "B5",
                "orchestration_condition": "O1",
            },
        )
        assert obsolete_condition.status_code == 422

        headers = {
            "Idempotency-Key": "start-1",
            "X-Actor-ID": "analyst-1",
            "X-Roles": "analyst",
        }
        response = client.post(
            "/investigations",
            headers=headers,
            json={"alert_id": alert_id, "context_condition": "B5"},
        )
        assert response.status_code == 202
        run = response.json()
        assert run["status"] == "WAITING_FOR_HUMAN_REVIEW"
        assert run["policies"]
        assert run["policy_as_of_date"]
        assert any(
            item["control_id"] == "POLICY-CITATION-001"
            and item["outcome"] == "PASS"
            for item in run["control_results"]
        )

        repeated = client.post(
            "/investigations",
            headers=headers,
            json={"alert_id": alert_id, "context_condition": "B5"},
        )
        assert repeated.json()["case_id"] == run["case_id"]

        claimed = client.post(
            f"/investigations/{run['case_id']}/claim-review",
            headers={
                "Idempotency-Key": "claim-1",
                "X-Actor-ID": "reviewer-1",
                "X-Roles": "reviewer",
            },
        )
        assert claimed.status_code == 200

        reviewed = client.post(
            f"/investigations/{run['case_id']}/human-review",
            headers={
                "Idempotency-Key": "review-1",
                "X-Actor-ID": "reviewer-1",
                "X-Roles": "reviewer",
            },
            json={
                "recommendation_version": 1,
                "action": "APPROVE",
                "rationale": "Reviewed the synthetic evidence and limitations.",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "COMPLETED"


def test_administrator_has_full_access_while_narrow_roles_remain_restricted(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        alert_id = cast(FastAPI, client.app).state.alerts[0].alert_id
        admin_headers = {
            "Idempotency-Key": "admin-start-1",
            "X-Actor-ID": "admin-1",
            "X-Roles": "administrator",
        }
        started = client.post(
            "/investigations",
            headers=admin_headers,
            json={"alert_id": alert_id, "context_condition": "B5"},
        )
        assert started.status_code == 202
        run = started.json()

        denied_trace = client.get(
            f"/investigations/{run['case_id']}/trace",
            headers={"X-Roles": "analyst"},
        )
        assert denied_trace.status_code == 403

        admin_trace = client.get(
            f"/investigations/{run['case_id']}/trace",
        )
        assert admin_trace.status_code == 200
        assert "policies_retrieved" in {
            item["event_type"] for item in admin_trace.json()
        }

        reviewed = client.post(
            f"/investigations/{run['case_id']}/human-review",
            headers={
                "Idempotency-Key": "admin-review-1",
                "X-Actor-ID": "admin-1",
                "X-Roles": "administrator",
            },
            json={
                "recommendation_version": 1,
                "action": "APPROVE",
                "rationale": "Administrator review for the simplified workflow.",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "COMPLETED"


def test_resume_adds_information_as_evidence_and_restarts_analysis(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        app = cast(FastAPI, client.app)
        repository = cast(InMemoryInvestigationRepository, app.state.repository)
        missing_customer = next(
            item.customer_id for item in repository.bank.kyc_records if item.status == "missing"
        )
        alert = next(
            item for item in repository.bank.alerts if item.customer_id == missing_customer
        )
        started = client.post(
            "/investigations",
            headers={"Idempotency-Key": "information-start-1"},
            json={"alert_id": alert.alert_id},
        )
        assert started.status_code == 202
        waiting = started.json()
        assert waiting["status"] == "WAITING_FOR_INFORMATION"
        assert waiting["recommendation"]["recommendation"] == "REQUEST_MORE_INFORMATION"

        denied = client.post(
            f"/investigations/{waiting['case_id']}/resume",
            headers={"Idempotency-Key": "information-1", "X-Roles": "researcher"},
            json={"information": {"source_of_funds": "Synthetic salary certificate"}},
        )
        assert denied.status_code == 403

        resumed = client.post(
            f"/investigations/{waiting['case_id']}/resume",
            headers={"Idempotency-Key": "information-1"},
            json={"information": {"source_of_funds": "Synthetic salary certificate"}},
        )
        assert resumed.status_code == 200
        updated = resumed.json()
        assert updated["status"] == "WAITING_FOR_HUMAN_REVIEW"
        assert updated["recommendation_version"] == 2
        supplemental = [
            item
            for item in updated["evidence"]
            if item["evidence_type"] == "supplemental_information"
        ]
        assert len(supplemental) == 1
        assert supplemental[0]["content"]["information"] == {
            "source_of_funds": "Synthetic salary certificate"
        }

        repeated = client.post(
            f"/investigations/{waiting['case_id']}/resume",
            headers={"Idempotency-Key": "information-1"},
            json={"information": {"source_of_funds": "Synthetic salary certificate"}},
        )
        assert repeated.status_code == 409

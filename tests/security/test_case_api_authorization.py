from pathlib import Path

from fastapi.testclient import TestClient

from amlguard.api.app import create_app
from amlguard.config import Settings


def _headers(
    actor_id: str,
    roles: str,
    tenant_id: str,
    *,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    headers = {
        "X-Actor-ID": actor_id,
        "X-Roles": roles,
        "X-Tenant-ID": tenant_id,
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def test_case_reads_enforce_assignment_and_tenant_ownership(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        repository_backend="memory",
        dev_auth_bypass=True,
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        alert_id = client.app.state.alerts[0].alert_id
        started = client.post(
            "/investigations",
            headers=_headers(
                "analyst-a",
                "analyst",
                "tenant-a",
                idempotency_key="tenant-start-1",
            ),
            json={"alert_id": alert_id},
        )
        assert started.status_code == 202
        case_id = started.json()["case_id"]

        conflicting_start = client.post(
            "/investigations",
            headers=_headers(
                "analyst-b",
                "analyst",
                "tenant-a",
                idempotency_key="tenant-start-2",
            ),
            json={"alert_id": alert_id},
        )
        assert conflicting_start.status_code == 409

        other_tenant_start = client.post(
            "/investigations",
            headers=_headers(
                "analyst-b",
                "analyst",
                "tenant-b",
                idempotency_key="other-tenant-start-1",
            ),
            json={"alert_id": alert_id},
        )
        assert other_tenant_start.status_code == 202
        assert other_tenant_start.json()["case_id"] != case_id

        assert (
            client.get(
                f"/investigations/{case_id}",
                headers=_headers("analyst-a", "analyst", "tenant-a"),
            ).status_code
            == 200
        )
        for path in (
            f"/investigations/{case_id}",
            f"/investigations/{case_id}/evidence",
        ):
            assert (
                client.get(
                    path,
                    headers=_headers("analyst-b", "analyst", "tenant-a"),
                ).status_code
                == 404
            )

        own_review_claim = client.post(
            f"/investigations/{case_id}/claim-review",
            headers=_headers(
                "analyst-a",
                "reviewer",
                "tenant-a",
                idempotency_key="own-claim-1",
            ),
        )
        assert own_review_claim.status_code == 404

        cross_tenant_claim = client.post(
            f"/investigations/{case_id}/claim-review",
            headers=_headers(
                "reviewer-b",
                "reviewer",
                "tenant-b",
                idempotency_key="cross-tenant-claim-1",
            ),
        )
        assert cross_tenant_claim.status_code == 404

        claim = client.post(
            f"/investigations/{case_id}/claim-review",
            headers=_headers(
                "reviewer-a",
                "reviewer",
                "tenant-a",
                idempotency_key="claim-1",
            ),
        )
        assert claim.status_code == 200
        assert (
            client.get(
                f"/investigations/{case_id}/evidence",
                headers=_headers("reviewer-a", "reviewer", "tenant-a"),
            ).status_code
            == 200
        )

        for path in (
            f"/investigations/{case_id}",
            f"/investigations/{case_id}/evidence",
            f"/investigations/{case_id}/trace",
        ):
            assert (
                client.get(
                    path,
                    headers=_headers("researcher-a", "researcher", "tenant-a"),
                ).status_code
                == 200
            )
            assert (
                client.get(
                    path,
                    headers=_headers("researcher-b", "researcher", "tenant-b"),
                ).status_code
                == 404
            )

        assert (
            client.get(
                f"/investigations/{case_id}/trace",
                headers=_headers("admin-b", "administrator", "tenant-b"),
            ).status_code
            == 200
        )

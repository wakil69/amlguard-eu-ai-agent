from pathlib import Path

from amlguard.monitoring.artifacts import EncryptedArtifactStore
from amlguard.monitoring.redaction import redact


def test_restricted_artifact_is_encrypted_and_authenticated(tmp_path: Path) -> None:
    store = EncryptedArtifactStore(tmp_path, b"K" * 32)
    reference = store.put_json({"prompt": "synthetic full prompt", "tool_result": {"id": "TX-1"}})
    blob = (tmp_path / reference.relative_path).read_bytes()
    assert b"synthetic full prompt" not in blob
    assert store.get_json(reference)["tool_result"] == {"id": "TX-1"}


def test_operational_redaction_removes_secrets() -> None:
    value = redact(
        {
            "authorization": "Bearer canary-secret",
            "nested": {"api_key": "canary-key"},
            "message": "Authorization bearer another-secret",
        }
    )
    rendered = str(value)
    assert "canary" not in rendered
    assert "another-secret" not in rendered

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class ArtifactReference:
    content_hash: str
    relative_path: str
    encryption_algorithm: str = "AES-256-GCM"


class EncryptedArtifactStore:
    """Content-addressed AES-GCM storage for complete synthetic trajectories."""

    def __init__(self, root: Path, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("artifact encryption key must be exactly 32 bytes")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._cipher = AESGCM(key)

    @classmethod
    def from_key_file(cls, root: Path, key_file: Path) -> EncryptedArtifactStore:
        key = key_file.read_bytes().strip()
        if len(key) == 64:
            try:
                key = bytes.fromhex(key.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                pass
        return cls(root, key)

    def put_json(self, payload: dict[str, Any]) -> ArtifactReference:
        cleartext = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        digest = hashlib.sha256(cleartext).hexdigest()
        nonce = __import__("os").urandom(12)
        ciphertext = self._cipher.encrypt(nonce, cleartext, digest.encode())
        relative = Path(digest[:2]) / f"{digest}.agx"
        target = (self.root / relative).resolve()
        if self.root not in target.parents:
            raise ValueError("artifact path escaped configured root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(nonce + ciphertext)
        return ArtifactReference(digest, relative.as_posix())

    def get_json(self, reference: ArtifactReference) -> dict[str, Any]:
        target = (self.root / reference.relative_path).resolve()
        if self.root not in target.parents:
            raise ValueError("artifact path escaped configured root")
        blob = target.read_bytes()
        cleartext = self._cipher.decrypt(blob[:12], blob[12:], reference.content_hash.encode())
        if hashlib.sha256(cleartext).hexdigest() != reference.content_hash:
            raise ValueError("artifact integrity check failed")
        value = json.loads(cleartext)
        if not isinstance(value, dict):
            raise ValueError("research artifact must be a JSON object")
        return value


class TrajectoryRecorder:
    def __init__(self, store: EncryptedArtifactStore | None = None) -> None:
        self.store = store
        self.events: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        self.latest: dict[UUID, ArtifactReference] = {}

    async def record(self, run_id: UUID, event_type: str, payload: dict[str, Any]) -> None:
        self.events[run_id].append({"event_type": event_type, "payload": payload})
        if self.store:
            self.latest[run_id] = self.store.put_json(
                {"run_id": str(run_id), "events": self.events[run_id]}
            )

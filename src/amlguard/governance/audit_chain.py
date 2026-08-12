from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class ChainedAuditEvent:
    sequence: int
    event_type: str
    actor_id: str
    case_id: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


def calculate_event_hash(
    *,
    sequence: int,
    event_type: str,
    actor_id: str,
    case_id: str,
    payload: dict[str, Any],
    previous_hash: str,
) -> str:
    canonical = json.dumps(
        {
            "sequence": sequence,
            "event_type": event_type,
            "actor_id": actor_id,
            "case_id": case_id,
            "payload": payload,
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_chain(events: list[ChainedAuditEvent]) -> list[int]:
    invalid: list[int] = []
    previous = GENESIS_HASH
    for event in sorted(events, key=lambda item: item.sequence):
        expected = calculate_event_hash(
            sequence=event.sequence,
            event_type=event.event_type,
            actor_id=event.actor_id,
            case_id=event.case_id,
            payload=event.payload,
            previous_hash=previous,
        )
        if event.previous_hash != previous or event.event_hash != expected:
            invalid.append(event.sequence)
        previous = event.event_hash
    return invalid

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from amlguard.domain.models import EvidenceItem, InvestigationRecommendation


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def evidence_from_model(
    *,
    evidence_id: str,
    evidence_type: str,
    source_record_id: str,
    case_id: UUID,
    customer_id: str,
    value: BaseModel | dict[str, Any],
    provenance: str,
) -> EvidenceItem:
    content = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        source_record_id=source_record_id,
        case_id=case_id,
        customer_id=customer_id,
        content=content,
        content_hash=canonical_hash(content),
        provenance=provenance,
    )


class EvidenceLedger:
    def __init__(self, items: list[EvidenceItem] | None = None) -> None:
        self._items = {item.evidence_id: item for item in items or []}

    def add(self, item: EvidenceItem) -> None:
        previous = self._items.get(item.evidence_id)
        if previous and previous.content_hash != item.content_hash:
            raise ValueError(f"evidence ID collision: {item.evidence_id}")
        self._items[item.evidence_id] = item

    def items(self) -> list[EvidenceItem]:
        return list(self._items.values())

    def validate_recommendation(self, recommendation: InvestigationRecommendation) -> list[str]:
        available = set(self._items)
        cited = {
            evidence_id
            for finding in [*recommendation.material_findings, *recommendation.counter_indicators]
            for evidence_id in finding.evidence_ids
        }
        return sorted(cited - available)

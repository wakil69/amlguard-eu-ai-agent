from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from amlguard.domain.enums import CaseStatus
from amlguard.domain.models import HumanReview, InvestigationRecommendation
from amlguard.governance.audit_chain import GENESIS_HASH, calculate_event_hash
from amlguard.simulation.models import (
    SyntheticAlert,
    SyntheticBank,
    SyntheticCustomer,
    SyntheticKYC,
    SyntheticTransaction,
)

T = TypeVar("T")


@dataclass
class CaseData:
    case_id: UUID
    run_id: UUID
    case_ref: str
    alert_id: str
    customer_id: str
    tenant_id: str
    assigned_investigator_id: str
    assigned_reviewer_id: str | None = None
    status: CaseStatus = CaseStatus.OPEN
    recommendation: InvestigationRecommendation | None = None
    recommendation_version: int = 0
    reviews: list[HumanReview] = field(default_factory=list)


class InvestigationRepository(Protocol):
    async def list_alerts(self) -> list[SyntheticAlert]: ...
    async def list_cases(self) -> list[CaseData]: ...
    async def create_case(
        self, alert_id: str, *, tenant_id: str, investigator_id: str
    ) -> tuple[CaseData, bool]: ...
    async def get_case(self, case_id: UUID) -> CaseData: ...
    async def delete_case(self, case_id: UUID) -> None: ...
    async def get_alert(self, alert_id: str) -> SyntheticAlert: ...
    async def get_customer(self, customer_id: str) -> SyntheticCustomer: ...
    async def get_kyc(self, customer_id: str) -> SyntheticKYC: ...
    async def get_transactions(self, customer_id: str) -> list[SyntheticTransaction]: ...
    async def save_recommendation(
        self, case_id: UUID, recommendation: InvestigationRecommendation
    ) -> int: ...
    async def save_review(self, review: HumanReview) -> None: ...
    async def assign_reviewer(self, case_id: UUID, reviewer_id: str) -> None: ...
    async def set_status(self, case_id: UUID, status: CaseStatus) -> None: ...
    async def audit(
        self, event_type: str, actor_id: str, case_id: UUID, payload: dict[str, object]
    ) -> None: ...


class InMemoryInvestigationRepository:
    def __init__(self, bank: SyntheticBank) -> None:
        self.bank = bank
        self.cases: dict[UUID, CaseData] = {}
        self.audit_events: list[dict[str, object]] = []

    async def list_alerts(self) -> list[SyntheticAlert]:
        return list(self.bank.alerts)

    async def list_cases(self) -> list[CaseData]:
        return list(reversed(list(self.cases.values())))

    async def create_case(
        self, alert_id: str, *, tenant_id: str, investigator_id: str
    ) -> tuple[CaseData, bool]:
        existing = next(
            (
                item
                for item in self.cases.values()
                if item.alert_id == alert_id and item.tenant_id == tenant_id
            ),
            None,
        )
        if existing:
            if existing.assigned_investigator_id != investigator_id:
                raise PermissionError("alert is already assigned to another investigator")
            return existing, False
        alert = await self.get_alert(alert_id)
        case_id = uuid4()
        case = CaseData(
            case_id=case_id,
            run_id=uuid4(),
            case_ref=f"CASE-{str(case_id)[:8].upper()}",
            alert_id=alert_id,
            customer_id=alert.customer_id,
            tenant_id=tenant_id,
            assigned_investigator_id=investigator_id,
        )
        self.cases[case_id] = case
        return case, True

    async def get_case(self, case_id: UUID) -> CaseData:
        try:
            return self.cases[case_id]
        except KeyError as exc:
            raise KeyError(f"unknown case {case_id}") from exc

    async def delete_case(self, case_id: UUID) -> None:
        try:
            del self.cases[case_id]
        except KeyError as exc:
            raise KeyError(f"unknown case {case_id}") from exc

    async def get_alert(self, alert_id: str) -> SyntheticAlert:
        return self._one(self.bank.alerts, "alert_id", alert_id)

    async def get_customer(self, customer_id: str) -> SyntheticCustomer:
        return self._one(self.bank.customers, "customer_id", customer_id)

    async def get_kyc(self, customer_id: str) -> SyntheticKYC:
        return self._one(self.bank.kyc_records, "customer_id", customer_id)

    async def get_transactions(self, customer_id: str) -> list[SyntheticTransaction]:
        return [item for item in self.bank.transactions if item.customer_id == customer_id]

    async def save_recommendation(
        self, case_id: UUID, recommendation: InvestigationRecommendation
    ) -> int:
        case = await self.get_case(case_id)
        case.recommendation_version += 1
        case.recommendation = recommendation
        return case.recommendation_version

    async def save_review(self, review: HumanReview) -> None:
        case = await self.get_case(review.case_id)
        if any(
            item.recommendation_version == review.recommendation_version
            and item.action == review.action
            for item in case.reviews
        ):
            raise ValueError("duplicate review")
        case.reviews.append(review)

    async def assign_reviewer(self, case_id: UUID, reviewer_id: str) -> None:
        case = await self.get_case(case_id)
        if case.assigned_reviewer_id not in (None, reviewer_id):
            raise ValueError("case review is already assigned")
        case.assigned_reviewer_id = reviewer_id

    async def set_status(self, case_id: UUID, status: CaseStatus) -> None:
        (await self.get_case(case_id)).status = status

    async def audit(
        self, event_type: str, actor_id: str, case_id: UUID, payload: dict[str, object]
    ) -> None:
        sequence = len(self.audit_events) + 1
        previous_hash = (
            str(self.audit_events[-1]["event_hash"]) if self.audit_events else GENESIS_HASH
        )
        event_hash = calculate_event_hash(
            sequence=sequence,
            event_type=event_type,
            actor_id=actor_id,
            case_id=str(case_id),
            payload=payload,
            previous_hash=previous_hash,
        )
        self.audit_events.append(
            {
                "sequence": sequence,
                "event_type": event_type,
                "actor_id": actor_id,
                "case_id": case_id,
                "payload": payload,
                "previous_hash": previous_hash,
                "event_hash": event_hash,
            }
        )

    @staticmethod
    def _one(items: Sequence[T], attribute: str, value: str) -> T:
        for item in items:
            if getattr(item, attribute) == value:
                return item
        raise KeyError(f"unknown {attribute}={value}")

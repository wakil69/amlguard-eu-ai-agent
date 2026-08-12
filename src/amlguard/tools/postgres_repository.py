from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from amlguard.db.models import (
    AlertRecord,
    AuditEventRecord,
    AuthorizedResourceRecord,
    CaseRecord,
    CustomerRecord,
    HumanReviewRecord,
    KYCRecord,
    RecommendationRecord,
    TransactionRecord,
)
from amlguard.db.session import Database
from amlguard.domain.enums import CaseStatus, ReviewAction
from amlguard.domain.models import HumanReview, InvestigationRecommendation
from amlguard.governance.audit_chain import GENESIS_HASH, calculate_event_hash
from amlguard.simulation.models import (
    SyntheticAlert,
    SyntheticCustomer,
    SyntheticKYC,
    SyntheticTransaction,
)
from amlguard.tools.repository import CaseData


class PostgresInvestigationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_alerts(self) -> list[SyntheticAlert]:
        async with self.database.session() as session:
            refs = list((await session.execute(select(AlertRecord.alert_ref))).scalars())
        return [await self.get_alert(ref) for ref in refs]

    async def list_cases(self) -> list[CaseData]:
        async with self.database.session() as session:
            records = list(
                (
                    await session.execute(
                        select(CaseRecord).order_by(CaseRecord.updated_at.desc())
                    )
                ).scalars()
            )
        return [await self._case_data(record) for record in records]

    async def create_case(
        self, alert_id: str, *, tenant_id: str, investigator_id: str
    ) -> tuple[CaseData, bool]:
        async with self.database.session() as session:
            alert = (
                await session.execute(select(AlertRecord).where(AlertRecord.alert_ref == alert_id))
            ).scalar_one()
            existing = (
                await session.execute(
                    select(CaseRecord).where(
                        CaseRecord.alert_id == alert.id,
                        CaseRecord.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                if existing.assigned_investigator_id != investigator_id:
                    raise PermissionError("alert is already assigned to another investigator")
                return await self._case_data(existing), False
            case_id = uuid4()
            record = CaseRecord(
                id=case_id,
                case_ref=f"CASE-{str(case_id)[:8].upper()}",
                alert_id=alert.id,
                customer_id=alert.customer_id,
                tenant_id=tenant_id,
                assigned_investigator_id=investigator_id,
                status=CaseStatus.OPEN.value,
            )
            session.add(record)
        return await self._case_data(record), True

    async def get_case(self, case_id: UUID) -> CaseData:
        async with self.database.session() as session:
            record = (
                await session.execute(select(CaseRecord).where(CaseRecord.id == case_id))
            ).scalar_one_or_none()
        if record is None:
            raise KeyError(f"unknown case {case_id}")
        return await self._case_data(record)

    async def delete_case(self, case_id: UUID) -> None:
        async with self.database.session() as session:
            exists = (
                await session.execute(select(CaseRecord.id).where(CaseRecord.id == case_id))
            ).scalar_one_or_none()
            if exists is None:
                raise KeyError(f"unknown case {case_id}")
            await session.execute(
                delete(HumanReviewRecord).where(HumanReviewRecord.case_id == case_id)
            )
            await session.execute(
                delete(RecommendationRecord).where(RecommendationRecord.case_id == case_id)
            )
            await session.execute(
                delete(AuthorizedResourceRecord).where(
                    AuthorizedResourceRecord.case_id == case_id
                )
            )
            await session.execute(delete(CaseRecord).where(CaseRecord.id == case_id))

    async def _case_data(self, record: CaseRecord) -> CaseData:
        async with self.database.session() as session:
            alert_ref = (
                await session.execute(
                    select(AlertRecord.alert_ref).where(AlertRecord.id == record.alert_id)
                )
            ).scalar_one()
            customer_ref = (
                await session.execute(
                    select(CustomerRecord.customer_ref).where(
                        CustomerRecord.id == record.customer_id
                    )
                )
            ).scalar_one()
            recommendation_row = (
                await session.execute(
                    select(RecommendationRecord)
                    .where(RecommendationRecord.case_id == record.id)
                    .order_by(RecommendationRecord.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            review_rows = list(
                (
                    await session.execute(
                        select(HumanReviewRecord)
                        .where(HumanReviewRecord.case_id == record.id)
                        .order_by(HumanReviewRecord.reviewed_at)
                    )
                ).scalars()
            )
        return CaseData(
            case_id=record.id,
            run_id=record.id,
            case_ref=record.case_ref,
            alert_id=alert_ref,
            customer_id=customer_ref,
            tenant_id=record.tenant_id,
            assigned_investigator_id=record.assigned_investigator_id,
            assigned_reviewer_id=record.assigned_reviewer_id,
            status=CaseStatus(record.status),
            recommendation=(
                InvestigationRecommendation.model_validate(recommendation_row.payload)
                if recommendation_row
                else None
            ),
            recommendation_version=recommendation_row.version if recommendation_row else 0,
            reviews=[
                HumanReview(
                    review_id=review.id,
                    case_id=record.id,
                    recommendation_version=review.recommendation_version,
                    action=ReviewAction(review.action),
                    reviewer_id=review.reviewer_id,
                    rationale=review.rationale,
                    edited_recommendation=(
                        InvestigationRecommendation.model_validate(review.edited_payload)
                        if review.edited_payload
                        else None
                    ),
                    reviewed_at=review.reviewed_at,
                )
                for review in review_rows
            ],
        )

    async def get_alert(self, alert_id: str) -> SyntheticAlert:
        async with self.database.session() as session:
            record = (
                await session.execute(select(AlertRecord).where(AlertRecord.alert_ref == alert_id))
            ).scalar_one()
            customer_ref = (
                await session.execute(
                    select(CustomerRecord.customer_ref).where(
                        CustomerRecord.id == record.customer_id
                    )
                )
            ).scalar_one()
        return SyntheticAlert(
            alert_id=record.alert_ref,
            customer_id=customer_ref,
            rule_id=record.rule_id,
            rule_version=record.rule_version,
            causal_transaction_ids=record.causal_transaction_refs,
            calculation_trace=record.calculation_trace,
            created_at=record.created_at,
        )

    async def get_customer(self, customer_id: str) -> SyntheticCustomer:
        async with self.database.session() as session:
            record = (
                await session.execute(
                    select(CustomerRecord).where(CustomerRecord.customer_ref == customer_id)
                )
            ).scalar_one()
        return SyntheticCustomer(
            customer_id=record.customer_ref,
            customer_type=record.customer_type,
            display_token=record.display_token,
            country_code=record.country_code,
            occupation_or_sector=record.occupation_or_sector,
            expected_monthly_turnover=record.expected_monthly_turnover,
            risk_level=record.risk_level,
        )

    async def get_kyc(self, customer_id: str) -> SyntheticKYC:
        async with self.database.session() as session:
            record = (
                await session.execute(
                    select(KYCRecord)
                    .join(CustomerRecord, CustomerRecord.id == KYCRecord.customer_id)
                    .where(CustomerRecord.customer_ref == customer_id)
                    .order_by(KYCRecord.reviewed_at.desc())
                    .limit(1)
                )
            ).scalar_one()
        return SyntheticKYC(
            kyc_id=record.kyc_ref,
            customer_id=customer_id,
            reviewed_at=record.reviewed_at,
            purpose=record.purpose,
            expected_activity=record.expected_activity,
            status=record.status,
        )

    async def get_transactions(self, customer_id: str) -> list[SyntheticTransaction]:
        async with self.database.session() as session:
            records = (
                await session.execute(
                    select(TransactionRecord)
                    .join(CustomerRecord, CustomerRecord.id == TransactionRecord.customer_id)
                    .where(CustomerRecord.customer_ref == customer_id)
                    .order_by(TransactionRecord.booked_at)
                )
            ).scalars()
            values = list(records)
        return [
            SyntheticTransaction(
                transaction_id=record.transaction_ref,
                account_id=str(record.account_id),
                customer_id=customer_id,
                counterparty_id=str(record.counterparty_id) if record.counterparty_id else None,
                booked_at=record.booked_at,
                amount=record.amount,
                currency=record.currency,
                direction=record.direction,
                description=record.description,
                injected_scenario_id=record.injected_scenario_id,
            )
            for record in values
        ]

    async def save_recommendation(
        self, case_id: UUID, recommendation: InvestigationRecommendation
    ) -> int:
        payload = recommendation.model_dump(mode="json")
        async with self.database.session() as session:
            latest = (
                await session.execute(
                    select(RecommendationRecord.version)
                    .where(RecommendationRecord.case_id == case_id)
                    .order_by(RecommendationRecord.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            version = (latest or 0) + 1
            content_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            session.add(
                RecommendationRecord(
                    case_id=case_id,
                    version=version,
                    author_type="model",
                    payload=payload,
                    content_hash=content_hash,
                )
            )
        return version

    async def save_review(self, review: HumanReview) -> None:
        async with self.database.session() as session:
            session.add(
                HumanReviewRecord(
                    id=review.review_id,
                    case_id=review.case_id,
                    recommendation_version=review.recommendation_version,
                    action=review.action.value,
                    reviewer_id=review.reviewer_id,
                    rationale=review.rationale,
                    edited_payload=(
                        review.edited_recommendation.model_dump(mode="json")
                        if review.edited_recommendation
                        else None
                    ),
                    reviewed_at=review.reviewed_at,
                )
            )

    async def assign_reviewer(self, case_id: UUID, reviewer_id: str) -> None:
        async with self.database.session() as session:
            record = (
                await session.execute(
                    select(CaseRecord).where(CaseRecord.id == case_id).with_for_update()
                )
            ).scalar_one()
            if record.assigned_reviewer_id not in (None, reviewer_id):
                raise ValueError("case review is already assigned")
            record.assigned_reviewer_id = reviewer_id
            record.updated_at = datetime.now(UTC)

    async def set_status(self, case_id: UUID, status: CaseStatus) -> None:
        async with self.database.session() as session:
            record = (
                await session.execute(
                    select(CaseRecord).where(CaseRecord.id == case_id).with_for_update()
                )
            ).scalar_one()
            record.status = status.value
            record.updated_at = datetime.now(UTC)

    async def audit(
        self, event_type: str, actor_id: str, case_id: UUID, payload: dict[str, object]
    ) -> None:
        async with self.database.session() as session:
            previous = (
                await session.execute(
                    select(AuditEventRecord)
                    .order_by(AuditEventRecord.sequence.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            sequence = (previous.sequence if previous else 0) + 1
            previous_hash = previous.event_hash if previous else GENESIS_HASH
            event_hash = calculate_event_hash(
                sequence=sequence,
                event_type=event_type,
                actor_id=actor_id,
                case_id=str(case_id),
                payload=payload,
                previous_hash=previous_hash,
            )
            session.add(
                AuditEventRecord(
                    event_type=event_type,
                    actor_id=actor_id,
                    case_id=case_id,
                    purpose="aml_investigation",
                    payload=payload,
                    sequence=sequence,
                    previous_hash=previous_hash,
                    event_hash=event_hash,
                )
            )

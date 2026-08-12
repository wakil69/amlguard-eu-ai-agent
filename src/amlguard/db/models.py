from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from amlguard.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class CustomerRecord(Base):
    __tablename__ = "customers"
    __table_args__ = {"schema": "bank"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    customer_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_type: Mapped[str] = mapped_column(String(20))
    display_token: Mapped[str] = mapped_column(String(80))
    country_code: Mapped[str] = mapped_column(String(2), default="FR")
    occupation_or_sector: Mapped[str] = mapped_column(String(120))
    expected_monthly_turnover: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    risk_level: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountRecord(Base):
    __tablename__ = "accounts"
    __table_args__ = {"schema": "bank"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("bank.customers.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    opened_at: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")


class KYCRecord(Base):
    __tablename__ = "kyc_records"
    __table_args__ = {"schema": "bank"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    kyc_ref: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("bank.customers.id"), index=True)
    valid_from: Mapped[date] = mapped_column(Date)
    reviewed_at: Mapped[date] = mapped_column(Date)
    purpose: Mapped[str] = mapped_column(Text)
    expected_activity: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(20))


class CounterpartyRecord(Base):
    __tablename__ = "counterparties"
    __table_args__ = {"schema": "bank"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    counterparty_ref: Mapped[str] = mapped_column(String(40), unique=True)
    display_token: Mapped[str] = mapped_column(String(80))
    country_code: Mapped[str] = mapped_column(String(2))
    entity_type: Mapped[str] = mapped_column(String(40))


class TransactionRecord(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        Index("ix_transactions_customer_booked", "customer_id", "booked_at"),
        {"schema": "bank"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    transaction_ref: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("bank.accounts.id"), index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("bank.customers.id"), index=True)
    counterparty_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bank.counterparties.id"), nullable=True
    )
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    direction: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text)
    injected_scenario_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)


class AlertRecord(Base):
    __tablename__ = "alerts"
    __table_args__ = {"schema": "casework"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    alert_ref: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("bank.customers.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[str] = mapped_column(String(20))
    causal_transaction_refs: Mapped[list[str]] = mapped_column(JSON_TYPE)
    calculation_trace: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseRecord(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "alert_id", name="uq_cases_tenant_alert"),
        {"schema": "casework"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_ref: Mapped[str] = mapped_column(String(50), unique=True)
    alert_id: Mapped[UUID] = mapped_column(ForeignKey("casework.alerts.id"))
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("bank.customers.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(120), index=True)
    assigned_investigator_id: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40))
    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthorizedResourceRecord(Base):
    __tablename__ = "authorized_resources"
    __table_args__ = (
        UniqueConstraint("case_id", "resource_type", "resource_ref"),
        {"schema": "casework"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("casework.cases.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_ref: Mapped[str] = mapped_column(String(80))
    authorization_reason: Mapped[str] = mapped_column(Text)


class RecommendationRecord(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("case_id", "version"),
        {"schema": "casework"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("casework.cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    author_type: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HumanReviewRecord(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        UniqueConstraint("case_id", "recommendation_version"),
        {"schema": "casework"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("casework.cases.id"), index=True)
    recommendation_version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    reviewer_id: Mapped[str] = mapped_column(String(120))
    rationale: Mapped[str] = mapped_column(Text)
    edited_payload: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEventRecord(Base):
    __tablename__ = "events"
    __table_args__ = {"schema": "audit"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    actor_id: Mapped[str] = mapped_column(String(120))
    case_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    sequence: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRecord(Base):
    __tablename__ = "manifests"
    __table_args__ = {"schema": "experiment"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(30), default="CREATED")
    cost_ceiling_eur: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    cost_spent_eur: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    cost_reserved_eur: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentJobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("session_key"),
        Index("ix_experiment_jobs_claim", "status", "not_before", "lease_expires_at"),
        {"schema": "experiment"},
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiment.manifests.id"), index=True)
    session_key: Mapped[str] = mapped_column(String(160))
    configuration_id: Mapped[str] = mapped_column(String(80))
    scenario_id: Mapped[str] = mapped_column(String(80))
    repetition: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    estimated_cost_eur: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    reserved_cost_eur: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    actual_cost_eur: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    provider_error: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)


class ExperimentSessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "experiment"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("experiment.jobs.id"), unique=True)
    session_key: Mapped[str] = mapped_column(String(160), unique=True)
    run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    result: Mapped[dict[str, object]] = mapped_column(JSON_TYPE)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RestrictedArtifactRecord(Base):
    __tablename__ = "restricted_artifacts"
    __table_args__ = {"schema": "experiment"}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    artifact_type: Mapped[str] = mapped_column(String(60))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    relative_path: Mapped[str] = mapped_column(String(500))
    encryption_algorithm: Mapped[str] = mapped_column(String(40))
    wrapped_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

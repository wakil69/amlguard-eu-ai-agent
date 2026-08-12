from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SyntheticModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyntheticCustomer(SyntheticModel):
    customer_id: str
    customer_type: str
    display_token: str
    country_code: str = "FR"
    occupation_or_sector: str
    expected_monthly_turnover: Decimal
    risk_level: str


class SyntheticAccount(SyntheticModel):
    account_id: str
    customer_id: str
    currency: str
    opened_at: date
    status: str = "active"


class SyntheticKYC(SyntheticModel):
    kyc_id: str
    customer_id: str
    reviewed_at: date
    purpose: str
    expected_activity: dict[str, object]
    status: str = "current"


class SyntheticCounterparty(SyntheticModel):
    counterparty_id: str
    display_token: str
    country_code: str
    entity_type: str


class SyntheticTransaction(SyntheticModel):
    transaction_id: str
    account_id: str
    customer_id: str
    counterparty_id: str | None
    booked_at: datetime
    amount: Decimal = Field(gt=0)
    currency: str = "EUR"
    direction: str
    description: str
    injected_scenario_id: str | None = None


class SyntheticAlert(SyntheticModel):
    alert_id: str
    customer_id: str
    rule_id: str
    rule_version: str = "1.0"
    causal_transaction_ids: list[str]
    calculation_trace: dict[str, object]
    created_at: datetime


class SyntheticBank(SyntheticModel):
    dataset_version: str = "1.0"
    seed: int
    customers: list[SyntheticCustomer]
    accounts: list[SyntheticAccount]
    kyc_records: list[SyntheticKYC]
    counterparties: list[SyntheticCounterparty]
    transactions: list[SyntheticTransaction]
    alerts: list[SyntheticAlert] = Field(default_factory=list)

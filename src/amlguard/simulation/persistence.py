from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert

from amlguard.db.models import (
    AccountRecord,
    AlertRecord,
    CounterpartyRecord,
    CustomerRecord,
    KYCRecord,
    TransactionRecord,
)
from amlguard.db.session import Database
from amlguard.simulation.models import SyntheticBank

MAX_POSTGRESQL_BIND_PARAMETERS = 32_767
TRANSACTION_PARAMETER_COUNT = 11
TRANSACTION_BATCH_SIZE = 1_000


def stable_uuid(external_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://amlguard.invalid/synthetic/{external_id}")


async def persist_bank(database: Database, bank: SyntheticBank) -> None:
    async with database.session() as session:
        await session.execute(
            insert(CustomerRecord)
            .values(
                [
                    {
                        "id": stable_uuid(item.customer_id),
                        "customer_ref": item.customer_id,
                        "customer_type": item.customer_type,
                        "display_token": item.display_token,
                        "country_code": item.country_code,
                        "occupation_or_sector": item.occupation_or_sector,
                        "expected_monthly_turnover": item.expected_monthly_turnover,
                        "risk_level": item.risk_level,
                    }
                    for item in bank.customers
                ]
            )
            .on_conflict_do_nothing(index_elements=["customer_ref"])
        )
        await session.execute(
            insert(AccountRecord)
            .values(
                [
                    {
                        "id": stable_uuid(item.account_id),
                        "account_ref": item.account_id,
                        "customer_id": stable_uuid(item.customer_id),
                        "currency": item.currency,
                        "opened_at": item.opened_at,
                        "status": item.status,
                    }
                    for item in bank.accounts
                ]
            )
            .on_conflict_do_nothing(index_elements=["account_ref"])
        )
        await session.execute(
            insert(KYCRecord)
            .values(
                [
                    {
                        "id": stable_uuid(item.kyc_id),
                        "kyc_ref": item.kyc_id,
                        "customer_id": stable_uuid(item.customer_id),
                        "valid_from": item.reviewed_at,
                        "reviewed_at": item.reviewed_at,
                        "purpose": item.purpose,
                        "expected_activity": item.expected_activity,
                        "status": item.status,
                    }
                    for item in bank.kyc_records
                ]
            )
            .on_conflict_do_nothing(index_elements=["kyc_ref"])
        )
        await session.execute(
            insert(CounterpartyRecord)
            .values(
                [
                    {
                        "id": stable_uuid(item.counterparty_id),
                        "counterparty_ref": item.counterparty_id,
                        "display_token": item.display_token,
                        "country_code": item.country_code,
                        "entity_type": item.entity_type,
                    }
                    for item in bank.counterparties
                ]
            )
            .on_conflict_do_nothing(index_elements=["counterparty_ref"])
        )
        # A multi-row VALUES insert binds every column for every row. Keep the
        # batch safely below asyncpg/PostgreSQL's 32,767 bind-parameter limit.
        for start in range(0, len(bank.transactions), TRANSACTION_BATCH_SIZE):
            batch = bank.transactions[start : start + TRANSACTION_BATCH_SIZE]
            await session.execute(
                insert(TransactionRecord)
                .values(
                    [
                        {
                            "id": stable_uuid(item.transaction_id),
                            "transaction_ref": item.transaction_id,
                            "account_id": stable_uuid(item.account_id),
                            "customer_id": stable_uuid(item.customer_id),
                            "counterparty_id": (
                                stable_uuid(item.counterparty_id) if item.counterparty_id else None
                            ),
                            "booked_at": item.booked_at,
                            "amount": item.amount,
                            "currency": item.currency,
                            "direction": item.direction,
                            "description": item.description,
                            "injected_scenario_id": item.injected_scenario_id,
                        }
                        for item in batch
                    ]
                )
                .on_conflict_do_nothing(index_elements=["transaction_ref"])
            )
        if bank.alerts:
            await session.execute(
                insert(AlertRecord)
                .values(
                    [
                        {
                            "id": stable_uuid(item.alert_id),
                            "alert_ref": item.alert_id,
                            "customer_id": stable_uuid(item.customer_id),
                            "rule_id": item.rule_id,
                            "rule_version": item.rule_version,
                            "causal_transaction_refs": item.causal_transaction_ids,
                            "calculation_trace": item.calculation_trace,
                            "created_at": item.created_at,
                        }
                        for item in bank.alerts
                    ]
                )
                .on_conflict_do_nothing(index_elements=["alert_ref"])
            )

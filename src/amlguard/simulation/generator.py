from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from faker import Faker

from amlguard.simulation.models import (
    SyntheticAccount,
    SyntheticBank,
    SyntheticCounterparty,
    SyntheticCustomer,
    SyntheticKYC,
    SyntheticTransaction,
)

SECTORS = ("retail", "consulting", "hospitality", "construction", "technology")
OCCUPATIONS = ("engineer", "teacher", "consultant", "trader", "retired")
COUNTRIES = ("FR", "DE", "ES", "IT", "BE", "NL", "PT")


class SyntheticBankGenerator:
    """Deterministic ordinary-activity generator with stable external identifiers."""

    def generate(
        self,
        *,
        seed: int,
        customer_count: int = 1_000,
        transaction_count: int = 50_000,
    ) -> SyntheticBank:
        if customer_count < 1 or transaction_count < customer_count:
            raise ValueError("transaction_count must be at least customer_count")
        rng = random.Random(seed)
        faker = Faker("fr_FR")
        Faker.seed(seed)
        base_date = datetime(2026, 1, 1, tzinfo=UTC)

        customers: list[SyntheticCustomer] = []
        accounts: list[SyntheticAccount] = []
        kyc_records: list[SyntheticKYC] = []
        counterparties: list[SyntheticCounterparty] = []

        for index in range(customer_count):
            customer_id = f"CUS-{index + 1:06d}"
            is_business = index % 4 == 0
            turnover = Decimal(str(rng.randrange(2_000, 80_000 if is_business else 12_000)))
            customers.append(
                SyntheticCustomer(
                    customer_id=customer_id,
                    customer_type="business" if is_business else "individual",
                    display_token=f"SYN-{faker.unique.lexify(text='????????').upper()}",
                    occupation_or_sector=rng.choice(SECTORS if is_business else OCCUPATIONS),
                    expected_monthly_turnover=turnover,
                    risk_level=rng.choices(["low", "medium", "high"], [75, 22, 3])[0],
                )
            )
            account_total = 2 if index % 3 == 0 else 1
            for account_index in range(account_total):
                accounts.append(
                    SyntheticAccount(
                        account_id=f"ACC-{index + 1:06d}-{account_index + 1}",
                        customer_id=customer_id,
                        currency="EUR",
                        opened_at=date(2018 + index % 7, 1 + index % 12, 1 + index % 25),
                    )
                )
            reviewed_at = date(2025, 1 + index % 12, 1 + index % 25)
            kyc_records.append(
                SyntheticKYC(
                    kyc_id=f"KYC-{index + 1:06d}",
                    customer_id=customer_id,
                    reviewed_at=reviewed_at,
                    purpose="ordinary commercial activity" if is_business else "personal banking",
                    expected_activity={
                        "monthly_turnover": str(turnover),
                        "international": index % 5 == 0,
                    },
                )
            )

        for index in range(max(200, customer_count // 2)):
            counterparties.append(
                SyntheticCounterparty(
                    counterparty_id=f"CP-{index + 1:06d}",
                    display_token=f"SYN-CP-{index + 1:06d}",
                    country_code=rng.choice(COUNTRIES),
                    entity_type="business" if index % 3 else "individual",
                )
            )

        accounts_by_customer: dict[str, list[SyntheticAccount]] = {}
        for account in accounts:
            accounts_by_customer.setdefault(account.customer_id, []).append(account)

        transactions: list[SyntheticTransaction] = []
        for index in range(transaction_count):
            customer = customers[index % customer_count]
            account = rng.choice(accounts_by_customer[customer.customer_id])
            amount_ceiling = max(50, int(customer.expected_monthly_turnover / Decimal("4")))
            amount = Decimal(rng.randrange(10, amount_ceiling * 100)) / Decimal("100")
            transactions.append(
                SyntheticTransaction(
                    transaction_id=f"TX-BG-{index + 1:08d}",
                    account_id=account.account_id,
                    customer_id=customer.customer_id,
                    counterparty_id=rng.choice(counterparties).counterparty_id,
                    booked_at=base_date + timedelta(minutes=index * 5),
                    amount=amount,
                    direction="credit" if rng.random() < 0.48 else "debit",
                    description=rng.choice(
                        ("invoice", "card settlement", "rent", "salary", "transfer")
                    ),
                )
            )

        return SyntheticBank(
            seed=seed,
            customers=customers,
            accounts=accounts,
            kyc_records=kyc_records,
            counterparties=counterparties,
            transactions=transactions,
        )

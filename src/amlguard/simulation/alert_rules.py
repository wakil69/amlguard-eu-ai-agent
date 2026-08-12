from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from amlguard.simulation.models import SyntheticAlert, SyntheticTransaction


def expected_activity_variance(
    customer_id: str, transactions: list[SyntheticTransaction]
) -> SyntheticAlert | None:
    """Low-severity deterministic review alert used by benign controls."""
    relevant = sorted(
        (item for item in transactions if item.customer_id == customer_id),
        key=lambda item: item.booked_at,
    )
    if not relevant:
        return None
    latest = relevant[-1]
    return SyntheticAlert(
        alert_id=f"ALT-EAV-{customer_id}",
        customer_id=customer_id,
        rule_id="EXPECTED_ACTIVITY_VARIANCE",
        causal_transaction_ids=[latest.transaction_id],
        calculation_trace={"review_reason": "sampled benign variance", "severity": "low"},
        created_at=latest.booked_at + timedelta(seconds=1),
    )


def rapid_funds_movement(
    customer_id: str, transactions: list[SyntheticTransaction]
) -> SyntheticAlert | None:
    ordered = sorted(
        (item for item in transactions if item.customer_id == customer_id),
        key=lambda item: item.booked_at,
    )
    for incoming in ordered:
        if incoming.direction != "credit" or incoming.amount < Decimal("5000"):
            continue
        deadline = incoming.booked_at + timedelta(days=3)
        outgoing = [
            item
            for item in ordered
            if item.direction == "debit" and incoming.booked_at <= item.booked_at <= deadline
        ]
        total_out = sum((item.amount for item in outgoing), Decimal("0"))
        if total_out >= incoming.amount * Decimal("0.80"):
            causal = [incoming.transaction_id, *(item.transaction_id for item in outgoing)]
            return SyntheticAlert(
                alert_id=f"ALT-RFM-{customer_id}",
                customer_id=customer_id,
                rule_id="RAPID_FUNDS_MOVEMENT",
                causal_transaction_ids=causal,
                calculation_trace={
                    "incoming": str(incoming.amount),
                    "outgoing_within_3d": str(total_out),
                    "ratio": str(total_out / incoming.amount),
                },
                created_at=max(item.booked_at for item in [incoming, *outgoing])
                + timedelta(seconds=1),
            )
    return None


def structuring_like(
    customer_id: str, transactions: list[SyntheticTransaction]
) -> SyntheticAlert | None:
    credits = sorted(
        (
            item
            for item in transactions
            if item.customer_id == customer_id
            and item.direction == "credit"
            and Decimal("1000") <= item.amount < Decimal("10000")
        ),
        key=lambda item: item.booked_at,
    )
    for start_index, first in enumerate(credits):
        window = [
            item
            for item in credits[start_index:]
            if first.booked_at <= item.booked_at <= first.booked_at + timedelta(days=7)
        ]
        if len(window) >= 5 and sum((item.amount for item in window), Decimal("0")) >= Decimal(
            "20000"
        ):
            return SyntheticAlert(
                alert_id=f"ALT-STR-{customer_id}",
                customer_id=customer_id,
                rule_id="STRUCTURING_LIKE_REPEATED_CREDITS",
                causal_transaction_ids=[item.transaction_id for item in window],
                calculation_trace={"count": len(window), "window_days": 7},
                created_at=max(item.booked_at for item in window) + timedelta(seconds=1),
            )
    return None


RULES = {
    "EXPECTED_ACTIVITY_VARIANCE": expected_activity_variance,
    "RAPID_FUNDS_MOVEMENT": rapid_funds_movement,
    "STRUCTURING_LIKE_REPEATED_CREDITS": structuring_like,
}

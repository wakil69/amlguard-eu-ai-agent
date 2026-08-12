from __future__ import annotations

from decimal import Decimal, InvalidOperation

from amlguard.domain.models import EvidenceItem
from amlguard.policy.models import PolicyApplicabilityFact

POLICY_FACT_IDS = frozenset(
    {
        "activity_variance_pattern",
        "beneficial_owner_data_unavailable",
        "business_customer",
        "causal_amount_exceeds_expected_monthly_turnover",
        "counterparty_geography_unavailable",
        "high_risk_customer",
        "kyc_missing",
        "kyc_not_current",
        "pep_status_unavailable",
        "potential_enhanced_examination_pattern",
        "rapid_funds_movement_pattern",
        "relationship_purpose_unavailable",
        "repeated_credit_pattern",
        "sanctions_screening_status_unavailable",
    }
)


def derive_policy_applicability_facts(
    evidence: list[EvidenceItem],
) -> list[PolicyApplicabilityFact]:
    """Derive bounded research facts used for conditional policy retrieval.

    These facts describe available evidence. They are not legal conclusions.
    """
    alert = next(item for item in evidence if item.evidence_type == "alert")
    customer = next(item for item in evidence if item.evidence_type == "customer_profile")
    kyc = next((item for item in evidence if item.evidence_type == "kyc_profile"), None)
    transactions = [item for item in evidence if item.evidence_type == "transaction"]
    supplemental = [
        item for item in evidence if item.evidence_type == "supplemental_information"
    ]
    supplemental_information: dict[str, object] = {}
    for item in supplemental:
        value = item.content.get("information", {})
        if isinstance(value, dict):
            supplemental_information.update(value)
    supplemental_ids = [item.evidence_id for item in supplemental]
    facts: dict[str, PolicyApplicabilityFact] = {}

    def add(fact_id: str, explanation: str, evidence_ids: list[str]) -> None:
        facts[fact_id] = PolicyApplicabilityFact(
            fact_id=fact_id,
            explanation=explanation,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
        )

    rule_id = str(alert.content.get("rule_id", ""))
    causal_ids = {
        str(item) for item in alert.content.get("causal_transaction_ids", [])
    }
    causal_transactions = [item for item in transactions if item.evidence_id in causal_ids]
    causal_evidence_ids = [alert.evidence_id, *(item.evidence_id for item in causal_transactions)]

    if rule_id == "EXPECTED_ACTIVITY_VARIANCE":
        add(
            "activity_variance_pattern",
            "The monitoring engine recorded an expected-activity variance.",
            causal_evidence_ids,
        )
    elif rule_id == "RAPID_FUNDS_MOVEMENT":
        add(
            "rapid_funds_movement_pattern",
            "The monitoring engine recorded incoming funds followed by rapid outgoing movement.",
            causal_evidence_ids,
        )
        add(
            "potential_enhanced_examination_pattern",
            "The rapid movement is an atypical pattern requiring assessment "
            "against the legal enhanced-examination criteria.",
            causal_evidence_ids,
        )
    elif rule_id == "STRUCTURING_LIKE_REPEATED_CREDITS":
        add(
            "repeated_credit_pattern",
            "The monitoring engine recorded repeated credits within a short window.",
            causal_evidence_ids,
        )
        add(
            "potential_enhanced_examination_pattern",
            "The repeated-credit pattern requires assessment against the legal "
            "enhanced-examination criteria.",
            causal_evidence_ids,
        )

    risk_level = str(customer.content.get("risk_level", "")).lower()
    if risk_level == "high":
        add(
            "high_risk_customer",
            "The customer profile is classified as high risk.",
            [customer.evidence_id],
        )
    if str(customer.content.get("customer_type", "")).lower() == "business":
        add(
            "business_customer",
            "The customer profile identifies a business customer.",
            [customer.evidence_id],
        )
        if (
            kyc is None or "beneficial_owner" not in kyc.content
        ) and "beneficial_owner" not in supplemental_information:
            add(
                "beneficial_owner_data_unavailable",
                "The retrieved KYC evidence does not contain beneficial-owner information.",
                [
                    customer.evidence_id,
                    *([kyc.evidence_id] if kyc else []),
                    *supplemental_ids,
                ],
            )

    if kyc is None or str(kyc.content.get("status", "")).lower() == "missing":
        add(
            "kyc_missing",
            "No usable KYC profile is available in the retrieved evidence.",
            [customer.evidence_id, *([kyc.evidence_id] if kyc else [])],
        )
    elif str(kyc.content.get("status", "")).lower() != "current":
        add(
            "kyc_not_current",
            "The retrieved KYC profile is not marked current.",
            [kyc.evidence_id],
        )
    if (
        kyc is None or not str(kyc.content.get("purpose", "")).strip()
    ) and not str(supplemental_information.get("purpose", "")).strip():
        add(
            "relationship_purpose_unavailable",
            "The purpose of the business relationship is absent from retrieved KYC evidence.",
            [
                customer.evidence_id,
                *([kyc.evidence_id] if kyc else []),
                *supplemental_ids,
            ],
        )

    if (
        "pep_status" not in customer.content
        and "pep_status" not in supplemental_information
    ):
        add(
            "pep_status_unavailable",
            "The retrieved customer profile does not contain a PEP assessment.",
            [customer.evidence_id],
        )
    if (
        "sanctions_screening_status" not in customer.content
        and "sanctions_screening_status" not in supplemental_information
    ):
        add(
            "sanctions_screening_status_unavailable",
            "The retrieved customer profile does not contain a sanctions-screening result.",
            [customer.evidence_id],
        )

    try:
        expected_turnover = Decimal(str(customer.content.get("expected_monthly_turnover", "0")))
    except InvalidOperation:
        expected_turnover = Decimal("0")
    if expected_turnover > 0 and any(
        Decimal(str(item.content.get("amount", "0"))) > expected_turnover
        for item in causal_transactions
    ):
        add(
            "causal_amount_exceeds_expected_monthly_turnover",
            "At least one causal transaction exceeds the recorded expected monthly turnover.",
            [customer.evidence_id, *causal_evidence_ids],
        )

    if (
        "counterparty_country_code"
        not in {key for item in causal_transactions for key in item.content}
        and "counterparty_country_code" not in supplemental_information
    ):
        add(
            "counterparty_geography_unavailable",
            "The causal transaction evidence does not include counterparty geography.",
            causal_evidence_ids,
        )

    return sorted(facts.values(), key=lambda item: item.fact_id)

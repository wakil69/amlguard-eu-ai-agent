from uuid import uuid4

from amlguard.domain.enums import RecommendationKind
from amlguard.domain.models import EvidenceItem, InvestigationRecommendation, MaterialFinding
from amlguard.evidence.ledger import EvidenceLedger


def test_fabricated_evidence_is_detected() -> None:
    case_id = uuid4()
    ledger = EvidenceLedger(
        [
            EvidenceItem(
                evidence_id="TX-REAL",
                evidence_type="transaction",
                source_record_id="TX-REAL",
                case_id=case_id,
                customer_id="CUS-1",
                content={"amount": "10.00"},
                content_hash="a" * 64,
                provenance="test",
            )
        ]
    )
    recommendation = InvestigationRecommendation(
        recommendation=RecommendationKind.ESCALATE_TO_HUMAN_AML_ANALYST,
        summary="Synthetic test",
        material_findings=[
            MaterialFinding(
                claim="A material assertion",
                evidence_ids=["TX-FABRICATED"],
                assessment="supports_concern",
                claim_type="fact",
            )
        ],
    )
    assert ledger.validate_recommendation(recommendation) == ["TX-FABRICATED"]

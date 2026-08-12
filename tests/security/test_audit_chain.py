from uuid import uuid4

import pytest

from amlguard.governance.audit_chain import ChainedAuditEvent, verify_chain
from amlguard.simulation.generator import SyntheticBankGenerator
from amlguard.tools.repository import InMemoryInvestigationRepository


@pytest.mark.asyncio
async def test_audit_chain_detects_tampering() -> None:
    repository = InMemoryInvestigationRepository(
        SyntheticBankGenerator().generate(seed=1, customer_count=2, transaction_count=2)
    )
    case_id = uuid4()
    await repository.audit("first", "actor", case_id, {"value": 1})
    await repository.audit("second", "actor", case_id, {"value": 2})
    events = [
        ChainedAuditEvent(**{**event, "case_id": str(event["case_id"])})
        for event in repository.audit_events
    ]
    assert verify_chain(events) == []
    altered = events.copy()
    altered[1] = ChainedAuditEvent(**{**altered[1].__dict__, "payload": {"value": 999}})
    assert verify_chain(altered) == [2]

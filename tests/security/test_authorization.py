from uuid import uuid4

import pytest

from amlguard.tools.authorization import CaseAuthorization
from amlguard.tools.repository import InMemoryInvestigationRepository
from amlguard.tools.service import InvestigationTools, ToolAuthorizationError


@pytest.mark.asyncio
async def test_cross_customer_access_is_denied_before_retrieval(injected_bank) -> None:  # type: ignore[no-untyped-def]
    repository = InMemoryInvestigationRepository(injected_bank)
    tools = InvestigationTools(repository)
    auth = CaseAuthorization(uuid4(), "CUS-000001", "analyst")
    with pytest.raises(ToolAuthorizationError):
        await tools.get_customer_profile(auth, "CUS-000002")
    assert tools.executions[-1].authorized is False
    assert tools.executions[-1].error_code == "CROSS_SCOPE_ACCESS"
    assert repository.audit_events[-1]["event_type"] == "tool_authorization_denied"


@pytest.mark.asyncio
async def test_prohibited_tools_are_denial_traps(injected_bank) -> None:  # type: ignore[no-untyped-def]
    repository = InMemoryInvestigationRepository(injected_bank)
    tools = InvestigationTools(repository)
    auth = CaseAuthorization(uuid4(), "CUS-000001", "analyst")
    with pytest.raises(ToolAuthorizationError):
        await tools.invoke_prohibited(auth, "submit_str", {"case": "synthetic"})
    assert tools.executions[-1].error_code == "PROHIBITED_ACTION"

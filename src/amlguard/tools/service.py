from __future__ import annotations

import time

from amlguard.domain.models import EvidenceItem, ToolExecution
from amlguard.evidence.ledger import evidence_from_model
from amlguard.monitoring.telemetry import log_event, record_tool_denial, stage_span
from amlguard.tools.authorization import AuthorizationDenied, CaseAuthorization
from amlguard.tools.repository import InvestigationRepository


class ToolAuthorizationError(PermissionError):
    pass


class InvestigationTools:
    """Typed, case-scoped tools. Authorization occurs before repository access."""

    PROHIBITED = {
        "submit_str",
        "freeze_account",
        "block_transaction",
        "contact_customer",
        "update_kyc",
    }

    def __init__(self, repository: InvestigationRepository) -> None:
        self.repository = repository
        self.executions: list[ToolExecution] = []

    async def get_alert(self, auth: CaseAuthorization, alert_id: str) -> EvidenceItem:
        started = time.perf_counter()
        with stage_span("tool.get_alert"):
            alert = await self.repository.get_alert(alert_id)
            await self._authorize(auth, alert.customer_id, "get_alert", started)
        evidence = evidence_from_model(
            evidence_id=f"ALERT-{alert.alert_id}",
            evidence_type="alert",
            source_record_id=alert.alert_id,
            case_id=auth.case_id,
            customer_id=auth.customer_id,
            value=alert,
            provenance="deterministic_monitoring_engine",
        )
        await self._record(auth, "get_alert", {"alert_id": alert_id}, [evidence], started)
        return evidence

    async def get_customer_profile(self, auth: CaseAuthorization, customer_id: str) -> EvidenceItem:
        started = time.perf_counter()
        await self._authorize(auth, customer_id, "get_customer_profile", started)
        customer = await self.repository.get_customer(customer_id)
        allowed = {
            "customer_id": customer.customer_id,
            "customer_type": customer.customer_type,
            "display_token": customer.display_token,
            "country_code": customer.country_code,
            "occupation_or_sector": customer.occupation_or_sector,
            "expected_monthly_turnover": str(customer.expected_monthly_turnover),
            "risk_level": customer.risk_level,
        }
        evidence = evidence_from_model(
            evidence_id=f"CUSTOMER-{customer_id}",
            evidence_type="customer_profile",
            source_record_id=customer_id,
            case_id=auth.case_id,
            customer_id=customer_id,
            value=allowed,
            provenance="synthetic_bank.customer_profile",
        )
        await self._record(
            auth, "get_customer_profile", {"customer_id": customer_id}, [evidence], started
        )
        return evidence

    async def get_kyc_profile(self, auth: CaseAuthorization, customer_id: str) -> EvidenceItem:
        started = time.perf_counter()
        await self._authorize(auth, customer_id, "get_kyc_profile", started)
        kyc = await self.repository.get_kyc(customer_id)
        evidence = evidence_from_model(
            evidence_id=f"KYC-{kyc.kyc_id}",
            evidence_type="kyc_profile",
            source_record_id=kyc.kyc_id,
            case_id=auth.case_id,
            customer_id=customer_id,
            value=kyc,
            provenance="synthetic_bank.kyc",
        )
        await self._record(
            auth, "get_kyc_profile", {"customer_id": customer_id}, [evidence], started
        )
        return evidence

    async def get_transactions(
        self, auth: CaseAuthorization, customer_id: str, limit: int = 250
    ) -> list[EvidenceItem]:
        started = time.perf_counter()
        await self._authorize(auth, customer_id, "get_transactions", started)
        if not 1 <= limit <= 500:
            raise ValueError("transaction result limit must be between 1 and 500")
        transactions = (await self.repository.get_transactions(customer_id))[-limit:]
        evidence = [
            evidence_from_model(
                evidence_id=item.transaction_id,
                evidence_type="transaction",
                source_record_id=item.transaction_id,
                case_id=auth.case_id,
                customer_id=customer_id,
                value=item,
                provenance="synthetic_bank.transactions",
            )
            for item in transactions
        ]
        await self._record(
            auth,
            "get_transactions",
            {"customer_id": customer_id, "limit": limit},
            evidence,
            started,
        )
        return evidence

    async def invoke_prohibited(
        self, auth: CaseAuthorization, tool_name: str, arguments: dict[str, object]
    ) -> None:
        if tool_name not in self.PROHIBITED:
            raise KeyError(tool_name)
        execution = ToolExecution(
            case_id=auth.case_id,
            tool_name=tool_name,
            sanitized_arguments=arguments,
            authorized=False,
            error_code="PROHIBITED_ACTION",
            duration_ms=0,
        )
        self.executions.append(execution)
        record_tool_denial(reason="PROHIBITED_ACTION", tool=tool_name)
        log_event("prohibited_tool_denied", level=30, tool_name=tool_name)
        await self.repository.audit(
            "prohibited_tool_denied", auth.actor_id, auth.case_id, execution.model_dump(mode="json")
        )
        raise ToolAuthorizationError(f"{tool_name} is intentionally unavailable")

    async def _authorize(
        self, auth: CaseAuthorization, customer_id: str, tool_name: str, started: float
    ) -> None:
        try:
            auth.require_customer(customer_id)
        except AuthorizationDenied as exc:
            execution = ToolExecution(
                case_id=auth.case_id,
                tool_name=tool_name,
                sanitized_arguments={"customer_id": customer_id},
                authorized=False,
                error_code="CROSS_SCOPE_ACCESS",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            self.executions.append(execution)
            record_tool_denial(reason="CROSS_SCOPE_ACCESS", tool=tool_name)
            log_event("tool_authorization_denied", level=30, tool_name=tool_name)
            await self.repository.audit(
                "tool_authorization_denied",
                auth.actor_id,
                auth.case_id,
                execution.model_dump(mode="json"),
            )
            raise ToolAuthorizationError(str(exc)) from exc

    async def _record(
        self,
        auth: CaseAuthorization,
        tool_name: str,
        arguments: dict[str, object],
        evidence: list[EvidenceItem],
        started: float,
    ) -> None:
        execution = ToolExecution(
            case_id=auth.case_id,
            tool_name=tool_name,
            sanitized_arguments=arguments,
            authorized=True,
            evidence_ids=[item.evidence_id for item in evidence],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self.executions.append(execution)
        await self.repository.audit(
            "tool_access", auth.actor_id, auth.case_id, execution.model_dump(mode="json")
        )

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


class AuthorizationDenied(PermissionError):
    pass


@dataclass(frozen=True)
class CaseAuthorization:
    case_id: UUID
    customer_id: str
    actor_id: str
    purpose: str = "aml_investigation"

    def require_customer(self, requested_customer_id: str) -> None:
        if requested_customer_id != self.customer_id:
            raise AuthorizationDenied(
                f"customer {requested_customer_id} is outside case scope {self.case_id}"
            )

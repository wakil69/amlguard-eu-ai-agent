from __future__ import annotations

from typing import Literal

from amlguard.auth.dependencies import FULL_ACCESS_ROLE, Actor
from amlguard.tools.repository import CaseData

CaseAction = Literal[
    "claim_review",
    "read_case",
    "read_evidence",
    "read_trace",
    "reset",
    "review",
    "supply_information",
]


class CaseAccessDenied(PermissionError):
    pass


def authorize_case(actor: Actor, case: CaseData, action: CaseAction) -> None:
    """Enforce tenant and case assignment after route-level role authorization."""
    if FULL_ACCESS_ROLE in actor.roles:
        return
    if actor.tenant_id != case.tenant_id:
        raise CaseAccessDenied("case belongs to another tenant")

    is_investigator = actor.actor_id == case.assigned_investigator_id
    is_reviewer = actor.actor_id == case.assigned_reviewer_id

    if action == "claim_review":
        if "reviewer" not in actor.roles:
            raise CaseAccessDenied("reviewer role required")
        if is_investigator:
            raise CaseAccessDenied("an investigator cannot claim their own review")
        return
    if action == "review":
        if "reviewer" not in actor.roles or not is_reviewer:
            raise CaseAccessDenied("reviewer is not assigned to this case")
        return
    if action == "read_trace":
        if "researcher" not in actor.roles:
            raise CaseAccessDenied("researcher role required")
        return
    if action in {"read_case", "read_evidence"}:
        if "researcher" in actor.roles or is_investigator or is_reviewer:
            return
        raise CaseAccessDenied("actor is not assigned to this case")
    if action == "supply_information" and (is_investigator or is_reviewer):
        return
    if action == "reset" and is_investigator:
        return
    raise CaseAccessDenied("actor is not authorized for this case action")

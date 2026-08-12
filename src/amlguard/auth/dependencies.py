from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient

from amlguard.config import Settings, get_settings

FULL_ACCESS_ROLE = "administrator"


@dataclass(frozen=True)
class Actor:
    actor_id: str
    roles: frozenset[str]
    tenant_id: str
    display_name: str | None = None


def _claims_to_actor(claims: dict[str, object]) -> Actor:
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    return Actor(
        actor_id=str(claims.get("sub", "unknown")),
        roles=frozenset(str(role) for role in roles),
        tenant_id=str(claims.get("tenant_id", "")).strip(),
        display_name=str(
            claims.get("preferred_username")
            or claims.get("name")
            or claims.get("sub")
            or "unknown"
        ),
    )


def _require_tenant(actor: Actor) -> Actor:
    if not actor.tenant_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "tenant identity claim required")
    return actor


async def get_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Actor:
    session_user = request.session.get("user") if hasattr(request, "session") else None
    if isinstance(session_user, dict):
        return _require_tenant(_claims_to_actor(session_user))
    if settings.dev_auth_bypass:
        return _require_tenant(
            Actor(
                actor_id=request.headers.get("X-Actor-ID", "dev-administrator"),
                roles=frozenset(request.headers.get("X-Roles", FULL_ACCESS_ROLE).split(",")),
                tenant_id=request.headers.get("X-Tenant-ID", "amlguard-development").strip(),
                display_name=request.headers.get("X-Actor-ID", "dev-administrator"),
            )
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        issuer = str(settings.keycloak_issuer).rstrip("/")
        signing_key = PyJWKClient(
            f"{settings.keycloak_backend}/protocol/openid-connect/certs"
        ).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=issuer,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid access token") from exc
    return _require_tenant(_claims_to_actor(claims))


def require_roles(*allowed: str):  # type: ignore[no-untyped-def]
    async def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if FULL_ACCESS_ROLE not in actor.roles and not actor.roles.intersection(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return actor

    return dependency

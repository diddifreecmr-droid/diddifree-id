"""The consumer-side port — what Wallet, Fund, Ride, Shop and the rest actually
integrate against.

This module is written to be **copied into a consuming service**, or packaged
later as a small shared library. It therefore depends on nothing from
`identity_app` — only `httpx` and `pyjwt[crypto]`.

It implements the rule stated in the contract's §0: verification happens
locally, against a cached JWKS, with no network call to DiddiFreeID on the
request path. The only traffic is a periodic key refresh, plus an immediate one
when a token arrives signed by an unknown `kid` — the signal that a rotation
just happened.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
import jwt
from jwt import PyJWK

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
DEFAULT_JWKS_TTL_SECONDS = 3600


class IdentityError(Exception):
    """Base class — a consumer maps these onto its own error envelope."""


class TokenExpired(IdentityError):
    """Consumers answer `401 TOKEN_EXPIRED`; the frontend then calls
    `POST /auth/refresh` itself. A module must never refresh on the user's
    behalf (contract §2)."""


class TokenInvalid(IdentityError):
    """Malformed, wrong signature, or signed by a key we cannot find."""


class UserNotActive(IdentityError):
    """Signature valid, but `status != active` — a suspended account. The
    contract requires refusing the action even though the token verifies."""


@dataclass(frozen=True)
class VerifiedIdentity:
    user_id: UUID
    role: str
    status: str


class IdentityVerifierPort(Protocol):
    """What a module needs from DiddiFreeID on the request path. Deliberately
    one method: anything more would tempt a module into synchronous calls."""

    async def verify(self, access_token: str) -> VerifiedIdentity:
        ...


class JwksIdentityVerifier:
    """Local verifier with a cached JWKS.

    Usage in a consuming service (one instance, shared, on app state)::

        verifier = JwksIdentityVerifier("https://api-dev.diddifree.app/identity/v1")
        identity = await verifier.verify(bearer_token)
    """

    def __init__(
        self,
        base_url: str,
        *,
        issuer: str = "diddifree-id",
        ttl_seconds: int = DEFAULT_JWKS_TTL_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._jwks_url = f"{base_url.rstrip('/')}/.well-known/jwks.json"
        self._issuer = issuer
        self._ttl = ttl_seconds
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _refresh(self) -> None:
        response = await self._client.get(self._jwks_url)
        response.raise_for_status()
        document = response.json()
        self._keys = {jwk["kid"]: PyJWK.from_dict(jwk) for jwk in document.get("keys", [])}
        self._fetched_at = time.monotonic()
        logger.info("JWKS rafraîchi : %s clé(s) — %s", len(self._keys), ", ".join(self._keys))

    async def _key_for(self, kid: str) -> PyJWK:
        stale = (time.monotonic() - self._fetched_at) > self._ttl
        if not self._keys or stale:
            await self._refresh()
        if kid not in self._keys:
            # Unknown kid on a fresh-enough cache means a rotation happened
            # between refreshes. One extra fetch here is what keeps a rotation
            # from logging the whole ecosystem out.
            logger.info("kid inconnu (%s), rafraîchissement immédiat du JWKS", kid)
            await self._refresh()
        try:
            return self._keys[kid]
        except KeyError as exc:
            raise TokenInvalid(f"Aucune clé publique ne correspond au kid {kid!r}.") from exc

    async def verify(self, access_token: str) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(access_token)
        except jwt.InvalidTokenError as exc:
            raise TokenInvalid(str(exc)) from exc

        kid = header.get("kid")
        if not kid:
            raise TokenInvalid("En-tête JWT sans `kid`.")

        key = await self._key_for(kid)

        try:
            claims = jwt.decode(
                access_token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "role"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpired(str(exc)) from exc
        except jwt.InvalidTokenError as exc:
            raise TokenInvalid(str(exc)) from exc

        status = claims.get("status", "active")
        if status != "active":
            raise UserNotActive(f"Compte en statut {status!r}.")

        try:
            user_id = UUID(claims["sub"])
        except (KeyError, ValueError) as exc:
            raise TokenInvalid("Claim `sub` absent ou malformé.") from exc

        return VerifiedIdentity(user_id=user_id, role=claims["role"], status=status)

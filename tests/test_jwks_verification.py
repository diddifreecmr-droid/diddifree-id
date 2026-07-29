"""The load-bearing claim of the whole architecture: a consuming module can
verify a DiddiFreeID token **without calling DiddiFreeID**.

Step 3 of the architecture's "prochaines étapes" asks for exactly this — a stub
consumer verifying a token on its own. `JwksIdentityVerifier` is the code the
modules will import, so testing it here tests what Wallet will actually run.
"""

from __future__ import annotations

import httpx
import pytest

from identity_app.shared_kernel.contracts.identity_provider import (
    JwksIdentityVerifier,
    TokenInvalid,
    UserNotActive,
)
from tests.conftest import API


class CountingTransport(httpx.AsyncBaseTransport):
    """Wraps a transport and counts requests, so a test can assert that
    verification touches the network zero times once the keys are cached."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        return await self._inner.handle_async_request(request)


@pytest.fixture
def consumer_transport():
    """A stand-in for a module's HTTP client, pointed at our ASGI app."""
    from identity_app.main import app

    return CountingTransport(httpx.ASGITransport(app=app))


async def test_jwks_is_served_at_both_documented_paths(client):
    root = await client.get("/.well-known/jwks.json")
    prefixed = await client.get(f"{API}/.well-known/jwks.json")

    assert root.status_code == 200
    assert prefixed.status_code == 200
    assert root.json() == prefixed.json()


async def test_jwks_shape_matches_the_contract(client):
    r = await client.get("/.well-known/jwks.json")

    keys = r.json()["keys"]
    assert len(keys) >= 1
    key = keys[0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"]
    assert key["n"] and key["e"]
    # A private exponent leaking into the published key set would hand anyone
    # the ability to mint tokens. Worth asserting rather than assuming.
    assert not {"d", "p", "q", "dp", "dq", "qi"} & set(key)


async def test_jwks_is_cacheable(client):
    r = await client.get("/.well-known/jwks.json")

    assert "max-age" in r.headers.get("cache-control", "")


async def test_a_module_verifies_a_token_locally(client, user_session, consumer_transport):
    verifier = JwksIdentityVerifier(
        "http://testserver",
        client=httpx.AsyncClient(transport=consumer_transport, base_url="http://testserver"),
    )
    try:
        identity = await verifier.verify(user_session["access_token"])

        assert str(identity.user_id) == user_session["user"]["id"]
        assert identity.role == "user"
        assert identity.status == "active"
        # Exactly one call: fetching the key set. Not one per verification.
        assert consumer_transport.count == 1

        # Every subsequent verification is pure local computation — this is the
        # property that keeps DiddiFreeID from becoming the ecosystem's
        # bottleneck (architecture §1).
        for _ in range(20):
            await verifier.verify(user_session["access_token"])
        assert consumer_transport.count == 1
    finally:
        await verifier.aclose()


async def test_a_module_rejects_a_token_signed_by_another_key(client, consumer_transport):
    """A forged token from a compromised module must not verify — the reason
    RS256 was chosen over a shared HS256 secret."""
    from datetime import UTC, datetime, timedelta

    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rogue_pem = rogue.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "role": "admin",
            "status": "active",
            "iss": "diddifree-id",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        rogue_pem,
        algorithm="RS256",
        # Claims our real kid, so the verifier looks up a key it does have and
        # the signature check is what has to catch this.
        headers={"kid": "dev-2026-07-01"},
    )

    verifier = JwksIdentityVerifier(
        "http://testserver",
        client=httpx.AsyncClient(transport=consumer_transport, base_url="http://testserver"),
    )
    try:
        with pytest.raises(TokenInvalid):
            await verifier.verify(forged)
    finally:
        await verifier.aclose()

    # And our own service refuses it too.
    r = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_a_module_refuses_a_suspended_account(client, user_session, admin_session, consumer_transport):
    """Contract §2: a valid signature is not enough — `status != active` must
    stop the action on the module's side."""
    r = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/status",
        json={"status": "suspended", "reason": "Test"},
        headers=admin_session["headers"],
    )
    assert r.status_code == 200

    # The token issued before the suspension still carries `status: active`,
    # which is the 15-minute window the contract acknowledges. A token minted
    # after it does not — build one and check the consumer refuses it.
    from uuid import UUID

    from identity_app.modules.identity.infra.token_service import TokenService

    stale_free_token = TokenService().issue_access_token(
        user_id=UUID(user_session["user"]["id"]), role="user", status="suspended",
    )

    verifier = JwksIdentityVerifier(
        "http://testserver",
        client=httpx.AsyncClient(transport=consumer_transport, base_url="http://testserver"),
    )
    try:
        with pytest.raises(UserNotActive):
            await verifier.verify(stale_free_token)
    finally:
        await verifier.aclose()


async def test_unknown_kid_triggers_one_refresh_then_fails(client, consumer_transport):
    from datetime import UTC, datetime, timedelta

    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "x", "role": "user", "iat": now, "exp": now + timedelta(minutes=5)},
        rogue.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        algorithm="RS256",
        headers={"kid": "kid-qui-nexiste-pas"},
    )

    verifier = JwksIdentityVerifier(
        "http://testserver",
        client=httpx.AsyncClient(transport=consumer_transport, base_url="http://testserver"),
    )
    try:
        with pytest.raises(TokenInvalid):
            await verifier.verify(token)
        # Two fetches: the initial load, then the rotation-suspicion refresh.
        # Not an unbounded retry — a flood of bogus kids must not turn into a
        # flood of requests against DiddiFreeID.
        assert consumer_transport.count == 2
    finally:
        await verifier.aclose()

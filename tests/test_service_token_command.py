from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from prometheus_client import generate_latest

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.commands.issue_service_token import IssueServiceToken
from identity_app.modules.identity.domain.service_client import ServiceClient


class FakeClients:
    def __init__(self, client: ServiceClient | None) -> None:
        self.client = client

    async def find_by_client_id(self, client_id: str) -> ServiceClient | None:
        return self.client if self.client and self.client.client_id == client_id else None


class FakeTokens:
    def issue_service_token(self, **kwargs: object) -> str:
        self.kwargs = kwargs
        return "signed-service-token"


def make_client(secret_hash: str) -> ServiceClient:
    return ServiceClient(
        id=uuid4(),
        client_id="pilotage-staging",
        service_name="pilotage",
        environment="staging",
        secret_hash=secret_hash,
        allowed_audiences=("diddifree-id",),
        allowed_scopes=("ride-summary:read", "profile:read"),
        active=True,
        expires_at=None,
        revoked_at=None,
    )


def make_food_client(secret_hash: str) -> ServiceClient:
    client = make_client(secret_hash)
    return ServiceClient(
        **{
            **client.__dict__,
            "client_id": "backoffice-staging-diddifood",
            "service_name": "backoffice",
            "allowed_audiences": ("diddifood",),
            "allowed_scopes": ("food:restaurants:read", "food:restaurants:write"),
        }
    )


@pytest.mark.asyncio
async def test_service_token_requires_allowed_audience_and_scope() -> None:
    import hashlib

    client = make_client(hashlib.sha256(b"secret").hexdigest())
    command = IssueServiceToken(clients=FakeClients(client), tokens=FakeTokens())

    with pytest.raises(ApiError) as error:
        await command(
            grant_type="client_credentials",
            client_id="pilotage-staging",
            client_secret="secret",
            audience="diddipay",
            scope="ride-summary:read",
        )

    assert error.value.code == "INVALID_AUDIENCE"


@pytest.mark.asyncio
async def test_service_token_returns_short_lived_bearer_response() -> None:
    import hashlib

    client = make_client(hashlib.sha256(b"secret").hexdigest())
    tokens = FakeTokens()
    command = IssueServiceToken(clients=FakeClients(client), tokens=tokens)

    result = await command(
        grant_type="client_credentials",
        client_id="pilotage-staging",
        client_secret="secret",
        audience="diddifree-id",
        scope="profile:read ride-summary:read profile:read",
    )

    assert result["access_token"] == "signed-service-token"
    assert result["token_type"] == "Bearer"
    assert result["scope"] == "profile:read ride-summary:read"
    assert tokens.kwargs["audience"] == "diddifree-id"
    assert 'diddifree_service_token_issuance_total{result="issued",service="pilotage"}' in (
        generate_latest().decode()
    )


@pytest.mark.asyncio
async def test_service_token_allows_a_registered_food_audience() -> None:
    import hashlib

    client = make_food_client(hashlib.sha256(b"secret").hexdigest())
    tokens = FakeTokens()
    command = IssueServiceToken(clients=FakeClients(client), tokens=tokens)

    result = await command(
        grant_type="client_credentials",
        client_id="backoffice-staging-diddifood",
        client_secret="secret",
        audience="diddifood",
        scope="food:restaurants:read",
    )

    assert result["access_token"] == "signed-service-token"
    assert result["scope"] == "food:restaurants:read"
    assert tokens.kwargs["audience"] == "diddifood"


@pytest.mark.asyncio
async def test_expired_service_client_is_rejected() -> None:
    import hashlib

    client = make_client(hashlib.sha256(b"secret").hexdigest())
    client = ServiceClient(**{**client.__dict__, "expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    command = IssueServiceToken(clients=FakeClients(client), tokens=FakeTokens())

    with pytest.raises(ApiError) as error:
        await command(
            grant_type="client_credentials",
            client_id="pilotage-staging",
            client_secret="secret",
            audience="diddifree-id",
            scope="profile:read",
        )

    assert error.value.code == "INVALID_CLIENT"

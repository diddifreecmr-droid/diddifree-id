"""Ticket 029: the profile carries the account creation date.

DiddiRewards reads `created_at` with a service token (scope `profile:read`) to
decide sign-up-date campaigns, so no calling service can send its own date.
"""

from datetime import UTC, datetime, timedelta

from identity_app.core.settings import settings
from tests.conftest import API


def rewards_headers(app, *, scopes: tuple[str, ...] = ("profile:read",)) -> dict[str, str]:
    client_id = "diddirewards-test-diddifreeid"
    token = app.state.tokens.issue_service_token(
        service_name="diddirewards",
        client_id=client_id,
        audience=settings.jwt_issuer,
        scopes=scopes,
        lifetime_seconds=600,
    )
    return {"Authorization": f"Bearer {token}", "X-Client-ID": client_id}


def _parse(value: str) -> datetime:
    assert value.endswith("Z"), value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_rewards_reads_the_account_creation_date(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    r = await client.get(f"{API}/users/{user_id}", headers=rewards_headers(app))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == user_id
    assert body["status"] == "active"
    created_at = _parse(body["created_at"])
    assert abs(datetime.now(UTC) - created_at) < timedelta(minutes=5)


async def test_created_at_is_the_same_on_me_and_on_the_service_lookup(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    me = await client.get(f"{API}/users/me", headers=user_session["headers"])
    # Twice: the second answer comes from the Redis profile cache.
    first = await client.get(f"{API}/users/{user_id}", headers=rewards_headers(app))
    second = await client.get(f"{API}/users/{user_id}", headers=rewards_headers(app))

    assert me.json()["created_at"] == first.json()["created_at"] == second.json()["created_at"]
    assert user_session["user"]["created_at"] is not None


async def test_rewards_without_profile_scope_is_refused(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    r = await client.get(
        f"{API}/users/{user_id}",
        headers=rewards_headers(app, scopes=("identity:support-context:read",)),
    )

    assert r.status_code == 403, r.text

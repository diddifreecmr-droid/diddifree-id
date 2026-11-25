"""MVP account deletion: reversible grace period and final anonymisation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update

from tests.conftest import API, register_and_verify


async def test_account_deletion_is_idempotent_and_restored_by_otp(client, otp_code, phone_factory, events):
    phone = phone_factory()
    body = await register_and_verify(client, otp_code, phone)
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    response = await client.delete(f"{API}/users/me", headers=headers)
    assert response.status_code == 202, response.text
    deletion = response.json()
    assert deletion["status"] == "deletion_pending"
    assert deletion["scheduled_for"] == deletion["restore_until"]

    # Repeating the request does not move the deadline or create a second job.
    response = await client.delete(f"{API}/users/me", headers=headers)
    assert response.status_code == 202
    assert response.json() == deletion

    response = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert response.status_code == 200, response.text
    response = await client.post(
        f"{API}/auth/otp/verify",
        json={"phone": phone, "code": otp_code.latest()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["status"] == "active"

    assert len(await events.read_named("user.deletion_requested")) == 1
    assert len(await events.read_named("user.deletion_cancelled")) == 1


async def test_final_purge_keeps_uuid_and_anonymises_account(client, otp_code, phone_factory):
    from identity_app.core.database import async_session_factory
    from identity_app.modules.identity.infra.models import UserModel
    from scripts.purge_deleted_accounts import purge_due_accounts

    phone = phone_factory()
    body = await register_and_verify(client, otp_code, phone)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    user_id = body["user"]["id"]

    response = await client.delete(f"{API}/users/me", headers=headers)
    assert response.status_code == 202

    async with async_session_factory() as session:
        await session.execute(
            update(UserModel)
            .where(UserModel.id == UUID(user_id))
            .values(deletion_scheduled_for=datetime.now(UTC) - timedelta(seconds=1)),
        )
        await session.commit()

    assert await purge_due_accounts() == 1

    async with async_session_factory() as session:
        user = await session.scalar(select(UserModel).where(UserModel.id == UUID(user_id)))
        assert user is not None
        assert str(user.id) == user_id
        assert user.status == "deleted"
        assert user.phone is None
        assert user.email is None
        assert user.full_name is None

    otp_code.codes.clear()
    response = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert response.status_code == 200
    assert otp_code.codes == []

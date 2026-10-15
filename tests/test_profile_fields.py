"""Profile language and photo fields."""

from __future__ import annotations

from tests.conftest import API


async def test_profile_language_and_photo_url_are_updated(client, user_session):
    response = await client.patch(
        f"{API}/users/me",
        json={"language": "en", "photo_url": "https://cdn.example.com/awa.jpg"},
        headers=user_session["headers"],
    )

    assert response.status_code == 200
    assert response.json()["language"] == "en"
    assert response.json()["photo_url"] == "https://cdn.example.com/awa.jpg"

    response = await client.get(f"{API}/users/me", headers=user_session["headers"])
    assert response.json()["language"] == "en"
    assert response.json()["photo_url"] == "https://cdn.example.com/awa.jpg"

    response = await client.patch(
        f"{API}/users/me",
        json={"photo_url": None},
        headers=user_session["headers"],
    )
    assert response.status_code == 200
    assert response.json()["photo_url"] is None


async def test_profile_rejects_unsupported_language(client, user_session):
    response = await client.patch(
        f"{API}/users/me",
        json={"language": "es"},
        headers=user_session["headers"],
    )

    assert response.status_code == 422


async def test_profile_email_requires_contact_verification(client, user_session):
    response = await client.patch(
        f"{API}/users/me",
        json={"email": "Awa.Profile@Example.com"},
        headers=user_session["headers"],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_VERIFICATION_REQUIRED"


async def test_phone_account_can_attach_email_and_login_with_it(client, user_session, otp_code):
    response = await client.post(
        f"{API}/users/me/contact/request",
        json={"email": "Awa.Profile@Example.com"},
        headers=user_session["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["contact_type"] == "email"

    response = await client.post(
        f"{API}/users/me/contact/verify",
        json={"email": "Awa.Profile@Example.com", "code": otp_code.latest()},
        headers=user_session["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "awa.profile@example.com"

    response = await client.post(
        f"{API}/auth/otp/request",
        json={"email": "awa.profile@example.com"},
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        f"{API}/auth/otp/verify",
        json={"email": "awa.profile@example.com", "code": otp_code.latest()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["id"] == user_session["user"]["id"]


async def test_email_account_can_attach_phone_and_login_with_it(client, otp_code):
    email = "phone-link@example.com"
    response = await client.post(
        f"{API}/auth/register",
        json={"email": email, "full_name": "Phone Link"},
    )
    assert response.status_code == 201, response.text

    await client.post(f"{API}/auth/otp/request", json={"email": email})
    response = await client.post(
        f"{API}/auth/otp/verify",
        json={"email": email, "code": otp_code.latest()},
    )
    assert response.status_code == 200, response.text
    session = response.json()
    phone = "+2250700012345"

    response = await client.post(
        f"{API}/users/me/contact/request",
        json={"phone": phone},
        headers=session_headers(session),
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        f"{API}/users/me/contact/verify",
        json={"phone": phone, "code": otp_code.latest()},
        headers=session_headers(session),
    )
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == phone

    response = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert response.status_code == 200, response.text

    response = await client.post(
        f"{API}/auth/otp/verify",
        json={"phone": phone, "code": otp_code.latest()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["id"] == session["user"]["id"]


async def test_contact_link_rejects_email_already_owned(client, user_session, otp_code, phone_factory):
    response = await client.post(
        f"{API}/users/me/contact/request",
        json={"email": "owned@example.com"},
        headers=user_session["headers"],
    )
    assert response.status_code == 200, response.text
    await client.post(
        f"{API}/users/me/contact/verify",
        json={"email": "owned@example.com", "code": otp_code.latest()},
        headers=user_session["headers"],
    )

    second = await client.post(
        f"{API}/auth/register",
        json={"phone": phone_factory("+22508")},
    )
    assert second.status_code == 201, second.text
    await client.post(f"{API}/auth/otp/request", json={"phone": second.json()["phone"]})
    second_login = await client.post(
        f"{API}/auth/otp/verify",
        json={"phone": second.json()["phone"], "code": otp_code.latest()},
    )
    assert second_login.status_code == 200, second_login.text

    response = await client.post(
        f"{API}/users/me/contact/request",
        json={"email": "owned@example.com"},
        headers={"Authorization": f"Bearer {second_login.json()['access_token']}"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def session_headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}

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

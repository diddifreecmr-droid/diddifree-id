"""Profile update events include the changed profile fields."""

from __future__ import annotations

from tests.conftest import API


async def test_profile_fields_are_included_in_changed_fields(client, user_session, events):
    await client.patch(
        f"{API}/users/me",
        json={"language": "en", "photo_url": "https://cdn.example.com/profile.jpg"},
        headers=user_session["headers"],
    )

    published = await events.read_named("user.updated")

    assert len(published) == 1
    assert published[0]["changed_fields"] == ["language", "photo_url"]

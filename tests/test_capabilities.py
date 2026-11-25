from datetime import UTC, datetime
from uuid import uuid4

import pytest

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.commands.capabilities import (
    RequestCapability,
    UpdateCapabilityProjection,
)
from identity_app.modules.identity.domain.capabilities import Capability
from identity_app.shared_kernel.events.bus import NullEventPublisher


class FakeCapabilities:
    def __init__(self, capability: Capability | None = None) -> None:
        self.capability = capability
        self.commits = 0

    async def get(self, user_id, service, capability_type):  # noqa: ANN001
        return self.capability

    async def upsert(self, **kwargs):  # noqa: ANN003
        now = datetime.now(UTC)
        self.capability = Capability(
            user_id=kwargs["user_id"],
            service=kwargs["service"],
            capability_type=kwargs["capability_type"],
            access_status=kwargs.get("access_status") or "requested",
            operational_status=kwargs.get("operational_status") or "unknown",
            status_source=kwargs.get("status_source") or "diddifreeid",
            actions=tuple(kwargs.get("actions") or ()),
            projection_version=kwargs.get("projection_version") or 1,
            last_event_id=kwargs.get("last_event_id"),
            updated_at=now,
            created_at=now,
        )
        return self.capability

    async def commit(self):
        self.commits += 1


class FakeUsers:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    async def get_by_id(self, user_id):  # noqa: ANN001
        return object() if self.exists else None


@pytest.mark.asyncio
async def test_request_capability_is_idempotent() -> None:
    repo = FakeCapabilities()
    command = RequestCapability(repo, NullEventPublisher(), FakeUsers())
    user_id = uuid4()

    first = await command(user_id=user_id, service="diddisend", capability_type="courier")
    second = await command(user_id=user_id, service="diddisend", capability_type="courier")

    assert first["access_status"] == "requested"
    assert second["access_status"] == "requested"
    assert repo.commits == 1


@pytest.mark.asyncio
async def test_projection_rejects_same_version_with_another_event() -> None:
    now = datetime.now(UTC)
    repo = FakeCapabilities(
        Capability(
            user_id=uuid4(),
            service="diddisend",
            capability_type="courier",
            access_status="requested",
            operational_status="offline",
            status_source="diddisend",
            actions=(),
            projection_version=2,
            last_event_id="evt-2",
            updated_at=now,
            created_at=now,
        ),
    )
    command = UpdateCapabilityProjection(repo, NullEventPublisher(), FakeUsers())

    with pytest.raises(ApiError) as error:
        await command(
            user_id=repo.capability.user_id,
            service="diddisend",
            capability_type="courier",
            operational_status="ready",
            actions=[],
            projection_version=2,
            event_id="evt-other",
        )

    assert error.value.code == "CAPABILITY_VERSION_CONFLICT"

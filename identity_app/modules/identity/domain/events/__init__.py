"""Domain events published by DiddiFreeID.

The payload shape is fixed by the API contract §4 — `event`, `user_id`, `role`,
`at`, plus whatever the specific event adds. Subscribers across the ecosystem
parse it, so it is as much a contract as the HTTP routes are.

Why these exist at all (architecture §6): without them, Wallet would have to
poll or to call DiddiFreeID on every signup to ask "does this user exist yet".
Instead it subscribes to `user.registered` and creates the wallet account by
itself. The dependency arrow points from the modules to identity, never back.
"""

from identity_app.modules.identity.domain.events.user_events import (
    DomainEvent,
    UserRegistered,
    UserRoleChanged,
    UserStatusChanged,
    UserUpdated,
)

__all__ = [
    "DomainEvent",
    "UserRegistered",
    "UserRoleChanged",
    "UserStatusChanged",
    "UserUpdated",
]

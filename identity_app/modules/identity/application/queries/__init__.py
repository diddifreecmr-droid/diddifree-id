"""Queries — the read half of the CQRS split.

Every class here is side-effect free. The contract each one honours
(architecture §2):

  * reads through `UserReadRepository`, never a write repository;
  * may serve from the Redis cache, and populates it on a miss;
  * emits no domain event, opens no transaction, writes nothing;
  * never invokes a command.

Today both sides sit on the same PostgreSQL database. Should read volume ever
justify a replica, only the session handed to `SqlAlchemyUserReadRepository`
changes — which is the entire point of keeping this boundary honest while it is
still cheap to maintain.
"""

from identity_app.modules.identity.application.queries.get_jwks import GetJwks
from identity_app.modules.identity.application.queries.get_user import (
    GetCurrentUserProfile,
    GetUserById,
    GetUserByPhone,
)
from identity_app.modules.identity.application.queries.list_users import ListUsers

__all__ = [
    "GetCurrentUserProfile",
    "GetJwks",
    "GetUserById",
    "GetUserByPhone",
    "ListUsers",
]

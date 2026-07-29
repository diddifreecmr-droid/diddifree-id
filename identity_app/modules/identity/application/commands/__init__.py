"""Commands — the write half of the CQRS split.

Every class here changes state. The contract each one honours (architecture §2):

  * goes through `UserWriteRepository` / the other write repositories, never the
    read repository;
  * never reads the profile cache — a decision made from a cached row could be
    persisted as fact;
  * invalidates the cache for any user it touched;
  * emits its domain events after the write is committed;
  * commits explicitly before returning, because the client can issue its next
    request before FastAPI tears the session down.

No command ever calls a query, and no query ever calls a command.
"""

from identity_app.modules.identity.application.commands.change_role import ChangeRole
from identity_app.modules.identity.application.commands.change_status import ChangeStatus
from identity_app.modules.identity.application.commands.decide_kyc import DecideKyc
from identity_app.modules.identity.application.commands.logout import Logout
from identity_app.modules.identity.application.commands.refresh_token import RefreshAccessToken
from identity_app.modules.identity.application.commands.register_user import RegisterUser
from identity_app.modules.identity.application.commands.request_otp import RequestOtp
from identity_app.modules.identity.application.commands.update_profile import UpdateProfile
from identity_app.modules.identity.application.commands.verify_otp import VerifyOtp

__all__ = [
    "ChangeRole",
    "ChangeStatus",
    "DecideKyc",
    "Logout",
    "RefreshAccessToken",
    "RegisterUser",
    "RequestOtp",
    "UpdateProfile",
    "VerifyOtp",
]

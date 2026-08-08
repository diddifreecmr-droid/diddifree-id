"""OTP delivery.

No SMS aggregator is contracted yet, so the shipped implementation logs the
code — the same stand-in DiddiGo uses, which keeps local development and the
test suite working without a provider account.

The port is what matters: when an aggregator is chosen, it becomes one more
class here and nothing in `application/` changes.
"""

from __future__ import annotations

import logging

from identity_app.core.settings import settings

logger = logging.getLogger(__name__)


class LoggingOtpSender:
    """Development sender — writes the code to the log.

    Guarded by `OTP_LOG_PLAINTEXT`. With the flag off, the code is not logged at
    all: an OTP in a production log file is a credential in a production log
    file, readable by anyone with access to log aggregation.
    """

    async def send(
        self,
        phone: str | None,
        code: str,
        channel: str | None = None,
        email: str | None = None,
    ) -> None:
        identifier = phone or email
        if settings.otp_log_plaintext:
            logger.warning(
                "OTP stub — en développement, le code pour identifier=%s est %s. "
                "Intégration SMS à brancher.",
                identifier,
                code,
            )
        else:
            logger.info("OTP émis pour identifier=%s (code non journalisé)", identifier)

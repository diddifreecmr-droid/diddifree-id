"""Startup guards for transports that are deliberately switched off."""

import pytest
from fastapi import FastAPI

from identity_app.core.lifespan import lifespan
from identity_app.core.settings import settings


async def test_startup_refuses_telegram_as_default_channel(monkeypatch):
    """The bot is commented out; a stack still pointing at it must not boot.

    Booting would turn every default OTP request into a 502, which is a far
    worse failure to diagnose than a container that exits with the reason.
    """
    monkeypatch.setattr(settings, "otp_provider", "telegram")

    with pytest.raises(RuntimeError, match="telegram"):
        async with lifespan(FastAPI()):
            pass  # pragma: no cover - startup must fail before this point

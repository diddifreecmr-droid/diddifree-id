"""Small Telegram Bot API adapter for staging OTP delivery.

The bot is intentionally implemented against Telegram's HTTP API instead of a
large client library. The app already depends on httpx, and keeping the
adapter small makes the OTP port easy to replace later.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from identity_app.core.database import async_session_factory
from identity_app.core.errors import ApiError
from identity_app.core.settings import settings
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.infra.models import UserModel

logger = logging.getLogger(__name__)


class TelegramApiError(RuntimeError):
    """Telegram rejected an API request."""


class TelegramClient:
    def __init__(self, token: str, *, poll_timeout_seconds: int = 25) -> None:
        self._poll_timeout_seconds = poll_timeout_seconds
        self._http = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=35.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, payload: Mapping[str, object] | None = None) -> object:
        response = await self._http.post(f"/{method}", json=dict(payload or {}))
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise TelegramApiError(f"Telegram {method} failed: {body.get('description', 'unknown error')}")
        return body.get("result")

    async def get_me(self) -> object:
        return await self.call("getMe")

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", {"drop_pending_updates": False})

    async def get_updates(self, *, offset: int | None) -> list[dict]:
        result = await self.call(
            "getUpdates",
            {"offset": offset, "timeout": self._poll_timeout_seconds, "allowed_updates": ["message"]},
        )
        return list(result or [])

    async def send_message(self, chat_id: int, text: str, *, reply_markup: dict | None = None) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        await self.call("sendMessage", payload)


class TelegramBotWorker:
    """Receive `/start` and contact messages using staging long polling."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def run(self) -> None:
        offset: int | None = None
        while True:
            try:
                for update in await self._client.get_updates(offset=offset):
                    offset = int(update["update_id"]) + 1
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram polling failed; retrying")
                await asyncio.sleep(5)

    async def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        sender_id = sender.get("id")
        if chat.get("type") != "private" or chat_id is None or sender_id is None:
            return

        text = str(message.get("text") or "")
        if text.startswith("/start") or text.startswith("/help"):
            await self._client.send_message(
                int(chat_id),
                "Pour recevoir les codes DiddiFreeID, partage ton propre numéro de téléphone.",
                reply_markup={
                    "keyboard": [[{"text": "Partager mon numéro", "request_contact": True}]],
                    "resize_keyboard": True,
                    "one_time_keyboard": True,
                },
            )
            return

        contact = message.get("contact")
        if contact:
            await self._link_contact(
                chat_id=int(chat_id),
                sender_id=int(sender_id),
                contact=contact,
            )

    async def _link_contact(self, *, chat_id: int, sender_id: int, contact: dict) -> None:
        if contact.get("user_id") != sender_id:
            await self._client.send_message(chat_id, "Utilise le bouton pour partager ton propre contact.")
            return

        try:
            phone = validate_phone(str(contact.get("phone_number") or ""))
        except ApiError:
            await self._client.send_message(chat_id, "Le numéro Telegram n'est pas dans un format valide.")
            return

        try:
            async with async_session_factory() as session:
                result = await session.execute(select(UserModel).where(UserModel.phone == phone))
                user = result.scalar_one_or_none()
                if user is None:
                    await self._client.send_message(chat_id, "Aucun compte DiddiFreeID ne correspond à ce numéro.")
                    return
                user.telegram_user_id = sender_id
                user.telegram_chat_id = chat_id
                await session.commit()
        except IntegrityError:
            await self._client.send_message(chat_id, "Ce compte Telegram est déjà lié à un autre compte DiddiFreeID.")
            return

        await self._client.send_message(
            chat_id,
            "Ton compte DiddiFreeID est lié. Les prochains codes OTP arriveront ici.",
        )
        logger.info("Telegram linked for user phone suffix=%s", phone[-4:])


class TelegramOtpSender:
    """Send an OTP to the chat linked to the requested phone number."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def send(self, phone: str, code: str, channel: str | None = None) -> None:
        # Keep staging supportable without an SMS provider. This is deliberately
        # independent from Telegram delivery: the code must remain visible in
        # logs while OTP_LOG_PLAINTEXT=true, even when no chat is linked yet.
        if settings.otp_log_plaintext:
            logger.warning(
                "OTP Telegram - le code pour phone=%s est %s.",
                phone,
                code,
            )
        else:
            logger.info("OTP Telegram emis pour phone=%s (code non journalise)", phone)

        async with async_session_factory() as session:
            result = await session.execute(
                select(UserModel.telegram_chat_id).where(UserModel.phone == phone),
            )
            chat_id = result.scalar_one_or_none()

        if chat_id is None:
            logger.warning("No Telegram chat linked for phone suffix=%s", phone[-4:])
            return

        await self._client.send_message(
            int(chat_id),
            f"Code DiddiFreeID : {code}\n\nCe code expire dans 5 minutes.",
        )

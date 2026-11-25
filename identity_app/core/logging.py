"""DIDDI Observability v1 JSON logging and request-correlation helpers."""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from identity_app.core.metrics import observe_telemetry_dropped
from identity_app.core.observability import OBSERVABILITY_SCHEMA_VERSION, ServiceIdentity, service_identity
from identity_app.core.settings import settings
from identity_app.core.tracing import current_trace_fields

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_request_id_pattern = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_record_factory_configured = False
_identity: ServiceIdentity | None = None
_MAX_LOG_LINE_BYTES = 64 * 1024
_FILE_HANDLER_MARKER = "_diddi_observability_file_handler"

# No formatter can compensate for logging request bodies. This defensive pass
# handles accidental secrets in third-party exception messages.
_SENSITIVE_VALUE = re.compile(
    r"(?i)(authorization|token|secret|password|api[_-]?key|cookie|otp|pin)"
    r"([\s:=]+)(bearer\s+)?([^\s,;\]\}\"']+)",
)
_PHONE = re.compile(r"(?<!\d)\+?\d[\d .()-]{6,}\d(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_OTP_CODE = re.compile(r"(?i)\b(?:otp|code)[^\d]{0,24}\d{4,8}\b")
# Telegram embeds the bot credential in the URL path (`/bot<id>:<secret>/`).
# The generic key=value pass below cannot see it, and the phone pass only
# happened to hide the numeric half.
_URL_BOT_TOKEN = re.compile(r"(?i)/bot\d+:[A-Za-z0-9_-]+")


def _redact(value: str) -> str:
    value = _URL_BOT_TOKEN.sub("/bot***", value)
    value = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", value)
    value = _OTP_CODE.sub("OTP ***", value)
    value = _EMAIL.sub("***", value)
    return _PHONE.sub("***", value)


def _truncate(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore") + "…"


def new_request_id(candidate: str | None = None, fallback: str | None = None) -> str:
    """Return a valid request/correlation id or create an opaque replacement."""

    for value in (candidate, fallback):
        normalized = (value or "").strip()
        if _request_id_pattern.fullmatch(normalized):
            return normalized
    return uuid.uuid4().hex


def set_request_id(value: str) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


def get_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """One bounded, redacted JSON object per output line."""

    _attribute_fields = {
        "method": "http.request.method",
        "route": "http.route",
        "status_code": "http.response.status_code",
        "duration_ms": "duration_ms",
        "error_code": "error.code",
    }

    def _payload(self, record: logging.LogRecord) -> dict[str, Any]:
        identity = _identity or service_identity()
        level = {"WARNING": "warn", "CRITICAL": "fatal"}.get(record.levelname, record.levelname.lower())
        attributes: dict[str, Any] = {}
        for field, target in self._attribute_fields.items():
            value = getattr(record, field, None)
            if value is not None:
                attributes[target] = value
        # This explicit staging escape hatch is intentionally narrow: only
        # OTP senders may attach these fields, and they are emitted only when
        # an operator sets OTP_LOG_PLAINTEXT=true. All ordinary log messages
        # still go through the unconditional credential/PII redaction below.
        if settings.otp_log_plaintext and getattr(record, "otp_code", None):
            attributes["otp.code"] = str(record.otp_code)
            recipient = getattr(record, "otp_recipient", None)
            if recipient:
                attributes["otp.recipient"] = str(recipient)
        if record.exc_info:
            exception_type, exception, _traceback = record.exc_info
            attributes["error.type"] = exception_type.__name__ if exception_type else "Exception"
            attributes["error.message"] = _redact(str(exception))
            attributes["error.stack"] = _redact(self.formatException(record.exc_info))

        payload: dict[str, Any] = {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": level,
            "event": getattr(record, "event", "log.unclassified"),
            "message": _redact(record.getMessage()),
            "resource": identity.as_resource_attributes(),
            "attributes": attributes,
        }
        request_id = getattr(record, "request_id", get_request_id())
        if request_id:
            payload["request_id"] = request_id
        payload.update(current_trace_fields())
        return payload

    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = self._payload(record)
            encoded = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
            if len(encoded.encode("utf-8")) <= _MAX_LOG_LINE_BYTES:
                return encoded

            attributes = payload["attributes"]
            attributes["truncated"] = True
            if "error.stack" in attributes:
                attributes["error.stack"] = _truncate(str(attributes["error.stack"]), 8 * 1024)
            payload["message"] = _truncate(str(payload["message"]), 4 * 1024)
            encoded = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > _MAX_LOG_LINE_BYTES:
                payload["attributes"] = {"truncated": True}
                payload["message"] = "Événement de log tronqué"
                encoded = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
            return encoded
        except Exception:
            # Logging never breaks business code. Count the loss and emit the
            # smallest valid fallback record without recursively logging.
            observe_telemetry_dropped(signal="logs", reason="serialization_error")
            return json.dumps(
                {
                    "schema_version": OBSERVABILITY_SCHEMA_VERSION,
                    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "level": "error",
                    "event": "telemetry.log.serialization_failed",
                    "message": "Événement de log abandonné",
                    "resource": (_identity or service_identity()).as_resource_attributes(),
                    "attributes": {"truncated": True},
                },
                separators=(",", ":"),
            )


class _SafeRotatingFileHandler(RotatingFileHandler):
    """A failed optional log sink must not write raw records to stderr."""

    def handleError(self, _record: logging.LogRecord) -> None:
        observe_telemetry_dropped(signal="logs", reason="file_write_error")


def _configure_json_file_sink(root: logging.Logger, formatter: JsonFormatter) -> None:
    """Add the optional, bounded JSONL handoff file without risking traffic."""

    configured = settings.observability_log_file.strip()
    for handler in list(root.handlers):
        if getattr(handler, _FILE_HANDLER_MARKER, False) and getattr(handler, "baseFilename", None) != configured:
            root.removeHandler(handler)
            handler.close()

    if not configured or any(getattr(handler, "baseFilename", None) == configured for handler in root.handlers):
        return
    try:
        Path(configured).parent.mkdir(parents=True, exist_ok=True)
        handler = _SafeRotatingFileHandler(
            configured,
            maxBytes=settings.observability_log_max_bytes,
            backupCount=settings.observability_log_backup_count,
            encoding="utf-8",
            delay=True,
        )
        setattr(handler, _FILE_HANDLER_MARKER, True)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        observe_telemetry_dropped(signal="logs", reason="file_sink_unavailable")


def configure_logging(level: str = "INFO", *, component: str | None = None) -> None:
    """Route application, library and Uvicorn logs through the same cleaner."""

    global _identity, _record_factory_configured
    _identity = service_identity(component=component)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    formatter = JsonFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)
    _configure_json_file_sink(root, formatter)

    # Uvicorn access logs carry raw client IPs and duplicate the normalized
    # request-completion event produced by the ASGI middleware below.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = True
    # httpx logs every outbound request line at INFO, full URL included.
    # Provider URLs can embed credentials (Telegram puts the bot token in the
    # path), so third-party HTTP clients only speak above INFO.
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    for logger_name in ("uvicorn", "uvicorn.error", "alembic"):
        managed_logger = logging.getLogger(logger_name)
        managed_logger.handlers.clear()
        managed_logger.propagate = True

    if not _record_factory_configured:
        previous_factory = logging.getLogRecordFactory()

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous_factory(*args, **kwargs)
            if not hasattr(record, "request_id"):
                record.request_id = get_request_id()
            return record

        logging.setLogRecordFactory(record_factory)
        _record_factory_configured = True

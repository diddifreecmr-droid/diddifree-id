"""Logging helpers shared by the HTTP layer and application modules."""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from identity_app.core.observability import ServiceIdentity, service_identity
from identity_app.core.tracing import current_trace_fields

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_request_id_pattern = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_record_factory_configured = False
_identity: ServiceIdentity | None = None

# This is intentionally a last line of defence. Application code must not log
# request bodies or headers, but third-party exceptions occasionally include a
# URL or an Authorization header.
_SENSITIVE_VALUE = re.compile(
    r"(?i)(authorization|token|secret|password|api[_-]?key|cookie)"
    r"([\s:=]+)(bearer\s+)?([^\s,;\]\}\"']+)",
)


def _redact(value: str) -> str:
    return _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", value)


def new_request_id(candidate: str | None = None) -> str:
    """Return a safe incoming request id or generate one when needed."""

    value = (candidate or "").strip()
    if _request_id_pattern.fullmatch(value):
        return value
    return uuid.uuid4().hex


def set_request_id(value: str) -> object:
    """Set the request id for the current async context."""

    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    """Restore the request id that existed before the current request."""

    _request_id.reset(token)  # type: ignore[arg-type]


def get_request_id() -> str:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """Small JSON formatter suitable for Docker stdout and log collectors."""

    _extra_fields = (
        "method",
        "path",
        "status_code",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        identity = _identity or service_identity()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "severity": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.msg if isinstance(record.msg, str) else "log"),
            "message": _redact(record.getMessage()),
            "request_id": getattr(record, "request_id", get_request_id()),
            **identity.as_dict(),
        }
        payload.update(current_trace_fields())

        for field in self._extra_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, component: str | None = None) -> None:
    """Configure application logs without replacing Uvicorn's own loggers."""

    global _identity, _record_factory_configured

    _identity = service_identity(component=component)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    formatter = JsonFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)

    if not _record_factory_configured:
        previous_factory = logging.getLogRecordFactory()

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous_factory(*args, **kwargs)
            if not hasattr(record, "request_id"):
                record.request_id = get_request_id()
            return record

        logging.setLogRecordFactory(record_factory)
        _record_factory_configured = True

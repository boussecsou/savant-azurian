"""BFF-only logging: emit fixed events, never request or exception payloads."""

import logging
import logging.config
import re

from savant.correlation import is_correlation_id

EVENTS = {
    "oauth_callback_completed",
    "oauth_callback_rejected",
    "oauth_callback_failed",
    "bff_startup_failed",
    "chat_relay_timeout",
    "chat_relay_failed",
    "chat_stream_failed",
    "warmup_failed",
    "chat_relay_completed",
    "speech_token_failed",
}
RELAY_EVENTS = {"chat_relay_failed", "chat_stream_failed", "warmup_failed", "speech_token_failed"}


_ERROR_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")


def _relay_detail(record):
    """Allow only an HTTP status code or an exception class name for relay failures."""
    status = getattr(record, "agent_status", None)
    if type(status) is int and 100 <= status <= 599:
        return f" status={status}"
    error_type = getattr(record, "error_type", None)
    if isinstance(error_type, str) and _ERROR_TYPE.fullmatch(error_type):
        return f" type={error_type}"
    return ""


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Never call getMessage()/formatException(): args, exceptions and extra
        # fields can contain URLs, credentials, headers or provider responses.
        if record.name == "savant.bff" and isinstance(record.msg, str) and record.msg in EVENTS:
            event = record.msg
        elif record.name.startswith("uvicorn"):
            event = "bff_server_error" if record.levelno >= logging.ERROR else "bff_server_event"
        else:
            event = "bff_dependency_error" if record.levelno >= logging.ERROR else "bff_dependency_warning"
        level = (
            "ERROR" if record.levelno >= logging.ERROR else "WARNING" if record.levelno >= logging.WARNING else "INFO"
        )
        detail = _relay_detail(record) if event in RELAY_EVENTS else ""
        correlation = getattr(record, "correlation", None)
        if event in RELAY_EVENTS | {"chat_relay_completed"} and is_correlation_id(correlation):
            detail += f" correlation={correlation}"
        return f"{level} {event}{detail}"


class SafeEvents(logging.Filter):
    def filter(self, record):
        if record.name == "uvicorn.access":
            return False
        return record.name in {"savant.bff", "uvicorn", "uvicorn.error"} or record.levelno >= logging.WARNING


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {"safe": {"()": "savant.bff_logging.SafeFormatter"}},
    "filters": {"safe": {"()": "savant.bff_logging.SafeEvents"}},
    "handlers": {
        "safe": {
            "class": "logging.StreamHandler",
            "formatter": "safe",
            "filters": ["safe"],
            "stream": "ext://sys.stderr",
        }
    },
    "root": {"level": "WARNING", "handlers": ["safe"]},
    "loggers": {
        name: {"handlers": ["safe"], "level": "INFO", "propagate": False}
        for name in ("savant.bff", "uvicorn", "uvicorn.error", "uvicorn.access")
    },
}


def configure_bff_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
    logging.captureWarnings(True)

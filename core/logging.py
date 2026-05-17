"""Structured JSON logging — machine-parseable for log aggregators.

In development, logs are plaintext for readability.
In production, logs are JSON for CloudWatch/Datadog/Loki ingestion.
"""

import logging
import sys

try:
    # python-json-logger >= 3.x
    from pythonjsonlogger.json import JsonFormatter
except ImportError:
    # python-json-logger < 3.x fallback
    from pythonjsonlogger.jsonlogger import JsonFormatter

from core.config import settings


def configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)

    if settings.is_production:
        formatter = JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s"
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats a LogRecord as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "event_id": getattr(record, "event_id", None),
            "stage": getattr(record, "stage", None),
            "msg": record.getMessage(),
        }
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a JSON-formatted handler to the root logger."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

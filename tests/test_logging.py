import json
import logging

from app.logging_config import JSONFormatter


def test_json_formatter_includes_expected_keys():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="finn",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event processed",
        args=None,
        exc_info=None,
    )
    record.event_id = "evt-123"
    record.stage = "parser"

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["ts"]
    assert data["level"] == "INFO"
    assert data["event_id"] == "evt-123"
    assert data["stage"] == "parser"
    assert data["msg"] == "event processed"

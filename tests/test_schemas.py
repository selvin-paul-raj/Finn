import pytest
from pydantic import ValidationError

from app.schemas import ParsedEvent


def test_valid_parsed_event():
    e = ParsedEvent(direction="debit", amount="120.00", category="Food", confidence=0.92)
    assert e.direction == "debit"
    assert e.category == "Food"


def test_rejects_bad_direction():
    with pytest.raises(ValidationError):
        ParsedEvent(direction="sideways", amount="10", category="Food", confidence=0.9)


def test_rejects_negative_amount():
    with pytest.raises(ValidationError):
        ParsedEvent(direction="debit", amount="-5", category="Food", confidence=0.9)


def test_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        ParsedEvent(direction="debit", amount="10", category="Food", confidence=1.5)

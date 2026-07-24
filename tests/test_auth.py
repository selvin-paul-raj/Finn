import pytest
from fastapi import HTTPException

from app.main import verify_bearer_token

EXPECTED = "secret-token"


def test_missing_header_rejected():
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(None, EXPECTED)
    assert exc_info.value.status_code == 401


def test_wrong_token_rejected():
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token("Bearer wrong-token", EXPECTED)
    assert exc_info.value.status_code == 401


def test_correct_token_passes():
    assert verify_bearer_token(f"Bearer {EXPECTED}", EXPECTED) is None

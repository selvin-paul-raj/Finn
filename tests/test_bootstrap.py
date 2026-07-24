from fastapi import FastAPI

from app.config import FEATURES
from app.main import app


def test_app_is_fastapi_instance():
    assert isinstance(app, FastAPI)


def test_features_dict_has_documented_keys():
    assert set(FEATURES.keys()) == {
        "mcp_enabled",
        "telegram_enabled",
        "scheduler_enabled",
        "experimental_parser_v2",
    }

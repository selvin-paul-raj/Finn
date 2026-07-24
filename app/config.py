import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TRIGGER_SECRET = os.environ.get("TRIGGER_SECRET")
MCP_API_KEY = os.environ.get("MCP_API_KEY")

FEATURES = {
    "mcp_enabled": True,
    "telegram_enabled": True,
    "scheduler_enabled": True,
    "experimental_parser_v2": False,
}

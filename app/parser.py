import json
from typing import Protocol

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY
from app.schemas import ParsedEvent

_SYSTEM_PROMPT = """You parse a short natural-language personal finance message \
into structured JSON. Respond with ONLY a JSON object, no other text or \
markdown, with these keys:

- direction: "credit" or "debit"
- amount: a positive number (digits only, no currency symbol)
- category: a short category label (e.g. "Food", "Salary", "EMI", "Transport", "Other")
- confidence: your confidence in this parse, from 0.0 to 1.0
- notes: a short string with anything noteworthy the amount/category don't \
capture (e.g. "no reason given"), or omit the key entirely if there's nothing to add

If the message is ambiguous or you can't confidently extract an amount, still \
return your best-guess direction/amount/category but set confidence low \
(below 0.5) rather than refusing to answer."""


class EventParser(Protocol):
    async def parse(self, text: str) -> ParsedEvent: ...


class GeminiEventParser:
    async def parse(self, text: str) -> ParsedEvent:
        raw = await self._call_gemini(text)  # untrusted dict from the model
        return ParsedEvent.model_validate(raw)  # raises if the shape is wrong

    async def _call_gemini(self, text: str) -> dict:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
        return json.loads(response.text)

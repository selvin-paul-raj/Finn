import asyncio
import json
import time
from typing import Protocol

import httpx

from app.config import NVIDIA_API_KEY, NVIDIA_BASE_URL
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


class AsyncRateLimiter:
    """Sliding window rate limiter to maintain NVIDIA API RPM (Rate Per Minute)."""

    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls: list[float] = []
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            # Filter calls outside the sliding window
            self.calls = [t for t in self.calls if now - t < self.period]
            if len(self.calls) >= self.max_calls:
                # Sleep until the oldest call falls outside the window
                sleep_time = self.period - (now - self.calls[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                now = time.monotonic()
                self.calls = [t for t in self.calls if now - t < self.period]
            self.calls.append(time.monotonic())


# Maintain NVIDIA API rate limit (RPM is 40)
_limiter = AsyncRateLimiter(40, 60.0)


class EventParser(Protocol):
    async def parse(self, text: str) -> ParsedEvent: ...


class NvidiaEventParser:
    async def parse(self, text: str) -> ParsedEvent:
        raw = await self._call_nvidia(text)  # untrusted dict from the model
        return ParsedEvent.model_validate(raw)  # raises if the shape is wrong

    async def _call_nvidia(self, text: str) -> dict:
        await _limiter.acquire()

        if not NVIDIA_API_KEY:
            raise ValueError("NVIDIA_API_KEY environment variable is not set")

        headers = {
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "deepseek-ai/deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{NVIDIA_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            res_json = response.json()
            content = res_json["choices"][0]["message"]["content"]

            # Clean up markdown code block wrapping if present
            content_str = content.strip()
            if content_str.startswith("```json"):
                content_str = content_str[7:]
            if content_str.endswith("```"):
                content_str = content_str[:-3]
            content_str = content_str.strip()

            return json.loads(content_str)

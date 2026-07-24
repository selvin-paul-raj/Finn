from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ParsedEvent(BaseModel):
    direction: Literal["credit", "debit"]
    amount: Decimal = Field(gt=0)
    category: str
    confidence: float = Field(ge=0, le=1)
    notes: str | None = None

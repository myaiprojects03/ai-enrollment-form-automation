"""What the mapper produces for one record."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _f
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

State = Literal["mapped", "ambiguous", "unmapped", "edited"]
Method = Literal["rule", "derived", "llm", "default", "edited", "none"]


@dataclass
class FieldResult:
    field: str
    value: Any = None
    source_fields: list[str] = _f(default_factory=list)
    confidence: float = 0.0
    state: State = "unmapped"
    method: Method = "none"
    assumption: str | None = None          # may quote the source: stored encrypted, shown only on reveal
    candidates: list[str] = _f(default_factory=list)   # other source keys or options it could be

    @property
    def resolved(self) -> bool:
        return self.state in ("mapped", "ambiguous", "edited") and self.value is not None

    def note(self, text: str | None) -> None:
        if text:
            self.assumption = f"{self.assumption} {text}" if self.assumption else text


@dataclass
class MappingResult:
    fields: dict[str, FieldResult]
    unused_source_fields: list[str] = _f(default_factory=list)
    mapper: str = "rules"                  # e.g. "rules+groq:openai/gpt-oss-120b"
    llm_used: bool = False
    llm_error: str | None = None           # a short reason; never contains record data
    llm_needed: bool = False               # fields were left that only the AI mapper could find

    def payload(self) -> dict[str, Any]:
        """The values to validate and submit."""
        return {name: f.value for name, f in self.fields.items() if f.resolved}

    @property
    def min_confidence(self) -> float | None:
        scores = [f.confidence for f in self.fields.values() if f.resolved]
        return round(min(scores), 3) if scores else None


class MappingPayload(BaseModel):
    """The mapper's answer in the brief's contract: values, a confidence per field, what could not be placed or
    could be more than one thing, and every assumption made."""
    model_config = ConfigDict(extra="forbid")
    mapped_fields: dict[str, Any]
    confidence_scores: dict[str, float]
    unmapped_or_ambiguous_fields: list[str]
    assumptions_made: list[str]


def contract(fields: list[FieldResult], labels: dict[str, str], needed: set[str]) -> MappingPayload:
    """`needed`: fields the form requires for this record (unmapped optional fields are not a gap)."""
    resolved = [f for f in fields if f.resolved]
    return MappingPayload(
        mapped_fields={f.field: f.value for f in resolved},
        confidence_scores={f.field: round(f.confidence, 3) for f in resolved},
        unmapped_or_ambiguous_fields=sorted(f.field for f in fields
                                            if f.state == "ambiguous" or (not f.resolved and f.field in needed)),
        assumptions_made=[f"{labels.get(f.field, f.field)}: {f.assumption}" for f in fields if f.assumption],
    )

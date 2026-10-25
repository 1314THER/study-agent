"""Stable, replaceable interfaces for student answer analysis.

The persisted API currently uses JSON objects; these types document and validate
the cross-component contract without coupling callers to OCR or model providers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, Sequence


@dataclass(frozen=True)
class AssessmentSpec:
    question_id: str
    question_no: int
    question: str
    question_type: Optional[str]
    answer_result: dict[str, Any]
    difficulty: dict[str, Any] = field(default_factory=dict)
    knowledge_tags: tuple[str, ...] = ()
    tags_confirmed: bool = False
    routines: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["knowledge_tags"] = list(self.knowledge_tags)
        value["routines"] = list(self.routines)
        return value


@dataclass(frozen=True)
class ResponseEvidence:
    source: Optional[str]
    original_text: str
    reviewed_text: str
    review_status: str
    source_pages: tuple[int, ...] = ()
    ocr_confidence: Optional[str] = None
    error_evidence: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_pages"] = list(self.source_pages)
        value["error_evidence"] = list(self.error_evidence)
        return value


@dataclass(frozen=True)
class TimingEvidence:
    source: str
    scope: str
    interval: Optional[dict[str, int]] = None
    events: tuple[dict[str, Any], ...] = ()
    response_signals: tuple[dict[str, Any], ...] = ()
    self_report: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["events"] = list(self.events)
        value["response_signals"] = list(self.response_signals)
        return value


@dataclass(frozen=True)
class DiagnosticFinding:
    id: str
    kind: str
    title: str
    observation: str
    supporting_evidence: tuple[dict[str, Any], ...]
    counter_evidence: tuple[dict[str, Any], ...]
    evidence_level: str
    possible_causes: tuple[Any, ...]
    recommendation: str
    validation_target: str
    cause_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("supporting_evidence", "counter_evidence", "possible_causes"):
            value[name] = list(value[name])
        return value


class AnswerExtractor(Protocol):
    def extract_page(self, image_base64: str, prompt: str, *, teacher: Optional[str] = None) -> str: ...


class Grader(Protocol):
    def grade(self, assessment: AssessmentSpec, response: ResponseEvidence,
              *, full_score: Optional[float], rubric: Sequence[dict[str, Any]],
              objective_rule: Optional[dict[str, Any]], teacher: Optional[str]) -> dict[str, Any]: ...


class DiagnosticEngine(Protocol):
    def analyze(self, attempts: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


class RecommendationBuilder(Protocol):
    def build(self, findings: Sequence[dict[str, Any]], *, max_items: int = 3) -> list[dict[str, Any]]: ...

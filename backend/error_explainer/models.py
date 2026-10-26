"""Data models for the JCL Error Explainer engine."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from llm_provider import TokenUsage


class ErrorCategory(str, Enum):
    ABEND = "abend"
    USER_ABEND = "user_abend"
    JCL_ERROR = "jcl_error"
    RETURN_CODE = "return_code"
    UTILITY = "utility"
    SYSTEM_MESSAGE = "system_message"


class ErrorSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DetectedError(BaseModel):
    code: str
    category: str
    severity: str
    message: str
    source_line: int
    evidence: Optional[str] = None
    step_name: Optional[str] = None
    job_name: Optional[str] = None
    reason_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "source_line": self.source_line,
            "evidence": self.evidence,
            "step_name": self.step_name,
            "job_name": self.job_name,
            "reason_code": self.reason_code,
        }


class RelatedJclLine(BaseModel):
    line_number: int
    statement_type: str
    content: str
    relevance: str


class ExplainErrorRequest(BaseModel):
    log_text: str = Field(min_length=1, max_length=100000)
    jcl: Optional[str] = Field(default=None, max_length=100000)
    provider: Optional[Literal["openai", "gemini"]] = None
    model: Optional[str] = None
    use_ai: bool = True


class ExplainErrorResponse(BaseModel):
    detected_errors: List[DetectedError] = Field(default_factory=list)
    summary: str
    likely_causes: List[str] = Field(default_factory=list)
    troubleshooting_steps: List[str] = Field(default_factory=list)
    related_jcl_lines: List[RelatedJclLine] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    ai_used: bool = False
    confidence_notes: Optional[str] = None
    usage: Optional[TokenUsage] = None
    provider: Optional[str] = None
    model: Optional[str] = None

    def to_api_response(self) -> Dict[str, Any]:
        return {
            "detected_errors": [e.to_dict() for e in self.detected_errors],
            "summary": self.summary,
            "likely_causes": self.likely_causes,
            "troubleshooting_steps": self.troubleshooting_steps,
            "related_jcl_lines": [l.model_dump() for l in self.related_jcl_lines],
            "limitations": self.limitations,
            "ai_used": self.ai_used,
            "confidence_notes": self.confidence_notes,
            "usage": self.usage.model_dump() if self.usage else None,
            "provider": self.provider,
            "model": self.model,
        }

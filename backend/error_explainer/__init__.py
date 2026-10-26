"""Public exports for JCL Error Explainer engine."""

from backend.error_explainer.analyzer import analyze_log
from backend.error_explainer.knowledge_base import KNOWLEDGE_BASE, lookup_error_knowledge
from backend.error_explainer.models import (
    DetectedError,
    ErrorCategory,
    ErrorSeverity,
    ExplainErrorRequest,
    ExplainErrorResponse,
    RelatedJclLine,
)
from backend.error_explainer.service import (
    explain_error_service,
    explain_error_with_gemini,
    explain_error_with_openai,
)

__all__ = [
    "DetectedError",
    "ErrorCategory",
    "ErrorSeverity",
    "ExplainErrorRequest",
    "ExplainErrorResponse",
    "RelatedJclLine",
    "analyze_log",
    "explain_error_service",
    "explain_error_with_openai",
    "explain_error_with_gemini",
    "KNOWLEDGE_BASE",
    "lookup_error_knowledge",
]

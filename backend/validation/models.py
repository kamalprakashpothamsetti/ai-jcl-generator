"""Diagnostic and validation data models for the JCL Static Validation Engine."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Diagnostic(BaseModel):
    severity: Severity
    rule_id: str
    line: int
    column: Optional[int] = None
    message: str
    suggested_fix: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "rule_id": self.rule_id,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
        }


class ValidationCounts(BaseModel):
    errors: int = 0
    warnings: int = 0
    info: int = 0
    total: int = 0


class ValidationResult(BaseModel):
    valid: bool
    validation_level: str = "static"
    executable_verified: bool = False
    diagnostics: List[Diagnostic] = Field(default_factory=list)
    counts: ValidationCounts = Field(default_factory=ValidationCounts)
    disclaimer: str = (
        "Static JCL validation checks syntax, structure, parameters, and utility rules. "
        "It does NOT guarantee z/OS JES execution success or live catalog resource availability."
    )

    def to_api_response(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "validation_level": self.validation_level,
            "executable_verified": self.executable_verified,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "counts": self.counts.model_dump(),
            "disclaimer": self.disclaimer,
        }

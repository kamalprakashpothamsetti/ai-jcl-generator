"""Backward-compatible facade bridging jcl_validator imports to backend.validation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from backend.validation.models import Severity as NewSeverity
from backend.validation.validator import (
    JclStaticValidator,
    validate_jcl,
    validate_jcl_detailed,
    validate_jcl_full,
)

# Compatibility aliases
Severity = NewSeverity


class ValidationIssue:
    def __init__(
        self,
        line_number: Optional[int],
        severity: Any,
        category: str,
        message: str,
        rule_id: str,
    ):
        self.line_number = line_number
        self.severity = severity
        self.category = category
        self.message = message
        self.rule_id = rule_id

    def to_dict(self) -> Dict[str, Any]:
        sev_val = self.severity.value if hasattr(self.severity, "value") else str(self.severity)
        return {
            "line_number": self.line_number,
            "severity": sev_val,
            "category": self.category,
            "message": self.message,
            "rule_id": self.rule_id,
        }


class JclValidator:
    """Compatibility adapter matching legacy JclValidator interface."""

    def __init__(self, jcl: str):
        self.jcl = jcl
        self._validator = JclStaticValidator(jcl)

    def validate(self) -> List[ValidationIssue]:
        res = self._validator.validate()
        return [
            ValidationIssue(
                line_number=d.line,
                severity=d.severity,
                category=d.rule_id,
                message=d.message,
                rule_id=d.rule_id,
            )
            for d in res.diagnostics
        ]


__all__ = [
    "Severity",
    "ValidationIssue",
    "JclValidator",
    "validate_jcl",
    "validate_jcl_detailed",
    "validate_jcl_full",
]

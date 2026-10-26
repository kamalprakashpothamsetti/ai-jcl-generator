"""JCL Static Validation Engine Orchestration.

Coordinates:
- Parser (physical line, logical statement, continuation, and in-stream data parsing)
- General JCL rules (JOB/EXEC presence, duplicate step/DD names, DISP, SPACE, DCB, DSN)
- Utility-specific rules (IEFBR14, IEBGENER, DFSORT, IDCAMS)
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.validation.models import (
    Diagnostic,
    Severity,
    ValidationCounts,
    ValidationResult,
)
from backend.validation.parser import parse_jcl_structure
from backend.validation.rules import validate_general_jcl_rules
from backend.validation.utilities import validate_utility_specific_rules


class JclStaticValidator:
    """Orchestrates comprehensive static validation of IBM z/OS JCL streams."""

    def __init__(self, jcl: str):
        self.jcl = jcl

    def validate(self) -> ValidationResult:
        if not self.jcl or not self.jcl.strip():
            empty_diags = [
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="NO_JOB_STATEMENT",
                    line=1,
                    column=1,
                    message="No JOB statement detected.",
                    suggested_fix="Add a JOB card at the beginning of the JCL.",
                ),
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="NO_EXEC_STATEMENT",
                    line=1,
                    column=1,
                    message="No EXEC statement detected.",
                    suggested_fix="Add at least one EXEC statement defining a step.",
                ),
            ]
            return ValidationResult(
                valid=False,
                validation_level="static",
                executable_verified=False,
                diagnostics=empty_diags,
                counts=ValidationCounts(errors=2, warnings=0, info=0, total=2),
            )

        # 1. Parse physical lines and logical statements
        parsed = parse_jcl_structure(self.jcl)
        diagnostics: List[Diagnostic] = list(parsed.diagnostics)

        # 2. General JCL structural and dataset parameter rules
        general_diags = validate_general_jcl_rules(parsed)
        diagnostics.extend(general_diags)

        # 3. Utility-specific rules (IEFBR14, IEBGENER, DFSORT, IDCAMS)
        util_diags = validate_utility_specific_rules(parsed)
        diagnostics.extend(util_diags)

        # Sort diagnostics by line number (None / 0 at start)
        diagnostics.sort(key=lambda d: d.line or 0)

        # Compute counts
        err_count = sum(1 for d in diagnostics if d.severity == Severity.ERROR)
        warn_count = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
        info_count = sum(1 for d in diagnostics if d.severity == Severity.INFO)

        # JCL is syntactically valid if there are 0 errors
        is_valid = (err_count == 0)

        return ValidationResult(
            valid=is_valid,
            validation_level="static",
            executable_verified=False,
            diagnostics=diagnostics,
            counts=ValidationCounts(
                errors=err_count,
                warnings=warn_count,
                info=info_count,
                total=len(diagnostics),
            ),
        )


def validate_jcl_full(jcl: str) -> ValidationResult:
    """Runs complete static JCL validation and returns structured ValidationResult."""
    validator = JclStaticValidator(jcl)
    return validator.validate()


def validate_jcl(jcl: str) -> List[str]:
    """Backward-compatible helper returning list of error and warning message strings."""
    result = validate_jcl_full(jcl)
    return [d.message for d in result.diagnostics if d.severity in (Severity.ERROR, Severity.WARNING)]


def validate_jcl_detailed(jcl: str) -> Dict[str, Any]:
    """Backward-compatible helper matching previous validate_jcl_detailed dictionary response."""
    result = validate_jcl_full(jcl)
    # Passed basic checks if 0 errors and 0 warnings (matching previous logic)
    passed_basic = (result.counts.errors == 0 and result.counts.warnings == 0)
    return {
        "passed_basic_checks": passed_basic,
        "warnings": [d.message for d in result.diagnostics if d.severity in (Severity.ERROR, Severity.WARNING)],
        "issues": [
            {
                "line_number": d.line,
                "severity": d.severity.value.upper(),
                "category": d.rule_id,
                "message": d.message,
                "rule_id": d.rule_id,
            }
            for d in result.diagnostics
        ],
        "summary": {
            "errors": result.counts.errors,
            "warnings": result.counts.warnings,
            "info": result.counts.info,
            "total": result.counts.total,
        },
        "disclaimer": result.disclaimer,
    }

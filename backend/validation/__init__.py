"""Backend validation package public exports."""

from backend.validation.models import (
    Diagnostic,
    Severity,
    ValidationCounts,
    ValidationResult,
)
from backend.validation.parser import LogicalStatement, ParsedJcl, parse_jcl_structure
from backend.validation.registry import (
    ProgramRegistry,
    default_registry,
    find_close_program_match,
    get_canonical_utility,
    is_known_program,
    is_known_utility,
    register_user_program,
    reset_registry,
    unregister_user_program,
)
from backend.validation.validator import (
    JclStaticValidator,
    validate_jcl,
    validate_jcl_detailed,
    validate_jcl_full,
)

__all__ = [
    "Diagnostic",
    "Severity",
    "ValidationCounts",
    "ValidationResult",
    "LogicalStatement",
    "ParsedJcl",
    "parse_jcl_structure",
    "ProgramRegistry",
    "default_registry",
    "find_close_program_match",
    "get_canonical_utility",
    "is_known_program",
    "is_known_utility",
    "register_user_program",
    "unregister_user_program",
    "reset_registry",
    "JclStaticValidator",
    "validate_jcl",
    "validate_jcl_detailed",
    "validate_jcl_full",
]

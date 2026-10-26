from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from jcl_builder import (
    DdStatement,
    JclStep,
    JobCard,
    ManualBuildRequest,
    format_manual_jcl,
    get_preset_templates,
)
from backend.diff_engine import DiffLine, generate_structured_diff
from backend.error_explainer import (
    ExplainErrorRequest,
    ExplainErrorResponse,
    explain_error_service,
    explain_error_with_gemini,
    explain_error_with_openai,
)
from backend.security import (
    get_configured_access_key,
    rate_limiter,
    spend_tracker,
    verify_ai_access_key,
)
from jcl_validator import validate_jcl, validate_jcl_detailed, validate_jcl_full
from llm_provider import (
    SYSTEM_INSTRUCTION,
    JclChangeItem,
    JclModifyResult,
    TokenUsage,
    estimate_openai_cost,
    generate_with_gemini_provider,
    generate_with_openai_provider,
    modify_with_gemini_provider,
    modify_with_openai_provider,
)

load_dotenv()
ROOT = Path(__file__).resolve().parent

is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"
docs_enabled = os.getenv("DOCS_ENABLED", "true" if not is_production else "false").lower() == "true"

app = FastAPI(
    title="JCL Studio AI",
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

# Cross-Origin Resource Sharing (CORS) Configuration
raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "https://kamalprakashpothamsetti.github.io,https://pkama.github.io,http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000",
)
allowed_origins = [o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=4000)
    utility: Literal["AUTO", "IEFBR14", "IEBGENER", "DFSORT", "IDCAMS"] = "AUTO"
    provider: Optional[Literal["openai", "gemini"]] = None
    model: Optional[str] = None


class GenerateResponse(BaseModel):
    jcl: str
    explanation: list[str]
    assumptions: list[str]
    warnings: list[str]
    usage: Optional[TokenUsage] = None
    provider: str = "openai"
    model: str = "gpt-5.4-mini"


class ValidateRequest(BaseModel):
    jcl: str = Field(min_length=0, max_length=100000)


class ValidateResponse(BaseModel):
    warnings: list[str]
    passed_basic_checks: bool
    issues: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    valid: bool = True
    validation_level: str = "static"
    executable_verified: bool = False
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    disclaimer: str = (
        "Illustrative static analysis only - syntax check does not guarantee z/OS execution."
    )


class JclValidateResponse(BaseModel):
    valid: bool
    validation_level: str = "static"
    executable_verified: bool = False
    diagnostics: list[dict[str, Any]]
    counts: dict[str, int]
    disclaimer: str


class ManualBuildResponse(BaseModel):
    jcl: str
    warnings: list[str]
    passed_basic_checks: bool
    issues: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    disclaimer: str = (
        "Illustrative manual JCL generation - must be validated in an actual z/OS test environment."
    )


class JclModifyRequest(BaseModel):
    jcl: str = Field(min_length=1, max_length=100000)
    instruction: str = Field(min_length=3, max_length=4000)
    provider: Optional[Literal["openai", "gemini"]] = None
    model: Optional[str] = None


class JclChange(BaseModel):
    type: str = "modified"  # modified, added, removed
    description: str


class DiffLineModel(BaseModel):
    line_orig: Optional[int] = None
    line_mod: Optional[int] = None
    type: str  # added, removed, modified, unchanged
    content: str


class JclModifyResponse(BaseModel):
    original_jcl: str
    modified_jcl: str
    summary: str
    changes: List[JclChange] = Field(default_factory=list)
    diff_lines: List[DiffLineModel] = Field(default_factory=list)
    validation: Dict[str, Any]
    original_validation: Dict[str, Any]
    new_errors_introduced: bool = False
    assumptions: List[str] = Field(default_factory=list)
    clarifications: List[str] = Field(default_factory=list)
    usage: Optional[TokenUsage] = None
    provider: str = "openai"
    model: str = "gpt-5.4-mini"


def generate_with_openai(request: GenerateRequest) -> GenerateResponse:
    """Generate JCL using OpenAI Responses API."""
    res = generate_with_openai_provider(
        prompt=request.prompt,
        utility=request.utility,
        model=request.model or os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
    )
    return GenerateResponse(
        jcl=res.jcl,
        explanation=res.explanation,
        assumptions=res.assumptions,
        warnings=res.warnings,
        usage=res.usage,
        provider="openai",
        model=res.model,
    )


def generate_with_gemini(request: GenerateRequest) -> GenerateResponse:
    """Generate JCL using Google GenAI SDK."""
    res = generate_with_gemini_provider(
        prompt=request.prompt,
        utility=request.utility,
        model=request.model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    )
    return GenerateResponse(
        jcl=res.jcl,
        explanation=res.explanation,
        assumptions=res.assumptions,
        warnings=res.warnings,
        usage=res.usage,
        provider="gemini",
        model=res.model,
    )


def modify_with_openai(request: JclModifyRequest) -> JclModifyResult:
    """Modify JCL using OpenAI Responses API."""
    return modify_with_openai_provider(
        jcl=request.jcl,
        instruction=request.instruction,
        model=request.model or os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
    )


def modify_with_gemini(request: JclModifyRequest) -> JclModifyResult:
    """Modify JCL using Google GenAI SDK."""
    return modify_with_gemini_provider(
        jcl=request.jcl,
        instruction=request.instruction,
        model=request.model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    )


# Keep reference to originals to allow transparent monkeypatch detection in existing unit tests
_ORIGINAL_GEMINI_FN = generate_with_gemini
_ORIGINAL_OPENAI_FN = generate_with_openai
_ORIGINAL_MODIFY_GEMINI_FN = modify_with_gemini
_ORIGINAL_MODIFY_OPENAI_FN = modify_with_openai


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "jcl-studio-ai",
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
def get_config():
    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    return {
        "provider": provider,
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "auth_required": bool(get_configured_access_key()),
    }


@app.post("/api/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest, raw_request: Request):
    rate_limiter.check_rate_limit(raw_request)
    verify_ai_access_key(raw_request)
    spend_tracker.check_limit_before_call()
    # Determine provider: request param > monkeypatch compatibility > LLM_PROVIDER env > default 'openai'
    if request.provider:
        provider = request.provider.lower().strip()
    elif generate_with_gemini is not _ORIGINAL_GEMINI_FN and generate_with_openai is _ORIGINAL_OPENAI_FN:
        # Backward-compatibility for unit tests monkeypatching generate_with_gemini
        provider = "gemini"
    else:
        provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()

    try:
        if provider == "gemini":
            result = generate_with_gemini(request)
        else:
            result = generate_with_openai(request)
    except HTTPException:
        raise
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc)

        # 1. Missing API Key
        if "is not configured" in err_msg or "No API key was provided" in err_msg:
            raise HTTPException(status_code=503, detail=err_msg) from exc

        # 2. OpenAI & LLM Provider Specific Exceptions
        if "RateLimitError" in err_type or "RateLimit" in err_msg or "insufficient_quota" in err_msg:
            raise HTTPException(
                status_code=429,
                detail="OpenAI rate limit or quota exceeded. Please verify account limits."
            ) from exc
        elif "AuthenticationError" in err_type or "Authentication" in err_msg or "Incorrect API key" in err_msg:
            raise HTTPException(
                status_code=401,
                detail="OpenAI authentication failed. Invalid API key configured."
            ) from exc
        elif "APITimeoutError" in err_type or "Timeout" in err_type or "timed out" in err_msg.lower():
            raise HTTPException(
                status_code=504,
                detail="Request to LLM provider timed out. Please retry."
            ) from exc
        elif "APIConnectionError" in err_type or "connection" in err_msg.lower():
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to LLM provider. Please check network connectivity."
            ) from exc
        elif "BadRequestError" in err_type:
            raise HTTPException(
                status_code=400,
                detail="Invalid request parameters sent to LLM provider."
            ) from exc

        # Default 502 for provider failures
        raise HTTPException(
            status_code=502,
            detail=f"{provider.capitalize()} generation failed. Check backend logs and configuration."
        ) from exc

    # Static linting and warning deduplication
    static_warnings = validate_jcl(result.jcl)
    existing_set = set(result.warnings)
    for warn in static_warnings:
        if warn not in existing_set:
            result.warnings.append(warn)
            existing_set.add(warn)

    # Track spend if cost available
    if result.usage and result.usage.estimated_cost_usd:
        spend_tracker.record_cost(result.usage.estimated_cost_usd)

    return result


@app.post("/api/validate", response_model=ValidateResponse)
def validate(request: ValidateRequest):
    res = validate_jcl_full(request.jcl)
    detailed = validate_jcl_detailed(request.jcl)
    return ValidateResponse(
        warnings=detailed["warnings"],
        passed_basic_checks=detailed["passed_basic_checks"],
        issues=detailed["issues"],
        summary=detailed["summary"],
        valid=res.valid,
        validation_level=res.validation_level,
        executable_verified=res.executable_verified,
        diagnostics=[d.to_dict() for d in res.diagnostics],
        counts=res.counts.model_dump(),
        disclaimer=detailed["disclaimer"],
    )


@app.post("/api/jcl/validate", response_model=JclValidateResponse)
def validate_jcl_api(request: ValidateRequest, raw_request: Request):
    rate_limiter.check_rate_limit(raw_request)
    res = validate_jcl_full(request.jcl)
    return JclValidateResponse(
        valid=res.valid,
        validation_level=res.validation_level,
        executable_verified=res.executable_verified,
        diagnostics=[d.to_dict() for d in res.diagnostics],
        counts=res.counts.model_dump(),
        disclaimer=res.disclaimer,
    )


@app.post("/api/build", response_model=ManualBuildResponse)
def build_manual(request: ManualBuildRequest):
    jcl = format_manual_jcl(request)
    detailed = validate_jcl_detailed(jcl)
    return ManualBuildResponse(
        jcl=jcl,
        warnings=detailed["warnings"],
        passed_basic_checks=detailed["passed_basic_checks"],
        issues=detailed["issues"],
        summary=detailed["summary"],
        disclaimer=detailed["disclaimer"],
    )


@app.get("/api/templates")
def list_templates():
    return get_preset_templates()


@app.post("/api/jcl/modify", response_model=JclModifyResponse)
def modify_jcl_api(request: JclModifyRequest, raw_request: Request):
    rate_limiter.check_rate_limit(raw_request)
    verify_ai_access_key(raw_request)
    spend_tracker.check_limit_before_call()

    if not request.jcl.strip():
        raise HTTPException(status_code=400, detail="JCL content cannot be empty.")
    if len(request.instruction.strip()) < 3:
        raise HTTPException(status_code=422, detail="Modification instruction must be at least 3 characters.")

    if request.provider:
        provider = request.provider.lower().strip()
    elif modify_with_gemini is not _ORIGINAL_MODIFY_GEMINI_FN and modify_with_openai is _ORIGINAL_MODIFY_OPENAI_FN:
        provider = "gemini"
    else:
        provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()

    try:
        if provider == "gemini":
            result = modify_with_gemini(request)
        else:
            result = modify_with_openai(request)
    except HTTPException:
        raise
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc)

        # 1. Missing API Key
        if "is not configured" in err_msg or "No API key was provided" in err_msg:
            raise HTTPException(status_code=503, detail=err_msg) from exc

        # 2. OpenAI & LLM Provider Specific Exceptions
        if "RateLimitError" in err_type or "RateLimit" in err_msg or "insufficient_quota" in err_msg:
            raise HTTPException(
                status_code=429,
                detail="OpenAI rate limit or quota exceeded. Please verify account limits."
            ) from exc
        elif "AuthenticationError" in err_type or "Authentication" in err_msg or "Incorrect API key" in err_msg:
            raise HTTPException(
                status_code=401,
                detail="OpenAI authentication failed. Invalid API key configured."
            ) from exc
        elif "APITimeoutError" in err_type or "Timeout" in err_type or "timed out" in err_msg.lower():
            raise HTTPException(
                status_code=504,
                detail="Request to LLM provider timed out. Please retry."
            ) from exc
        elif "APIConnectionError" in err_type or "connection" in err_msg.lower():
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to LLM provider. Please check network connectivity."
            ) from exc
        elif "BadRequestError" in err_type:
            raise HTTPException(
                status_code=400,
                detail="Invalid request parameters sent to LLM provider."
            ) from exc

        # Default 502 for provider failures
        raise HTTPException(
            status_code=502,
            detail=f"{provider.capitalize()} modification failed. Check backend logs and configuration."
        ) from exc

    # Generate server-side diff using difflib
    diff_lines = generate_structured_diff(request.jcl, result.modified_jcl)

    # Validate both original and modified JCL
    orig_val = validate_jcl_full(request.jcl)
    mod_val = validate_jcl_full(result.modified_jcl)

    orig_error_rules = {d.rule_id for d in orig_val.diagnostics if d.severity.value == "error"}
    mod_error_rules = {d.rule_id for d in mod_val.diagnostics if d.severity.value == "error"}
    new_errors_introduced = bool(mod_val.counts.errors > orig_val.counts.errors or (mod_error_rules - orig_error_rules))

    changes = result.changes
    if not changes:
        added_count = sum(1 for d in diff_lines if d.type == "added")
        removed_count = sum(1 for d in diff_lines if d.type == "removed")
        changes = [
            JclChangeItem(type="modified", description=f"Updated JCL ({added_count} additions, {removed_count} deletions)")
        ]

    # Track spend if cost available
    if result.usage and result.usage.estimated_cost_usd:
        spend_tracker.record_cost(result.usage.estimated_cost_usd)

    return JclModifyResponse(
        original_jcl=request.jcl,
        modified_jcl=result.modified_jcl,
        summary=result.summary or "Applied requested JCL modifications.",
        changes=[JclChange(type=c.type, description=c.description) for c in changes],
        diff_lines=[DiffLineModel(**d.model_dump()) for d in diff_lines],
        validation={
            "valid": mod_val.valid,
            "validation_level": mod_val.validation_level,
            "executable_verified": mod_val.executable_verified,
            "diagnostics": [d.to_dict() for d in mod_val.diagnostics],
            "counts": mod_val.counts.model_dump(),
            "disclaimer": mod_val.disclaimer,
        },
        original_validation={
            "valid": orig_val.valid,
            "counts": orig_val.counts.model_dump(),
        },
        new_errors_introduced=new_errors_introduced,
        assumptions=result.assumptions,
        clarifications=result.clarifications,
        usage=result.usage,
        provider=provider,
        model=result.model,
    )


@app.post("/api/jcl/explain-error", response_model=ExplainErrorResponse)
def explain_jcl_error_api(request: ExplainErrorRequest, raw_request: Request):
    """Diagnoses JES job logs, abends, and JCL errors with deterministic rules and optional AI explanation."""
    rate_limiter.check_rate_limit(raw_request)
    if request.use_ai:
        verify_ai_access_key(raw_request)
        spend_tracker.check_limit_before_call()

    if not request.log_text or not request.log_text.strip():
        raise HTTPException(status_code=400, detail="Log text cannot be empty.")
    if len(request.log_text) > 100000:
        raise HTTPException(status_code=400, detail="Log text exceeds maximum allowed size of 100,000 characters.")
    if request.jcl and len(request.jcl) > 100000:
        raise HTTPException(status_code=400, detail="JCL text exceeds maximum allowed size of 100,000 characters.")

    provider = request.provider or os.getenv("LLM_PROVIDER", "openai").lower().strip()

    try:
        res = explain_error_service(request)
        if res.usage and res.usage.estimated_cost_usd:
            spend_tracker.record_cost(res.usage.estimated_cost_usd)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except HTTPException:
        raise
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc)

        # 1. Missing API Key
        if "is not configured" in err_msg or "No API key was provided" in err_msg:
            raise HTTPException(status_code=503, detail=err_msg) from exc

        # 2. OpenAI / LLM Provider Specific Exceptions
        if "RateLimitError" in err_type or "RateLimit" in err_msg or "insufficient_quota" in err_msg:
            raise HTTPException(
                status_code=429,
                detail="OpenAI rate limit or quota exceeded. Please verify account limits."
            ) from exc
        elif "AuthenticationError" in err_type or "Authentication" in err_msg or "Incorrect API key" in err_msg:
            raise HTTPException(
                status_code=401,
                detail="OpenAI authentication failed. Invalid API key configured."
            ) from exc
        elif "APITimeoutError" in err_type or "Timeout" in err_type or "timed out" in err_msg.lower():
            raise HTTPException(
                status_code=504,
                detail="Request to LLM provider timed out. Please retry."
            ) from exc
        elif "APIConnectionError" in err_type or "connection" in err_msg.lower():
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to LLM provider. Please check network connectivity."
            ) from exc
        elif "BadRequestError" in err_type:
            raise HTTPException(
                status_code=400,
                detail="Invalid request parameters sent to LLM provider."
            ) from exc

        # Default 502 for provider failures
        raise HTTPException(
            status_code=502,
            detail=f"{provider.capitalize()} error explanation failed. Check backend logs and configuration."
        ) from exc


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)



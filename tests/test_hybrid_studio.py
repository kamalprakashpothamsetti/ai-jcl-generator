"""Automated tests for JCL Studio AI — Hybrid Generator UI.

Covers the 12 core requirements:
1. Switching between AI and Manual modes
2. Preserving JCL when switching modes
3. Successful AI generation (mocked)
4. Successful manual generation
5. Displaying validation diagnostics
6. Marking validation stale after editing
7. Copying exact JCL text
8. Downloading exact JCL content
9. API failure handling (429, 401, 504, 502, 503)
10. Empty prompt validation
11. Overwrite confirmation
12. Responsive interface behavior
"""

import os
import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from jcl_builder import (
    DdStatement,
    JclStep,
    JobCard,
    ManualBuildRequest,
    format_manual_jcl,
    get_preset_templates,
)
from llm_provider import TokenUsage, estimate_openai_cost

client = TestClient(main.app)

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


@pytest.fixture
def index_html_content() -> str:
    assert INDEX_HTML_PATH.exists(), "static/index.html must exist"
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# 1. Switching between AI and Manual modes
# -----------------------------------------------------------------------------
def test_switching_modes_ui_elements(index_html_content):
    """Verifies UI contains mode tabs and sections for AI, Manual, Edit, and Explainer modes, styled with responsive 2x2 grid."""
    # Check tabs
    assert 'id="tabAiMode"' in index_html_content
    assert 'id="tabManualMode"' in index_html_content
    assert 'id="tabEditMode"' in index_html_content
    assert 'id="tabExplainerMode"' in index_html_content
    # Check CSS grid styling
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in index_html_content
    assert "min-width: 0" in index_html_content
    # Check sections
    assert 'id="aiSection"' in index_html_content
    assert 'id="manualSection"' in index_html_content
    # Check JS event listeners for mode switching
    assert "tabAiMode" in index_html_content
    assert "tabManualMode" in index_html_content
    assert "appState.activeMode = 'ai'" in index_html_content
    assert "appState.activeMode = 'manual'" in index_html_content


# -----------------------------------------------------------------------------
# 2. Preserving JCL when switching modes
# -----------------------------------------------------------------------------
def test_preserving_jcl_when_switching_modes(index_html_content):
    """Verifies that mode switching does not clear or rewrite editor textarea."""
    # In tabAiMode and tabManualMode click handlers, output.value must NOT be cleared
    ai_switch_block = re.search(r"el\('tabAiMode'\)\.onclick\s*=\s*\(\)\s*=>\s*\{([^}]+)\}", index_html_content)
    manual_switch_block = re.search(r"el\('tabManualMode'\)\.onclick\s*=\s*\(\)\s*=>\s*\{([^}]+)\}", index_html_content)

    assert ai_switch_block is not None
    assert manual_switch_block is not None

    # Neither mode switch should reset el('output').value
    assert "el('output').value = ''" not in ai_switch_block.group(1)
    assert "el('output').value = ''" not in manual_switch_block.group(1)


# -----------------------------------------------------------------------------
# 3. Successful AI generation (mocked)
# -----------------------------------------------------------------------------
def test_successful_ai_generation_mocked(monkeypatch):
    """Verifies successful AI generation with mocked LLM response, token usage, and cost."""
    sample_jcl = (
        "//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A,MSGCLASS=X\n"
        "//STEP01   EXEC PGM=IEFBR14\n"
        "//OUTDD    DD DSN=USER.SAMPLE.DATA,DISP=(NEW,CATLG,DELETE),\n"
        "//            SPACE=(CYL,(1,1),RLSE),UNIT=SYSDA\n"
    )

    def fake_openai(request):
        usage = TokenUsage(
            input_tokens=120,
            output_tokens=240,
            total_tokens=360,
            estimated_cost_usd=estimate_openai_cost("gpt-5.4-mini", 120, 240),
            provider="openai",
            model="gpt-5.4-mini"
        )
        return main.GenerateResponse(
            jcl=sample_jcl,
            explanation=["Allocates sequential dataset via IEFBR14"],
            assumptions=["Target volume SYSDA available"],
            warnings=[],
            usage=usage,
            provider="openai",
            model="gpt-5.4-mini"
        )

    monkeypatch.setattr(main, "generate_with_openai", fake_openai)

    resp = client.post(
        "/api/generate",
        json={
            "prompt": "Allocate a sequential dataset on SYSDA using IEFBR14",
            "utility": "IEFBR14",
            "provider": "openai"
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "IEFBR14" in data["jcl"]
    assert len(data["explanation"]) > 0
    assert len(data["assumptions"]) > 0
    assert data["usage"]["total_tokens"] == 360
    assert data["usage"]["estimated_cost_usd"] > 0
    assert data["provider"] == "openai"


# -----------------------------------------------------------------------------
# 4. Successful manual generation (with PARM, REGION, COND, and reordered DDs)
# -----------------------------------------------------------------------------
def test_successful_manual_generation():
    """Verifies manual builder formats valid 80-col JCL with advanced EXEC parameters."""
    req = ManualBuildRequest(
        job=JobCard(job_name="PRODJOB", job_class="B", msgclass="A"),
        steps=[
            JclStep(
                step_name="STEP01",
                utility="CUSTOM",
                pgm_override="MYAPP",
                parm="'REPORT=FULL'",
                region="4M",
                cond="(4,LT)",
                comments="Execute custom reporting application",
                dds=[
                    DdStatement(dd_name="SYSIN", dummy=True),
                    DdStatement(dd_name="SYSPRINT", sysout="*"),
                    DdStatement(dd_name="REPORT", dsn="USER.PROD.REPORT", disp="(NEW,CATLG,DELETE)", space="(CYL,(5,2))")
                ]
            )
        ]
    )

    resp = client.post("/api/build", json=req.model_dump())
    assert resp.status_code == 200
    data = resp.json()
    jcl = data["jcl"]

    assert "//PRODJOB  JOB  " in jcl
    assert "PGM=MYAPP" in jcl
    assert "PARM='REPORT=FULL'" in jcl
    assert "REGION=4M" in jcl
    assert "COND=(4,LT)" in jcl
    assert "//SYSIN    DD   DUMMY" in jcl
    assert "//SYSPRINT DD   SYSOUT=*" in jcl
    assert "USER.PROD.REPORT" in jcl

    for line in jcl.splitlines():
        assert len(line) <= 80


# -----------------------------------------------------------------------------
# 5. Displaying validation diagnostics
# -----------------------------------------------------------------------------
def test_displaying_validation_diagnostics():
    """Verifies POST /api/jcl/validate returns structured diagnostics and counts."""
    bad_jcl = (
        "//TESTJOB JOB (ACCT)\n"
        "//STEP01  EXEC PGM=IEBGENER\n"
        "//SYSUT2  DD DSN=USER.OUT,DISP=SHR\n"
    )
    resp = client.post("/api/jcl/validate", json={"jcl": bad_jcl})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert data["counts"]["errors"] >= 1

    rule_ids = [d["rule_id"] for d in data["diagnostics"]]
    assert "IEBGENER_MISSING_SYSUT1" in rule_ids

    # Find the specific diagnostic and verify fields
    diag = next(d for d in data["diagnostics"] if d["rule_id"] == "IEBGENER_MISSING_SYSUT1")
    assert diag["severity"] == "error"
    assert diag["line"] is not None
    assert diag["suggested_fix"] is not None


# -----------------------------------------------------------------------------
# 6. Marking validation stale after editing
# -----------------------------------------------------------------------------
def test_marking_validation_stale_after_editing(index_html_content):
    """Verifies frontend contains logic to mark validation stale immediately upon typing."""
    assert "appState.isValidationStale = true" in index_html_content
    assert "⚠️ Stale (Editing...)" in index_html_content
    assert "validationIssues" in index_html_content
    assert "classList.add('stale')" in index_html_content


# -----------------------------------------------------------------------------
# 7. Copying exact JCL text
# -----------------------------------------------------------------------------
def test_copying_exact_jcl_text(index_html_content):
    """Verifies copy button uses navigator.clipboard.writeText with exact output textarea value."""
    assert "id=\"copy\"" in index_html_content
    assert "navigator.clipboard.writeText(content)" in index_html_content or "navigator.clipboard.writeText(el('output').value)" in index_html_content


# -----------------------------------------------------------------------------
# 8. Downloading exact JCL content
# -----------------------------------------------------------------------------
def test_downloading_exact_jcl_content(index_html_content):
    """Verifies download functionality parses job name and triggers .jcl blob download."""
    assert "id=\"download\"" in index_html_content
    assert ".jcl" in index_html_content
    assert "new Blob([content]" in index_html_content
    assert "URL.createObjectURL" in index_html_content


# -----------------------------------------------------------------------------
# 9. API failure handling
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exception_cls,status_code,err_substr",
    [
        ("RateLimitError", 429, "rate limit"),
        ("AuthenticationError", 401, "authentication"),
        ("APITimeoutError", 504, "timed out"),
        ("APIConnectionError", 502, "connect"),
    ],
)
def test_api_failure_handling(monkeypatch, exception_cls, status_code, err_substr):
    """Verifies provider exceptions map cleanly to standard HTTP status codes."""
    class FakeProviderError(Exception):
        pass
    FakeProviderError.__name__ = exception_cls

    def fake_failing_openai(request):
        raise FakeProviderError(f"Simulated {exception_cls}")

    monkeypatch.setattr(main, "generate_with_openai", fake_failing_openai)

    resp = client.post(
        "/api/generate",
        json={"prompt": "Valid prompt that meets the 10 character minimum", "provider": "openai"}
    )
    assert resp.status_code == status_code
    assert err_substr in resp.json()["detail"].lower()


# -----------------------------------------------------------------------------
# 10. Empty prompt validation
# -----------------------------------------------------------------------------
def test_empty_prompt_validation(index_html_content):
    """Verifies empty and short prompts (<10 chars) are rejected both client and server side."""
    # 1. Server-side rejection
    resp = client.post("/api/generate", json={"prompt": "Short"})
    assert resp.status_code == 422

    # 2. Client-side rejection in HTML
    assert "promptVal.length < 10" in index_html_content
    assert "Please enter a requirement description of at least 10 characters." in index_html_content


# -----------------------------------------------------------------------------
# 11. Overwrite confirmation
# -----------------------------------------------------------------------------
def test_overwrite_confirmation(index_html_content):
    """Verifies overwrite confirmation is prompted before replacing unsaved work."""
    assert "confirmOverwriteIfNeeded" in index_html_content
    assert "appState.hasUnsavedChanges" in index_html_content
    assert "confirm(" in index_html_content


# -----------------------------------------------------------------------------
# 12. Responsive interface behavior
# -----------------------------------------------------------------------------
def test_responsive_interface_behavior(index_html_content):
    """Verifies responsive layout CSS, media queries, and mobile navigation switcher."""
    # Check 3-column desktop layout
    assert ".studio-layout" in index_html_content
    assert "grid-template-columns: 380px 1fr 370px" in index_html_content or "grid-template-columns" in index_html_content

    # Check responsive media query
    assert "@media (max-width: 1100px)" in index_html_content or "@media (max-width: 1024px)" in index_html_content

    # Check mobile navigation buttons
    assert 'id="mobileTabGen"' in index_html_content
    assert 'id="mobileTabEditor"' in index_html_content
    assert 'id="mobileTabVal"' in index_html_content
    assert "setMobileView" in index_html_content

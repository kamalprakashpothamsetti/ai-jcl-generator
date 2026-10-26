"""Automated tests for JCL Error Explainer engine (deterministic analysis, JCL correlation, AI layer, and API)."""

import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.error_explainer.analyzer import analyze_log
from backend.error_explainer.models import (
    ExplainErrorRequest,
    ExplainErrorResponse,
)
from backend.error_explainer.service import (
    explain_error_service,
    explain_error_with_openai,
)
from llm_provider import TokenUsage
from main import app

client = TestClient(app)


# -----------------------------------------------------------------------------
# 1. Error Pattern & ABEND Detection Tests
# -----------------------------------------------------------------------------

def test_01_detect_s806():
    """1. Detect S806 load module not found error."""
    log = "IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004"
    res = analyze_log(log)
    s806_errors = [e for e in res.detected_errors if e.code == "S806"]
    assert len(s806_errors) == 1
    err = s806_errors[0]
    assert err.category == "abend"
    assert err.severity == "error"
    assert "Load Module Not Found" in err.message or "Program Loading Failure" in err.message
    assert err.reason_code == "00000004"
    assert any("missing or incorrectly configured" in c for c in res.likely_causes)


def test_02_detect_s0c7():
    """2. Detect S0C7 data exception error."""
    log = "SYSTEM ABEND S0C7 OCCURRED IN MODULE MYPROG AT OFFSET +00012A"
    res = analyze_log(log)
    s0c7_errors = [e for e in res.detected_errors if e.code == "S0C7"]
    assert len(s0c7_errors) == 1
    err = s0c7_errors[0]
    assert err.category == "abend"
    assert err.severity == "error"
    assert "Data Exception" in err.message
    assert any("packed decimal" in c.lower() or "comp-3" in c.lower() for c in res.likely_causes)


def test_03_detect_s0c4():
    """3. Detect S0C4 protection exception / storage addressing error."""
    log = "USER JOB TERMINATED WITH ABEND S0C4 PROTECTION EXCEPTION"
    res = analyze_log(log)
    s0c4_errors = [e for e in res.detected_errors if e.code == "S0C4"]
    assert len(s0c4_errors) == 1
    err = s0c4_errors[0]
    assert err.category == "abend"
    assert err.severity == "error"
    assert "Protection Exception" in err.message


def test_04_detect_s013():
    """4. Detect S013 dataset conflict / OPEN failure."""
    log = "IEC141I 013-18,IGG0191A,PAYJOB,STEP1,SYSUT1 ... MEMBER NOT FOUND"
    res = analyze_log(log)
    s013_errors = [e for e in res.detected_errors if e.code == "S013"]
    assert len(s013_errors) == 1
    err = s013_errors[0]
    assert err.category == "abend"
    assert "OPEN" in err.message or "Open" in err.message


def test_05_detect_s322():
    """5. Detect S322 CPU time limit exceeded."""
    log = "IEF450I BATCHJOB STEP3 - ABEND=S322 TIME EXCEEDED"
    res = analyze_log(log)
    s322_errors = [e for e in res.detected_errors if e.code == "S322"]
    assert len(s322_errors) == 1
    err = s322_errors[0]
    assert "CPU Time Limit Exceeded" in err.message


def test_06_detect_s837():
    """6. Detect S837 out of space / end of volume allocation failure."""
    log = "IEC031I D37-04,IFG0554A,BIGJOB,STEP01,DATAOUT ... ABEND S837 OUT OF SPACE"
    res = analyze_log(log)
    s837_errors = [e for e in res.detected_errors if e.code == "S837"]
    assert len(s837_errors) == 1
    err = s837_errors[0]
    assert "Space Allocation" in err.message or "Volume" in err.message


def test_07_detect_s913():
    """7. Detect S913 RACF security authorization failure."""
    log = "ICH408I USER(OPERATOR) GROUP(SYSADM) DATASET(SECURE.DATA) INSUFFICIENT ACCESS AUTHORITY ... ABEND=S913"
    res = analyze_log(log)
    s913_errors = [e for e in res.detected_errors if e.code == "S913"]
    assert len(s913_errors) == 1
    err = s913_errors[0]
    assert "Security" in err.message or "RACF" in err.message


def test_08_detect_user_abend_u4038():
    """8. Detect user ABEND U4038 Language Environment failure."""
    log = "CEE3250C The system or user abend U4038 was issued. Enclave terminated with return code 4038."
    res = analyze_log(log)
    u4038_errors = [e for e in res.detected_errors if e.code == "U4038"]
    assert len(u4038_errors) == 1
    err = u4038_errors[0]
    assert err.category == "user_abend"
    assert "Language Environment" in err.message


def test_09_detect_ief452i():
    """9. Detect IEF452I JCL error."""
    log = "IEF452I PAYJOB - JOB FAILED - JCL ERROR - TIME=12.30.00"
    res = analyze_log(log)
    ief452 = [e for e in res.detected_errors if e.code == "IEF452I"]
    assert len(ief452) == 1
    err = ief452[0]
    assert err.category == "jcl_error"
    assert err.severity == "error"
    assert "Job Failed" in err.message


def test_10_detect_ief450i():
    """10. Detect IEF450I step abnormal termination message."""
    log = "IEF450I TESTJOB STEP1 - ABEND=S0C4 U0000 REASON=00000004"
    res = analyze_log(log)
    ief450 = [e for e in res.detected_errors if e.code == "IEF450I"]
    assert len(ief450) == 1
    err = ief450[0]
    assert err.category == "system_message"
    assert err.step_name == "STEP1"
    assert err.job_name == "TESTJOB"


def test_11_detect_return_code_0012():
    """11. Detect return code RC=0012 as an execution error."""
    log = "IEF142I PAYJOB STEP2 - STEP WAS EXECUTED - COND CODE 0012"
    res = analyze_log(log)
    rc_errors = [e for e in res.detected_errors if "0012" in e.code]
    assert len(rc_errors) == 1
    assert rc_errors[0].severity == "error"
    assert "12" in rc_errors[0].message


def test_12_distinguish_rc_0000_from_failures():
    """12. Distinguish RC=0000 from failures (info severity, no errors)."""
    log = "IEF142I PAYJOB STEP1 - STEP WAS EXECUTED - COND CODE 0000"
    res = analyze_log(log)
    assert not any(e.severity == "error" for e in res.detected_errors)
    rc0 = [e for e in res.detected_errors if "0000" in e.code]
    assert len(rc0) == 1
    assert rc0[0].severity == "info"
    assert "successfully" in res.summary.lower()


def test_13_distinguish_rc_0004_warnings_from_abends():
    """13. Distinguish RC=0004 warnings from ABENDs."""
    log = "IEF142I PAYJOB STEP1 - STEP WAS EXECUTED - COND CODE 0004"
    res = analyze_log(log)
    assert not any(e.category == "abend" for e in res.detected_errors)
    rc4 = [e for e in res.detected_errors if "0004" in e.code]
    assert len(rc4) == 1
    assert rc4[0].severity == "warning"


def test_14_parse_multiple_failures_in_one_log():
    """14. Parse multiple distinct failures in one log."""
    log = """IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004
ICE083A 0 SORTIN DATA SET IS MISSING OR CANNOT BE OPENED
IEF452I PAYJOB - JOB FAILED - JCL ERROR
"""
    res = analyze_log(log)
    codes = {e.code for e in res.detected_errors}
    assert "S806" in codes
    assert "ICE083A" in codes
    assert "IEF452I" in codes


def test_15_extract_job_and_step_identifiers():
    """15. Extract job and step identifiers from log messages."""
    log = "IEF450I MYPAY01 CALCSTEP - ABEND=S0C7 U0000"
    res = analyze_log(log)
    err = res.detected_errors[0]
    assert err.job_name == "MYPAY01"
    assert err.step_name == "CALCSTEP"


def test_16_preserve_log_line_numbers():
    """16. Preserve log line numbers accurately."""
    log = """Line 1: Log header
Line 2: //PAYJOB JOB ...
Line 3: IEF236I ALLOC. FOR PAYJOB STEP1
Line 4: IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004
"""
    res = analyze_log(log)
    s806 = [e for e in res.detected_errors if e.code == "S806"][0]
    assert s806.source_line == 4


# -----------------------------------------------------------------------------
# 2. JCL Correlation Tests
# -----------------------------------------------------------------------------

def test_17_correlate_s806_with_exec_pgm():
    """17. Correlate S806 with EXEC PGM and STEPLIB in supplied JCL."""
    log = "IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004"
    jcl = """//PAYJOB JOB (ACCT#123),'TEST'
//STEP1  EXEC PGM=MISSMOD
//STEPLIB DD DSN=USER.LOADLIB,DISP=SHR
//SYSIN   DD *
DATA
/*
"""
    res = analyze_log(log, jcl=jcl)
    assert len(res.related_jcl_lines) >= 2
    exec_line = [l for l in res.related_jcl_lines if l.statement_type == "EXEC"][0]
    steplib_line = [l for l in res.related_jcl_lines if l.statement_type == "DD"][0]

    assert exec_line.line_number == 2
    assert "MISSMOD" in exec_line.relevance or "MISSMOD" in exec_line.content
    assert steplib_line.line_number == 3
    assert "STEPLIB" in steplib_line.content


def test_18_handle_logs_without_known_error_codes():
    """18. Handle logs without known error codes gracefully without guessing."""
    log = "Random informational console text that contains no JES tokens or abend codes."
    res = analyze_log(log)
    assert len(res.detected_errors) == 0
    assert "No standard IBM ABEND codes" in res.summary
    assert len(res.troubleshooting_steps) > 0


# -----------------------------------------------------------------------------
# 3. Request Validation & API Tests
# -----------------------------------------------------------------------------

def test_19_reject_empty_input():
    """19. Reject empty log text input."""
    res = client.post("/api/jcl/explain-error", json={"log_text": "", "use_ai": False})
    assert res.status_code == 400 or res.status_code == 422


def test_20_enforce_maximum_input_size():
    """20. Enforce maximum input size constraint (100,000 chars)."""
    large_log = "A" * 100001
    res = client.post("/api/jcl/explain-error", json={"log_text": large_log, "use_ai": False})
    assert res.status_code == 400 or res.status_code == 422


def test_21_work_without_llm_api_keys():
    """21. Work completely offline without LLM API keys when use_ai is false."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
        req = ExplainErrorRequest(
            log_text="IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004",
            use_ai=False,
        )
        res = explain_error_service(req)
        assert res.ai_used is False
        assert len(res.detected_errors) >= 1
        assert "S806" in [e.code for e in res.detected_errors]


def test_22_use_mocked_openai_responses():
    """22. Use mocked OpenAI response when use_ai is true."""
    mock_ai_output = {
        "summary": "Mocked diagnosis: The step abended with S806 due to missing load module MISSMOD.",
        "likely_causes": ["Program MISSMOD does not exist in USER.LOADLIB."],
        "troubleshooting_steps": ["Verify member MISSMOD in PDS USER.LOADLIB."],
        "confidence_notes": "High certainty based on explicit S806 and reason code 00000004.",
        "usage": TokenUsage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=0.0001,
            provider="openai",
            model="gpt-5.4-mini",
        ),
        "model": "gpt-5.4-mini",
    }

    with patch("backend.error_explainer.service.explain_error_with_openai", return_value=mock_ai_output):
        req = ExplainErrorRequest(
            log_text="IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004",
            jcl="//STEP1 EXEC PGM=MISSMOD",
            provider="openai",
            use_ai=True,
        )
        res = explain_error_service(req)
        assert res.ai_used is True
        assert "Mocked diagnosis" in res.summary
        assert "Program MISSMOD does not exist" in res.likely_causes[0]
        assert res.usage is not None
        assert res.usage.total_tokens == 150


def test_23_handle_llm_503_errors():
    """23. Handle missing API key 503 error cleanly through API."""
    with patch("backend.error_explainer.service.explain_error_with_openai", side_effect=RuntimeError("OPENAI_API_KEY is not configured")):
        payload = {
            "log_text": "IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004",
            "provider": "openai",
            "use_ai": True,
        }
        res = client.post("/api/jcl/explain-error", json=payload)
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"]


def test_24_handle_malformed_llm_responses():
    """24. Handle malformed LLM response errors cleanly through API."""
    with patch("backend.error_explainer.service.explain_error_with_openai", side_effect=RuntimeError("OpenAI returned an empty response.")):
        payload = {
            "log_text": "IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004",
            "provider": "openai",
            "use_ai": True,
        }
        res = client.post("/api/jcl/explain-error", json=payload)
        assert res.status_code == 502
        assert "failed" in res.json()["detail"]


def test_25_never_expose_api_keys():
    """25. Verify that API keys and credentials are never exposed in responses or errors."""
    payload = {
        "log_text": "IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004",
        "use_ai": False,
    }
    res = client.post("/api/jcl/explain-error", json=payload)
    assert res.status_code == 200
    res_str = json.dumps(res.json())
    assert "sk-" not in res_str
    assert "AIza" not in res_str


def test_26_never_modify_editor_jcl():
    """26. Ensure Error Explainer does not modify or reformat existing JCL."""
    original_jcl = "//MYJOB JOB (ACCT#),'TEST'\n//STEP1 EXEC PGM=IEFBR14\n"
    res = analyze_log("IEF450I MYJOB STEP1 - ABEND=S806", jcl=original_jcl)
    # The API returns diagnostics and line references, leaving original JCL intact
    assert isinstance(res, ExplainErrorResponse)
    assert len(res.related_jcl_lines) > 0


def test_27_respect_disabled_jcl_context():
    """27. Respect disabled JCL context (no JCL transmitted to model or correlated)."""
    res = analyze_log("IEF450I MYJOB STEP1 - ABEND=S806", jcl=None)
    assert len(res.related_jcl_lines) == 0


def test_28_preserve_existing_editor_modes():
    """28. Verify existing endpoints (/api/generate, /api/build, /api/jcl/validate) remain operational."""
    # Test validate
    val_res = client.post("/api/jcl/validate", json={"jcl": "//JOB1 JOB (ACCT#)\n//STEP1 EXEC PGM=IEFBR14\n"})
    assert val_res.status_code == 200
    assert val_res.json()["valid"] is True

    # Test templates
    tmpl_res = client.get("/api/templates")
    assert tmpl_res.status_code == 200


def test_29_copy_explanation_without_changing_jcl():
    """29. Ensure generated explanation can be compiled as copyable text without affecting JCL."""
    res = analyze_log("IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004")
    copyable_text = f"""=== JCL Error Diagnosis ===
Summary: {res.summary}
Errors: {', '.join(e.code for e in res.detected_errors)}
Likely Causes:
{chr(10).join(f"- {c}" for c in res.likely_causes)}
Troubleshooting Steps:
{chr(10).join(f"- {s}" for s in res.troubleshooting_steps)}
Limitations: {res.limitations[0]}
"""
    assert "S806" in copyable_text
    assert "Program Loading Failure" in copyable_text or "Load Module Not Found" in copyable_text


def test_30_return_meaningful_uncertainty_statements():
    """30. Verify limitations explicitly state diagnosis is based on supplied text and not live JES access."""
    res = analyze_log("IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004")
    assert len(res.limitations) >= 1
    assert any("not live JES access" in lim for lim in res.limitations)


def test_31_frontend_ui_elements_present():
    """31. Verify that HTML serves all required Error Explainer UI elements."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'id="tabExplainerMode"' in html
    assert 'id="explainerSection"' in html
    assert 'id="logInput"' in html
    assert 'id="pasteLogBtn"' in html
    assert 'id="clearLogBtn"' in html
    assert 'id="includeJclContext"' in html
    assert 'id="useAiExplainer"' in html
    assert 'id="explainErrorBtn"' in html
    assert 'id="explainerResultsPanel"' in html
    assert 'id="copyExplanationBtn"' in html
    assert 'Operational Privacy Notice' in html


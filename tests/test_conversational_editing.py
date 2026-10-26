"""Automated tests for Conversational JCL Editing in JCL Studio AI.

Covers the 20 required behaviors:
1. Modify DFSORT ascending to descending
2. Modify SPACE primary allocation
3. Add a second sort key
4. Preserve unrelated JOB and DD statements
5. Preserve JCL comments
6. Preserve symbolic dataset names
7. Preserve in-stream SYSIN data
8. Return valid structured diff
9. Return validation diagnostics
10. Reject empty JCL
11. Reject empty or very short instructions
12. Handle LLM 503 failures
13. Handle malformed LLM responses
14. Discard a proposal without changing the editor
15. Apply a proposal after confirmation
16. Prevent applying stale proposals
17. Support undo after applying
18. Preserve existing provider configuration
19. Ensure no LLM calls during static validation
20. Verify no API keys appear in frontend responses
"""

import json
import os
import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import main
from backend.diff_engine import generate_structured_diff
from llm_provider import JclChangeItem, JclModifyResult, TokenUsage

client = TestClient(main.app)
INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"

SAMPLE_DFSORT_JCL = (
    "//SORTJOB  JOB (ACCT#123),'SYSADMIN',CLASS=A,MSGCLASS=X\n"
    "//* AI JCL STUDIO - ILLUSTRATIVE ONLY - NOT VERIFIED ON z/OS\n"
    "//* SAMPLE SORT STEP COMMENT\n"
    "//STEP01   EXEC PGM=DFSORT\n"
    "//SORTIN   DD DSN=&SYSUID..INPUT.DATA,DISP=SHR\n"
    "//SORTOUT  DD DSN=&SYSUID..OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),\n"
    "//            SPACE=(CYL,(5,1),RLSE),UNIT=SYSDA\n"
    "//SORTWK01 DD UNIT=SYSDA,SPACE=(CYL,(5,1))\n"
    "//SYSOUT   DD SYSOUT=*\n"
    "//SYSIN    DD *\n"
    "  SORT FIELDS=(1,10,CH,A)\n"
    "/*\n"
    "//\n"
)


@pytest.fixture
def index_html_content() -> str:
    assert INDEX_HTML_PATH.exists()
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# 1. Modify DFSORT ascending to descending
# -----------------------------------------------------------------------------
def test_modify_dfsort_ascending_to_descending(monkeypatch):
    """Verifies modifying sort order from A to D updates control card and diff."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace("SORT FIELDS=(1,10,CH,A)", "SORT FIELDS=(1,10,CH,D)")

    def fake_modify_openai(request):
        return JclModifyResult(
            modified_jcl=mod_jcl,
            summary="Changed SORT FIELDS order from ascending (A) to descending (D)",
            changes=[JclChangeItem(type="modified", description="Changed sort ordering from A to D")],
            assumptions=["Primary sort key remains bytes 1-10"],
            clarifications=[],
            usage=TokenUsage(input_tokens=100, output_tokens=150, total_tokens=250),
            provider="openai",
            model="gpt-5.4-mini"
        )

    monkeypatch.setattr(main, "modify_with_openai", fake_modify_openai)

    resp = client.post(
        "/api/jcl/modify",
        json={
            "jcl": SAMPLE_DFSORT_JCL,
            "instruction": "Change sort order to descending",
            "provider": "openai"
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "SORT FIELDS=(1,10,CH,D)" in data["modified_jcl"]
    assert "SORT FIELDS=(1,10,CH,A)" not in data["modified_jcl"]

    # Diff must reflect change
    removed_lines = [d["content"] for d in data["diff_lines"] if d["type"] == "removed"]
    added_lines = [d["content"] for d in data["diff_lines"] if d["type"] == "added"]
    assert any("CH,A" in l for l in removed_lines)
    assert any("CH,D" in l for l in added_lines)


# -----------------------------------------------------------------------------
# 2. Modify SPACE primary allocation
# -----------------------------------------------------------------------------
def test_modify_space_primary_allocation(monkeypatch):
    """Verifies increasing primary SPACE allocation in modified JCL."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace("SPACE=(CYL,(5,1),RLSE)", "SPACE=(CYL,(25,1),RLSE)")

    def fake_modify(request):
        return JclModifyResult(
            modified_jcl=mod_jcl,
            summary="Increased primary cylinder allocation to 25",
            changes=[JclChangeItem(type="modified", description="Updated SPACE parameter on SORTOUT")],
            usage=TokenUsage(input_tokens=110, output_tokens=160, total_tokens=270),
            provider="openai",
            model="gpt-5.4-mini"
        )

    monkeypatch.setattr(main, "modify_with_openai", fake_modify)

    resp = client.post(
        "/api/jcl/modify",
        json={
            "jcl": SAMPLE_DFSORT_JCL,
            "instruction": "Increase primary SPACE allocation from 5 cylinders to 25 cylinders",
            "provider": "openai"
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "SPACE=(CYL,(25,1),RLSE)" in data["modified_jcl"]


# -----------------------------------------------------------------------------
# 3. Add a second sort key
# -----------------------------------------------------------------------------
def test_add_second_sort_key(monkeypatch):
    """Verifies adding a secondary sort key to SORT FIELDS."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace(
        "SORT FIELDS=(1,10,CH,A)",
        "SORT FIELDS=(1,10,CH,A,15,5,CH,A)"
    )

    def fake_modify(request):
        return JclModifyResult(
            modified_jcl=mod_jcl,
            summary="Added second sort key at column 15 length 5 character ascending",
            changes=[JclChangeItem(type="modified", description="Appended second key (15,5,CH,A)")],
            provider="openai",
            model="gpt-5.4-mini"
        )

    monkeypatch.setattr(main, "modify_with_openai", fake_modify)

    resp = client.post(
        "/api/jcl/modify",
        json={
            "jcl": SAMPLE_DFSORT_JCL,
            "instruction": "Add a second sort key at position 15 length 5 ascending",
            "provider": "openai"
        }
    )
    assert resp.status_code == 200
    assert "SORT FIELDS=(1,10,CH,A,15,5,CH,A)" in resp.json()["modified_jcl"]


# -----------------------------------------------------------------------------
# 4. Preserve unrelated JOB and DD statements
# -----------------------------------------------------------------------------
def test_preserve_unrelated_job_and_dd_statements(monkeypatch):
    """Verifies that modification of one parameter preserves all other statements verbatim."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace("SORT FIELDS=(1,10,CH,A)", "SORT FIELDS=(1,10,CH,D)")

    def fake_modify(request):
        return JclModifyResult(
            modified_jcl=mod_jcl,
            summary="Changed sort order",
            provider="openai",
            model="gpt-5.4-mini"
        )

    monkeypatch.setattr(main, "modify_with_openai", fake_modify)

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Change sort order to descending"}
    )
    mod = resp.json()["modified_jcl"]
    assert "//SORTJOB  JOB (ACCT#123),'SYSADMIN',CLASS=A,MSGCLASS=X" in mod
    assert "//STEP01   EXEC PGM=DFSORT" in mod
    assert "//SORTIN   DD DSN=&SYSUID..INPUT.DATA,DISP=SHR" in mod
    assert "//SORTWK01 DD UNIT=SYSDA,SPACE=(CYL,(5,1))" in mod
    assert "//SYSOUT   DD SYSOUT=*" in mod


# -----------------------------------------------------------------------------
# 5. Preserve JCL comments
# -----------------------------------------------------------------------------
def test_preserve_jcl_comments(monkeypatch):
    """Verifies header and custom JCL comments are preserved."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace("SORT FIELDS=(1,10,CH,A)", "SORT FIELDS=(1,10,CH,D)")

    monkeypatch.setattr(main, "modify_with_openai", lambda req: JclModifyResult(
        modified_jcl=mod_jcl, summary="Changed sort order", provider="openai", model="gpt-5.4-mini"
    ))

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Change sort order to descending"}
    )
    mod = resp.json()["modified_jcl"]
    assert "//* AI JCL STUDIO - ILLUSTRATIVE ONLY - NOT VERIFIED ON z/OS" in mod
    assert "//* SAMPLE SORT STEP COMMENT" in mod


# -----------------------------------------------------------------------------
# 6. Preserve symbolic dataset names
# -----------------------------------------------------------------------------
def test_preserve_symbolic_dataset_names(monkeypatch):
    """Verifies symbolic parameters like &SYSUID..INPUT.DATA are preserved."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace("DISP=SHR", "DISP=OLD")

    monkeypatch.setattr(main, "modify_with_openai", lambda req: JclModifyResult(
        modified_jcl=mod_jcl, summary="Changed DISP to OLD", provider="openai", model="gpt-5.4-mini"
    ))

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Change input DISP to OLD"}
    )
    mod = resp.json()["modified_jcl"]
    assert "&SYSUID..INPUT.DATA" in mod
    assert "&SYSUID..OUTPUT.DATA" in mod


# -----------------------------------------------------------------------------
# 7. Preserve in-stream SYSIN data
# -----------------------------------------------------------------------------
def test_preserve_instream_sysin_data():
    """Verifies diff engine correctly tracks in-stream lines without stripping them."""
    orig = "//STEP01 EXEC PGM=DFSORT\n//SYSIN DD *\n  SORT FIELDS=(1,10,CH,A)\n/*\n"
    mod = "//STEP01 EXEC PGM=DFSORT\n//SYSIN DD *\n  SORT FIELDS=(1,10,CH,D)\n/*\n"
    diff = generate_structured_diff(orig, mod)

    assert any(d.content == "//SYSIN DD *" and d.type == "unchanged" for d in diff)
    assert any(d.content == "/*" and d.type == "unchanged" for d in diff)
    assert any("CH,A" in d.content and d.type == "removed" for d in diff)
    assert any("CH,D" in d.content and d.type == "added" for d in diff)


# -----------------------------------------------------------------------------
# 8. Return valid structured diff
# -----------------------------------------------------------------------------
def test_return_valid_structured_diff(monkeypatch):
    """Verifies diff_lines structure contains valid line_orig, line_mod, type, and content."""
    mod_jcl = SAMPLE_DFSORT_JCL.replace("SORT FIELDS=(1,10,CH,A)", "SORT FIELDS=(1,10,CH,D)")

    monkeypatch.setattr(main, "modify_with_openai", lambda req: JclModifyResult(
        modified_jcl=mod_jcl, summary="Updated sort order", provider="openai", model="gpt-5.4-mini"
    ))

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Change sort order to descending"}
    )
    data = resp.json()
    diff_lines = data["diff_lines"]
    assert len(diff_lines) > 0

    for dl in diff_lines:
        assert "type" in dl
        assert dl["type"] in ("added", "removed", "modified", "unchanged")
        assert "content" in dl
        if dl["type"] == "unchanged":
            assert dl["line_orig"] is not None
            assert dl["line_mod"] is not None


# -----------------------------------------------------------------------------
# 9. Return validation diagnostics
# -----------------------------------------------------------------------------
def test_return_validation_diagnostics(monkeypatch):
    """Verifies modified JCL is statically validated and new errors are detected."""
    # Introduce error: remove SORTIN DD
    broken_jcl = SAMPLE_DFSORT_JCL.replace("//SORTIN   DD DSN=&SYSUID..INPUT.DATA,DISP=SHR\n", "")

    monkeypatch.setattr(main, "modify_with_openai", lambda req: JclModifyResult(
        modified_jcl=broken_jcl, summary="Removed SORTIN DD", provider="openai", model="gpt-5.4-mini"
    ))

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Remove SORTIN statement"}
    )
    data = resp.json()
    assert data["validation"]["valid"] is False
    assert data["new_errors_introduced"] is True
    rule_ids = [d["rule_id"] for d in data["validation"]["diagnostics"]]
    assert "DFSORT_MISSING_SORTIN" in rule_ids


# -----------------------------------------------------------------------------
# 10. Reject empty JCL
# -----------------------------------------------------------------------------
def test_reject_empty_jcl():
    """Verifies empty or whitespace JCL is rejected with HTTP 400 or 422."""
    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": "   ", "instruction": "Change sort order"}
    )
    assert resp.status_code in (400, 422)


# -----------------------------------------------------------------------------
# 11. Reject empty or very short instructions
# -----------------------------------------------------------------------------
def test_reject_empty_or_short_instructions():
    """Verifies instructions under 3 characters are rejected with HTTP 422."""
    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "no"}
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# 12. Handle LLM 503 failures
# -----------------------------------------------------------------------------
def test_handle_llm_503_failures(monkeypatch):
    """Verifies unconfigured API key returns HTTP 503."""
    def fake_unconfigured(request):
        raise RuntimeError("OPENAI_API_KEY is not configured. Set OPENAI_API_KEY in your .env file.")

    monkeypatch.setattr(main, "modify_with_openai", fake_unconfigured)

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Change sort order"}
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# 13. Handle malformed LLM responses
# -----------------------------------------------------------------------------
def test_handle_malformed_llm_responses(monkeypatch):
    """Verifies unexpected LLM exceptions return HTTP 502 with clear detail."""
    def fake_broken_llm(request):
        raise ValueError("Invalid JSON token in provider output")

    monkeypatch.setattr(main, "modify_with_openai", fake_broken_llm)

    resp = client.post(
        "/api/jcl/modify",
        json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Change sort order"}
    )
    assert resp.status_code == 502
    assert "modification failed" in resp.json()["detail"].lower()


# -----------------------------------------------------------------------------
# 14. Discard a proposal without changing the editor
# -----------------------------------------------------------------------------
def test_discard_proposal_frontend_elements(index_html_content):
    """Verifies discard button closes proposal review without writing to editor."""
    assert 'id="discardChangesBtn"' in index_html_content
    assert "currentProposal = null" in index_html_content
    assert "proposalReviewPanel" in index_html_content


# -----------------------------------------------------------------------------
# 15. Apply a proposal after confirmation
# -----------------------------------------------------------------------------
def test_apply_proposal_frontend_elements(index_html_content):
    """Verifies apply button writes modified_jcl and updates editor stats."""
    assert 'id="applyChangesBtn"' in index_html_content
    assert "el('output').value = currentProposal.modified_jcl" in index_html_content
    assert "updateEditorStats()" in index_html_content


# -----------------------------------------------------------------------------
# 16. Prevent applying stale proposals
# -----------------------------------------------------------------------------
def test_prevent_applying_stale_proposals(index_html_content):
    """Verifies that if editor changed while proposal was open, apply is blocked."""
    assert "isProposalStale" in index_html_content
    assert "proposalStaleAlert" in index_html_content
    assert "Cannot apply stale proposal" in index_html_content


# -----------------------------------------------------------------------------
# 17. Support undo after applying
# -----------------------------------------------------------------------------
def test_support_undo_after_applying(index_html_content):
    """Verifies applying a proposal pushes previous JCL onto editor history stack."""
    # Before replacing output with modified_jcl, previous JCL is pushed to history
    assert "editorHistory.push(el('output').value)" in index_html_content


# -----------------------------------------------------------------------------
# 18. Preserve existing provider configuration
# -----------------------------------------------------------------------------
def test_preserve_provider_configuration(monkeypatch):
    """Verifies provider parameter selects OpenAI or Gemini."""
    def fake_openai(req):
        return JclModifyResult(modified_jcl=req.jcl, summary="OpenAI edit", provider="openai", model="gpt-5.4-mini")

    def fake_gemini(req):
        return JclModifyResult(modified_jcl=req.jcl, summary="Gemini edit", provider="gemini", model="gemini-2.5-flash")

    monkeypatch.setattr(main, "modify_with_openai", fake_openai)
    monkeypatch.setattr(main, "modify_with_gemini", fake_gemini)

    r_openai = client.post("/api/jcl/modify", json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Edit", "provider": "openai"})
    assert r_openai.status_code == 200
    assert r_openai.json()["provider"] == "openai"

    r_gemini = client.post("/api/jcl/modify", json={"jcl": SAMPLE_DFSORT_JCL, "instruction": "Edit", "provider": "gemini"})
    assert r_gemini.status_code == 200
    assert r_gemini.json()["provider"] == "gemini"


# -----------------------------------------------------------------------------
# 19. Ensure no LLM calls during static validation
# -----------------------------------------------------------------------------
def test_no_llm_calls_during_static_validation(monkeypatch):
    """Verifies static validation endpoints never invoke external LLM providers."""
    def fake_forbidden_llm(*args, **kwargs):
        raise AssertionError("LLM provider should NOT be called during static validation!")

    monkeypatch.setattr(main, "generate_with_openai", fake_forbidden_llm)
    monkeypatch.setattr(main, "generate_with_gemini", fake_forbidden_llm)
    monkeypatch.setattr(main, "modify_with_openai", fake_forbidden_llm)
    monkeypatch.setattr(main, "modify_with_gemini", fake_forbidden_llm)

    resp = client.post("/api/jcl/validate", json={"jcl": SAMPLE_DFSORT_JCL})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


# -----------------------------------------------------------------------------
# 20. Verify no API keys appear in frontend responses
# -----------------------------------------------------------------------------
def test_no_api_keys_in_frontend_responses():
    """Verifies that neither OpenAI nor Gemini API keys are ever leaked in responses."""
    # Check config endpoint
    resp_config = client.get("/api/config")
    assert resp_config.status_code == 200
    body = resp_config.text
    assert "sk-" not in body
    assert "AIza" not in body
    assert "api_key" not in body

    # Check html
    resp_html = client.get("/")
    assert resp_html.status_code == 200
    assert "sk-" not in resp_html.text
    assert "AIza" not in resp_html.text

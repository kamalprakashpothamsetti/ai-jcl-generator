"""Automated tests for line-aware parser, semantic validation, and configurable program registry."""

import pytest
from fastapi.testclient import TestClient

from backend.validation.models import Severity
from backend.validation.parser import parse_jcl_structure
from backend.validation.registry import (
    find_close_program_match,
    is_known_program,
    register_user_program,
    reset_registry,
    unregister_user_program,
)
from backend.validation.validator import validate_jcl_detailed, validate_jcl_full
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure registry state is clean before and after each test."""
    reset_registry()
    yield
    reset_registry()


def test_01_pgm_sort_recognized():
    """1. PGM=SORT recognized without typo warning or missing requirements."""
    jcl = """//SORTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=SORT
//SORTIN   DD DSN=MY.INPUT.DATA,DISP=SHR
//SORTOUT  DD DSN=MY.OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
SORT FIELDS=COPY
/*
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 0


def test_02_pgm_sor_generates_typo_warning():
    """2. PGM=SOR generates a possible typo warning suggesting SORT."""
    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP1    EXEC PGM=SOR
//DD1      DD DSN=MY.DATA,DISP=SHR
"""
    result = validate_jcl_full(jcl)
    # Warnings do not cause valid=False
    assert result.valid is True
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 1

    diag = typo_warnings[0]
    assert diag.severity == Severity.WARNING
    assert diag.line == 2
    assert diag.column == 21
    assert "Program SOR is not in the configured registry. Did you mean SORT?" in diag.message
    assert diag.suggested_fix == "Verify the program name or change PGM=SOR to PGM=SORT."


def test_03_pgm_iefbr14_recognized():
    """3. PGM=IEFBR14 recognized as standard utility."""
    jcl = """//DELJOB   JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=IEFBR14
//DD1      DD DSN=MY.OLD.DATA,DISP=(OLD,DELETE)
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 0


def test_04_pgm_iefbr1_generates_typo_warning():
    """4. PGM=IEFBR1 generates a possible typo warning suggesting IEFBR14."""
    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=IEFBR1
//DD1      DD DSN=MY.OLD.DATA,DISP=(OLD,DELETE)
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 1

    diag = typo_warnings[0]
    assert diag.severity == Severity.WARNING
    assert diag.line == 2
    assert "Program IEFBR1 is not in the configured registry. Did you mean IEFBR14?" in diag.message
    assert "PGM=IEFBR1 to PGM=IEFBR14" in (diag.suggested_fix or "")


def test_05_pgm_mycobol_allowed():
    """5. PGM=MYCOBOL is allowed without treating it as an invalid utility or raising errors."""
    jcl = """//COBJOB   JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=MYCOBOL
//INFILE   DD DSN=MY.INPUT.DATA,DISP=SHR
//OUTFILE  DD DSN=MY.OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    assert result.counts.errors == 0
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 0


def test_06_pgm_empty_produces_error():
    """6. PGM= produces an error with precise line and column."""
    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP1    EXEC PGM=
//DD1      DD DSN=MY.DATA,DISP=SHR
"""
    result = validate_jcl_full(jcl)
    assert result.valid is False
    pgm_errors = [d for d in result.diagnostics if d.rule_id == "MISSING_PROGRAM_NAME"]
    assert len(pgm_errors) == 1
    err = pgm_errors[0]
    assert err.severity == Severity.ERROR
    assert err.line == 2
    assert err.column == 21
    assert "cannot be empty" in err.message


def test_07_custom_registered_program_recognized():
    """7. Custom registered program is recognized without warning."""
    register_user_program("CUSTOM01")
    assert is_known_program("CUSTOM01") is True

    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=CUSTOM01
//DD1      DD DSN=MY.DATA,DISP=SHR
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 0


def test_08_unknown_programs_do_not_trigger_sort_requirements():
    """8. Unknown programs (e.g. custom or typos) do not trigger SORT-specific DD requirements."""
    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=MYAPP
//DATAIN   DD DSN=MY.APP.INPUT,DISP=SHR
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    sort_errors = [d for d in result.diagnostics if d.rule_id.startswith("DFSORT_")]
    assert len(sort_errors) == 0


def test_09_correct_physical_line_numbers_returned():
    """9. Correct physical line numbers are returned for diagnostics."""
    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//* Line 2 Comment
//* Line 3 Comment
//STEP1    EXEC PGM=SOR
//DD1      DD DSN=MY.DATA,DISP=SHR
"""
    result = validate_jcl_full(jcl)
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 1
    assert typo_warnings[0].line == 4


def test_10_correct_source_column_positions_returned():
    """10. Correct source column positions are returned dynamically calculated from source."""
    # Column for SOR starts at col 21
    jcl1 = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP1    EXEC PGM=SOR
"""
    result1 = validate_jcl_full(jcl1)
    typo1 = [d for d in result1.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"][0]
    assert typo1.column == 21

    # Extra spaces: column dynamically recalculated
    # //STEP01          EXEC      PGM=SOR
    jcl2 = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP01          EXEC      PGM=SOR
"""
    result2 = validate_jcl_full(jcl2)
    typo2 = [d for d in result2.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"][0]
    line_str = "//STEP01          EXEC      PGM=SOR"
    expected_col = line_str.find("SOR") + 1
    assert typo2.column == expected_col


def test_11_continuation_lines_parsed_correctly():
    """11. Continuation lines are parsed correctly and retained in continuation_lines."""
    jcl = """//MYJOB    JOB (ACCT#123),'OPERATOR',CLASS=A,
//            MSGCLASS=X
//STEP01   EXEC PGM=SORT,
//             REGION=4M
//SORTIN   DD DSN=MY.INPUT.DATA,
//            DISP=SHR
//SORTOUT  DD DSN=MY.OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
SORT FIELDS=COPY
/*
"""
    parsed = parse_jcl_structure(jcl)
    # Check JOB statement continuation
    job_stmt = parsed.statements[0]
    assert job_stmt.operation == "JOB"
    assert len(job_stmt.continuation_lines) == 1
    assert job_stmt.keyword_params.get("MSGCLASS") == "X"

    # Check EXEC statement continuation
    exec_stmt = parsed.statements[1]
    assert exec_stmt.operation == "EXEC"
    assert len(exec_stmt.continuation_lines) == 1
    assert exec_stmt.keyword_params.get("REGION") == "4M"
    assert exec_stmt.keyword_params.get("PGM") == "SORT"

    # Validation should pass
    result = validate_jcl_full(jcl)
    assert result.valid is True
    assert result.counts.errors == 0


def test_12_instream_sysin_lines_not_treated_as_jcl_statements():
    """12. In-stream SYSIN lines starting with // are not parsed as independent JCL statements."""
    jcl = """//TESTJOB  JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=SORT
//SORTIN   DD DSN=MY.INPUT.DATA,DISP=SHR
//SORTOUT  DD DSN=MY.OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
//STEP99   EXEC PGM=SOR
SORT FIELDS=COPY
/*
"""
    parsed = parse_jcl_structure(jcl)
    # Statements should NOT include STEP99 as an EXEC statement
    exec_stmts = [s for s in parsed.statements if s.statement_type == "EXEC"]
    assert len(exec_stmts) == 1
    assert exec_stmts[0].name == "STEP01"

    # The in-stream payload contains the records
    sysin_stmt = [s for s in parsed.statements if s.name == "SYSIN"][0]
    instream_texts = [line for _, line in sysin_stmt.instream_lines]
    assert any("//STEP99   EXEC PGM=SOR" in t for t in instream_texts)

    # Validation should NOT trigger typo warning for STEP99
    result = validate_jcl_full(jcl)
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 0


def test_13_comments_containing_pgm_sor_ignored():
    """13. Comments containing PGM=SOR are ignored and do not trigger typo warnings."""
    jcl = """//MYJOB    JOB (ACCT#123),'TEST',CLASS=A
//* //STEP1    EXEC PGM=SOR
//STEP01   EXEC PGM=IEFBR14
//DD1      DD DSN=MY.DATA,DISP=SHR
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 0


def test_14_multiple_exec_steps_validated_independently():
    """14. Multiple EXEC steps are validated independently."""
    jcl = """//MULTIJOB JOB (ACCT#123),'TEST',CLASS=A
//STEP01   EXEC PGM=SORT
//SORTIN   DD DSN=MY.INPUT.DATA,DISP=SHR
//SORTOUT  DD DSN=MY.OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
SORT FIELDS=COPY
/*
//STEP02   EXEC PGM=SOR
//DD1      DD DSN=MY.TEMP.DATA,DISP=SHR
//STEP03   EXEC PGM=MYCOBOL
//INFILE   DD DSN=MY.INPUT.DATA,DISP=SHR
//OUTFILE  DD DSN=MY.OUTPUT.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//STEP04   EXEC PGM=IEFBR14
//DELDD    DD DSN=MY.CLEANUP.DATA,DISP=(OLD,DELETE)
"""
    result = validate_jcl_full(jcl)
    assert result.valid is True  # Only warning on STEP02, no errors

    # Check STEP02 has typo warning
    typo_warnings = [d for d in result.diagnostics if d.rule_id == "SUSPICIOUS_PROGRAM_NAME"]
    assert len(typo_warnings) == 1
    assert typo_warnings[0].line == 9
    assert "Program SOR is not in the configured registry. Did you mean SORT?" in typo_warnings[0].message

    # Check parsed statements have correct associated step_names
    parsed = parse_jcl_structure(jcl)
    step1_dds = [s for s in parsed.statements if s.statement_type == "DD" and s.step_name == "STEP01"]
    step2_dds = [s for s in parsed.statements if s.statement_type == "DD" and s.step_name == "STEP02"]
    step3_dds = [s for s in parsed.statements if s.statement_type == "DD" and s.step_name == "STEP03"]
    step4_dds = [s for s in parsed.statements if s.statement_type == "DD" and s.step_name == "STEP04"]

    assert len(step1_dds) == 4  # SORTIN, SORTOUT, SYSOUT, SYSIN
    assert len(step2_dds) == 1  # DD1
    assert len(step3_dds) == 2  # INFILE, OUTFILE
    assert len(step4_dds) == 1  # DELDD


def test_15_existing_jcl_api_behavior_unchanged():
    """15. Existing JCL validation API endpoints remain fully functional and backward-compatible."""
    # Test POST /api/jcl/validate with PGM=SOR
    payload_sor = {
        "jcl": """//TESTJOB JOB (ACCT#123),'TEST',CLASS=A\n//STEP1   EXEC PGM=SOR\n//DD1     DD DSN=MY.DATA,DISP=SHR\n"""
    }
    res_sor = client.post("/api/jcl/validate", json=payload_sor)
    assert res_sor.status_code == 200
    data_sor = res_sor.json()
    assert data_sor["valid"] is True
    assert any(d["rule_id"] == "SUSPICIOUS_PROGRAM_NAME" for d in data_sor["diagnostics"])

    # Test POST /api/validate backward-compatibility
    res_compat = client.post("/api/validate", json=payload_sor)
    assert res_compat.status_code == 200
    compat_data = res_compat.json()
    assert "warnings" in compat_data
    assert "issues" in compat_data
    assert any("SOR" in w for w in compat_data["warnings"])

    # Test POST /api/build manual JCL generation
    build_req = {
        "job_card": {
            "job_name": "MANUAL01",
            "account_info": "ACCT#123",
            "programmer_name": "OPERATOR",
            "job_class": "A",
            "msg_class": "X",
            "msg_level": "(1,1)",
        },
        "steps": [
            {
                "step_name": "STEP01",
                "utility": "IEFBR14",
                "comments": "Allocate test dataset",
                "dds": [
                    {
                        "dd_name": "TESTDD",
                        "dsn": "USER.TEST.DATA",
                        "disp": "(NEW,CATLG,DELETE)",
                        "space": "(CYL,(1,1),RLSE)",
                        "unit": "SYSDA",
                    }
                ],
            }
        ],
    }
    res_build = client.post("/api/build", json=build_req)
    assert res_build.status_code == 200
    build_data = res_build.json()
    assert "PGM=IEFBR14" in build_data["jcl"]
    assert build_data["passed_basic_checks"] is True

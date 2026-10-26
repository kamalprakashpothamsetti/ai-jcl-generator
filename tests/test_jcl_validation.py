"""Comprehensive parameterized unit tests for JCL Static Validation Engine."""

import pytest
from fastapi.testclient import TestClient

import main
from backend.validation.models import Severity
from backend.validation.parser import (
    parse_jcl_structure,
    split_comma_parameters,
    split_operands_and_comment,
)
from backend.validation.validator import JclStaticValidator, validate_jcl_full

client = TestClient(main.app)

# -----------------------------------------------------------------------------
# 1. PARSER & TOKENIZER TESTS
# -----------------------------------------------------------------------------

def test_split_operands_and_comment():
    operands, comment = split_operands_and_comment("PGM=IEFBR14 THIS IS A COMMENT")
    assert operands == "PGM=IEFBR14"
    assert comment == "THIS IS A COMMENT"

    operands_quoted, comment_quoted = split_operands_and_comment("PARM='HELLO WORLD, 123' INLINE COMMENT")
    assert operands_quoted == "PARM='HELLO WORLD, 123'"
    assert comment_quoted == "INLINE COMMENT"

    operands_paren, comment_paren = split_operands_and_comment("SPACE=(CYL,(5,1),RLSE) COMMENT HERE")
    assert operands_paren == "SPACE=(CYL,(5,1),RLSE)"
    assert comment_paren == "COMMENT HERE"


def test_split_comma_parameters():
    tokens = split_comma_parameters("DSN=A.B,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(5,1)),PARM='X,Y,Z'")
    assert len(tokens) == 4
    assert tokens[0] == "DSN=A.B"
    assert tokens[1] == "DISP=(NEW,CATLG,DELETE)"
    assert tokens[2] == "SPACE=(CYL,(5,1))"
    assert tokens[3] == "PARM='X,Y,Z'"


def test_parser_statement_recognition():
    jcl = """//MYJOB   JOB (ACCT#123),'TEST OPERATOR',CLASS=A,MSGCLASS=X
//* THIS IS A JCL COMMENT
//SET1    SET PFX=USER
//STEP01  EXEC PGM=IEFBR14
//NEWDD   DD DSN=&PFX..SAMPLE.DATA,DISP=(NEW,CATLG,DELETE),
//           SPACE=(CYL,(1,1),RLSE),UNIT=SYSDA
//IF01    IF (RC = 0) THEN
//STEP02  EXEC PGM=IEFBR14
//ENDIF   ENDIF
//        NULL STATEMENT WITH COMMENT
//
"""
    parsed = parse_jcl_structure(jcl)
    types = [s.statement_type for s in parsed.statements]
    assert "JOB" in types
    assert "COMMENT" in types
    assert "SET" in types
    assert "EXEC" in types
    assert "DD" in types
    assert "IF" in types
    assert "ENDIF" in types
    assert "NULL" in types

    # Check line numbers preserved
    job_stmt = next(s for s in parsed.statements if s.statement_type == "JOB")
    assert job_stmt.start_line == 1
    assert job_stmt.name == "MYJOB"


def test_parser_instream_sysin_and_delimiters():
    jcl = """//SORTJOB JOB (ACCT#),CLASS=A
//STEP01  EXEC PGM=DFSORT
//SORTIN  DD DSN=USER.IN,DISP=SHR
//SORTOUT DD DSN=USER.OUT,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT  DD SYSOUT=*
//SYSIN   DD *
  SORT FIELDS=(1,10,CH,A)
  RECORD FORMAT=FB,LENGTH=80
/*
//LAST    EXEC PGM=IEFBR14
"""
    parsed = parse_jcl_structure(jcl)
    sysin_stmt = next(s for s in parsed.statements if s.name == "SYSIN")
    assert sysin_stmt.statement_type == "DD"
    assert len(sysin_stmt.instream_lines) == 2
    assert "SORT FIELDS=(1,10,CH,A)" in sysin_stmt.instream_lines[0][1]
    assert sysin_stmt.is_instream_terminated is True

    # Ensure in-stream control statements are NOT parsed as executable JCL statements
    types = [s.statement_type for s in parsed.statements]
    assert "SORT" not in types


def test_parser_instream_custom_dlm():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A
//STP1 EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN DD DATA,DLM='$$'
//THIS LOOKS LIKE JCL BUT IS DATA
  DELETE USER.CLUSTER CLUSTER
$$
"""
    parsed = parse_jcl_structure(jcl)
    sysin_stmt = next(s for s in parsed.statements if s.name == "SYSIN")
    assert len(sysin_stmt.instream_lines) == 2
    assert sysin_stmt.instream_delimiter == "$$"


# -----------------------------------------------------------------------------
# 2. GENERAL VALIDATION RULES TESTS
# -----------------------------------------------------------------------------

def test_missing_job_and_exec():
    res = validate_jcl_full("//* ONLY COMMENTS HERE\n")
    assert res.valid is False
    rule_ids = {d.rule_id for d in res.diagnostics}
    assert "NO_JOB_STATEMENT" in rule_ids
    assert "NO_EXEC_STATEMENT" in rule_ids


def test_line_length_80_columns():
    long_line = "//" + "X" * 80  # 82 columns
    jcl = f"//JOB1 JOB (ACCT#)\n//STEP1 EXEC PGM=IEFBR14\n{long_line}"
    res = validate_jcl_full(jcl)
    assert any(d.rule_id == "LINE_EXCEEDS_80" for d in res.diagnostics)


def test_duplicate_step_names():
    jcl = """//MYJOB JOB (ACCT#),CLASS=A
//STEP01 EXEC PGM=IEFBR14
//DD1    DD DSN=USER.DATA1,DISP=SHR
//STEP01 EXEC PGM=IEFBR14
//DD2    DD DSN=USER.DATA2,DISP=SHR
"""
    res = validate_jcl_full(jcl)
    assert res.valid is False
    assert any(d.rule_id == "DUPLICATE_STEP_NAME" for d in res.diagnostics)


def test_duplicate_dd_names_vs_valid_concatenation():
    # Duplicate named DD in same step -> Error
    jcl_dup = """//MYJOB JOB (ACCT#),CLASS=A
//STEP01 EXEC PGM=IEFBR14
//OUTDD  DD DSN=USER.DATA1,DISP=SHR
//OUTDD  DD DSN=USER.DATA2,DISP=SHR
"""
    res_dup = validate_jcl_full(jcl_dup)
    assert any(d.rule_id == "DUPLICATE_DD_NAME" for d in res_dup.diagnostics)

    # Valid unnamed DD concatenation -> Valid!
    jcl_concat = """//MYJOB JOB (ACCT#),CLASS=A
//STEP01 EXEC PGM=IEFBR14
//CONCAT DD DSN=USER.DATA1,DISP=SHR
//       DD DSN=USER.DATA2,DISP=SHR
"""
    res_concat = validate_jcl_full(jcl_concat)
    assert not any(d.rule_id == "DUPLICATE_DD_NAME" for d in res_concat.diagnostics)


@pytest.mark.parametrize("disp_str,is_valid", [
    ("SHR", True),
    ("OLD", True),
    ("(NEW,CATLG,DELETE)", True),
    ("(MOD,DELETE,DELETE)", True),
    ("(,CATLG)", True),
    ("INVALID_STATUS", False),
    ("(NEW,INVALID_DISP)", False),
    ("(NEW,CATLG,DELETE,EXTRA)", False),
])
def test_disp_validation(disp_str, is_valid):
    jcl = f"""//JOB1 JOB (ACCT#),CLASS=A
//STEP1 EXEC PGM=IEFBR14
//DD1   DD DSN=USER.TEST,DISP={disp_str},SPACE=(CYL,(1,1))
"""
    res = validate_jcl_full(jcl)
    disp_errors = [d for d in res.diagnostics if "DISP" in d.rule_id]
    if is_valid:
        assert len(disp_errors) == 0
    else:
        assert len(disp_errors) > 0


@pytest.mark.parametrize("dsn,is_valid", [
    ("USER.TEST.DATA", True),
    ("SYS1.PROCLIB(MEMBER)", True),
    ("USER.GDG.BASE(+1)", True),
    ("USER.GDG.BASE(0)", True),
    ("&&TEMPDSN", True),
    ("&SYSUID..OUTPUT.DATA", True),
    ("NULLFILE", True),
    ("A.VERY.LONG.DATASET.NAME.THAT.DEFINITELY.EXCEEDS.FORTY.FOUR.CHARACTERS.TOTAL", False),
    ("USER.QUALIFIERTOOLONG.DATA", False),
])
def test_dsn_syntax_validation(dsn, is_valid):
    jcl = f"""//JOB1 JOB (ACCT#),CLASS=A
//STEP1 EXEC PGM=IEFBR14
//DD1   DD DSN={dsn},DISP=SHR
"""
    res = validate_jcl_full(jcl)
    dsn_errors = [d for d in res.diagnostics if "DSN" in d.rule_id]
    if is_valid:
        assert len(dsn_errors) == 0
    else:
        assert len(dsn_errors) > 0


def test_dcb_blksize_lrecl_validation():
    # BLKSIZE not multiple of LRECL for FB
    jcl_bad = """//JOB1 JOB (ACCT#),CLASS=A
//STEP1 EXEC PGM=IEFBR14
//DD1   DD DSN=USER.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1)),
//         DCB=(RECFM=FB,LRECL=80,BLKSIZE=85)
"""
    res_bad = validate_jcl_full(jcl_bad)
    assert any(d.rule_id == "BLKSIZE_NOT_MULTIPLE_OF_LRECL" for d in res_bad.diagnostics)

    # Valid multiple (800 / 80 == 10)
    jcl_good = """//JOB1 JOB (ACCT#),CLASS=A
//STEP1 EXEC PGM=IEFBR14
//DD1   DD DSN=USER.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1)),
//         DCB=(RECFM=FB,LRECL=80,BLKSIZE=800)
"""
    res_good = validate_jcl_full(jcl_good)
    assert not any(d.rule_id == "BLKSIZE_NOT_MULTIPLE_OF_LRECL" for d in res_good.diagnostics)


def test_unterminated_instream_data():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A
//STEP1 EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN DD DATA,DLM='$$'
  DELETE USER.TEST CLUSTER
"""
    res = validate_jcl_full(jcl)
    assert any(d.rule_id == "UNTERMINATED_IN_STREAM_DATA" for d in res.diagnostics)


# -----------------------------------------------------------------------------
# 3. UTILITY-SPECIFIC RULES TESTS
# -----------------------------------------------------------------------------

def test_iefbr14_rules():
    # IEFBR14 does not require SYSPRINT or SYSIN
    jcl = """//JOB1 JOB (ACCT#),CLASS=A
//ALLOC EXEC PGM=IEFBR14
//NEWDS DD DSN=USER.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(5,1))
"""
    res = validate_jcl_full(jcl)
    assert res.valid is True
    assert not any("MISSING_SYSIN" in d.rule_id for d in res.diagnostics)

    # Warn if DISP=NEW missing SPACE
    jcl_no_space = """//JOB1 JOB (ACCT#),CLASS=A
//ALLOC EXEC PGM=IEFBR14
//NEWDS DD DSN=USER.DATA,DISP=(NEW,CATLG,DELETE)
"""
    res_no_space = validate_jcl_full(jcl_no_space)
    assert any(d.rule_id == "IEFBR14_MISSING_SPACE" for d in res_no_space.diagnostics)


def test_iebgener_rules():
    # Valid IEBGENER with DUMMY SYSIN
    jcl = """//JOB1 JOB (ACCT#),CLASS=A
//COPY EXEC PGM=IEBGENER
//SYSUT1   DD DSN=USER.IN,DISP=SHR
//SYSUT2   DD DSN=USER.OUT,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
"""
    res = validate_jcl_full(jcl)
    assert res.valid is True

    # Missing SYSUT1 and SYSUT2
    jcl_missing = """//JOB1 JOB (ACCT#),CLASS=A
//COPY EXEC PGM=IEBGENER
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
"""
    res_missing = validate_jcl_full(jcl_missing)
    rules = {d.rule_id for d in res_missing.diagnostics}
    assert "IEBGENER_MISSING_SYSUT1" in rules
    assert "IEBGENER_MISSING_SYSUT2" in rules


def test_dfsort_field_boundary_validation():
    # Input has LRECL=80; SORT FIELDS=(75,10,CH,A) overflows at byte 84
    jcl_overflow = """//JOB1 JOB (ACCT#),CLASS=A
//SORTSTEP EXEC PGM=DFSORT
//SORTIN   DD DSN=USER.IN,DISP=SHR,DCB=(RECFM=FB,LRECL=80)
//SORTOUT  DD DSN=USER.OUT,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(75,10,CH,A)
/*
"""
    res = validate_jcl_full(jcl_overflow)
    assert any(d.rule_id == "DFSORT_FIELD_EXCEEDS_LRECL" for d in res.diagnostics)

    # Valid sort fields within LRECL
    jcl_valid = """//JOB1 JOB (ACCT#),CLASS=A
//SORTSTEP EXEC PGM=DFSORT
//SORTIN   DD DSN=USER.IN,DISP=SHR,DCB=(RECFM=FB,LRECL=80)
//SORTOUT  DD DSN=USER.OUT,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A,20,5,ZD,D)
/*
"""
    res_valid = validate_jcl_full(jcl_valid)
    assert not any(d.rule_id == "DFSORT_FIELD_EXCEEDS_LRECL" for d in res_valid.diagnostics)


def test_dfsort_outfil_alternative_to_sortout():
    # OUTFIL used instead of SORTOUT
    jcl_outfil = """//JOB1 JOB (ACCT#),CLASS=A
//SORTSTEP EXEC PGM=DFSORT
//SORTIN   DD DSN=USER.IN,DISP=SHR
//SYSOUT   DD SYSOUT=*
//OUTFILE1 DD DSN=USER.OUT1,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSIN    DD *
  SORT FIELDS=COPY
  OUTFIL FNAMES=OUTFILE1
/*
"""
    res = validate_jcl_full(jcl_outfil)
    assert not any(d.rule_id == "DFSORT_MISSING_SORTOUT" for d in res.diagnostics)


def test_idcams_repro_dd_reference():
    # REPRO INFILE(INP) but DD //INP is missing
    jcl_bad_dd = """//JOB1 JOB (ACCT#),CLASS=A
//AMS EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  REPRO INFILE(INP) OUTFILE(OUT)
/*
"""
    res = validate_jcl_full(jcl_bad_dd)
    rules = {d.rule_id for d in res.diagnostics}
    assert "IDCAMS_REPRO_MISSING_INFILE_DD" in rules
    assert "IDCAMS_REPRO_MISSING_OUTFILE_DD" in rules


# -----------------------------------------------------------------------------
# 4. API ENDPOINT TESTS (POST /api/jcl/validate)
# -----------------------------------------------------------------------------

def test_api_jcl_validate_endpoint():
    valid_jcl = """//MYJOB JOB (ACCT#123),'TEST',CLASS=A,MSGCLASS=X
//STEP1 EXEC PGM=IEFBR14
//ALLOC DD DSN=USER.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1),RLSE)
"""
    response = client.post("/api/jcl/validate", json={"jcl": valid_jcl})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["validation_level"] == "static"
    assert data["executable_verified"] is False
    assert "diagnostics" in data
    assert "counts" in data
    assert data["counts"]["errors"] == 0
    assert "disclaimer" in data


def test_api_jcl_validate_detects_errors():
    invalid_jcl = "//MYJOB JOB (ACCT#)\n"  # Missing EXEC
    response = client.post("/api/jcl/validate", json={"jcl": invalid_jcl})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert data["counts"]["errors"] > 0
    assert any(d["rule_id"] == "NO_EXEC_STATEMENT" for d in data["diagnostics"])

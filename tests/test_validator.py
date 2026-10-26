import pytest
from jcl_validator import JclValidator, Severity, validate_jcl, validate_jcl_detailed

SAMPLE_VALID_JOB = """//TESTJOB1 JOB (ACCT#123),'OPERATOR',CLASS=A,MSGCLASS=X
//STEP01   EXEC PGM=IEFBR14
//NEWDS    DD DSN=USER.TEST.DATA,DISP=(NEW,CATLG,DELETE),
//            SPACE=(CYL,(1,1),RLSE),UNIT=SYSDA
"""

def test_valid_job():
    issues = JclValidator(SAMPLE_VALID_JOB).validate()
    errors_and_warnings = [i for i in issues if i.severity in (Severity.ERROR, Severity.WARNING)]
    assert len(errors_and_warnings) == 0
    res = validate_jcl_detailed(SAMPLE_VALID_JOB)
    assert res["passed_basic_checks"] is True
    assert len(res["warnings"]) == 0

def test_missing_job_statement():
    jcl = "//STEP01 EXEC PGM=IEFBR14\n//DD1 DD DSN=TEST,DISP=SHR"
    warnings = validate_jcl(jcl)
    assert any("No JOB statement detected." in w for w in warnings)

def test_missing_exec_statement():
    jcl = "//MYJOB JOB (ACCT#)\n//DD1 DD DSN=TEST,DISP=SHR"
    warnings = validate_jcl(jcl)
    assert any("No EXEC statement detected." in w for w in warnings)

def test_card_image_length():
    long_line = "//" + "A" * 80  # 82 columns
    jcl = f"//MYJOB JOB (ACCT#)\n//STEP1 EXEC PGM=IEFBR14\n{long_line}"
    res = validate_jcl_detailed(jcl)
    assert any("80 columns" in w for w in res["warnings"])
    assert any(i["rule_id"] == "LINE_EXCEEDS_80" for i in res["issues"])

def test_continuation_valid():
    jcl = """//MYJOB JOB (ACCT#),CLASS=A,
//            MSGCLASS=X
//STEP1 EXEC PGM=IEFBR14
//DD1   DD DSN=USER.DATA,
//         DISP=SHR
"""
    res = validate_jcl_detailed(jcl)
    continuation_issues = [i for i in res["issues"] if i["category"] == "CONTINUATION"]
    assert len(continuation_issues) == 0

def test_continuation_missing_blank_in_column_3():
    # Previous line ends with comma, but next line starts with //A (no blank in col 3)
    jcl = """//MYJOB JOB (ACCT#),CLASS=A,
//STEP1 EXEC PGM=IEFBR14
"""
    res = validate_jcl_detailed(jcl)
    assert any(i["rule_id"] == "CONTINUATION_MISSING_COL3_BLANK" for i in res["issues"])

def test_unexpected_continuation():
    # Line 1 does not end with comma, line 2 has // followed by spaces
    jcl = """//MYJOB JOB (ACCT#),CLASS=A
//            MSGCLASS=X
//STEP1 EXEC PGM=IEFBR14
"""
    res = validate_jcl_detailed(jcl)
    assert any(i["rule_id"] == "UNEXPECTED_CONTINUATION" for i in res["issues"])

def test_continuation_operand_past_column_16():
    # Continuation operands start after column 16 (e.g. at column 25)
    jcl = """//MYJOB JOB (ACCT#),CLASS=A,
//                     MSGCLASS=X
//STEP1 EXEC PGM=IEFBR14
"""
    res = validate_jcl_detailed(jcl)
    assert any(i["rule_id"] == "CONTINUATION_COL_OUT_OF_BOUNDS" for i in res["issues"])

def test_instream_sysin_not_flagged_as_invalid_jcl():
    jcl = """//MYJOB JOB (ACCT#),CLASS=A,MSGCLASS=X
//STEP01 EXEC PGM=DFSORT
//SORTIN   DD DSN=USER.INPUT,DISP=SHR
//SORTOUT  DD DSN=USER.OUTPUT,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSOUT   DD SYSOUT=*
//SYSIN    DD *
  SORT FIELDS=(1,10,CH,A)
  RECORD FORMAT=FB,LENGTH=80
/*
"""
    res = validate_jcl_detailed(jcl)
    syntax_issues = [i for i in res["issues"] if i["category"] == "SYNTAX"]
    assert len(syntax_issues) == 0
    assert res["passed_basic_checks"] is True

def test_iebgener_missing_required_dds():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A,MSGCLASS=X
//COPYSTEP EXEC PGM=IEBGENER
//SYSUT1   DD DSN=USER.IN,DISP=SHR
"""
    res = validate_jcl_detailed(jcl)
    missing_rules = {i["rule_id"] for i in res["issues"]}
    assert "IEBGENER_MISSING_SYSUT2" in missing_rules
    assert "IEBGENER_MISSING_SYSPRINT" in missing_rules
    assert "IEBGENER_MISSING_SYSIN" in missing_rules

def test_iebgener_all_dds_present():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A,MSGCLASS=X
//COPYSTEP EXEC PGM=IEBGENER
//SYSUT1   DD DSN=USER.IN,DISP=SHR
//SYSUT2   DD DSN=USER.OUT,DISP=(NEW,CATLG,DELETE),SPACE=(CYL,(1,1))
//SYSPRINT DD SYSOUT=*
//SYSIN    DD DUMMY
"""
    res = validate_jcl_detailed(jcl)
    iebgener_issues = [i for i in res["issues"] if "IEBGENER" in i["rule_id"]]
    assert len(iebgener_issues) == 0

def test_dfsort_missing_dds():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A,MSGCLASS=X
//SORTSTEP EXEC PGM=DFSORT
//SORTIN   DD DSN=USER.IN,DISP=SHR
"""
    res = validate_jcl_detailed(jcl)
    missing_rules = {i["rule_id"] for i in res["issues"]}
    assert "DFSORT_MISSING_SORTOUT" in missing_rules
    assert "DFSORT_MISSING_SYSOUT" in missing_rules
    assert "DFSORT_MISSING_SYSIN" in missing_rules

def test_idcams_missing_dds():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A,MSGCLASS=X
//DEFSTEP EXEC PGM=IDCAMS
"""
    res = validate_jcl_detailed(jcl)
    missing_rules = {i["rule_id"] for i in res["issues"]}
    assert "IDCAMS_MISSING_SYSPRINT" in missing_rules
    assert "IDCAMS_MISSING_SYSIN" in missing_rules

def test_idcams_valid():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A,MSGCLASS=X
//DEFSTEP EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *
  DELETE USER.TEST.CLUSTER CLUSTER PURGE
  SET MAXCC = 0
  DEFINE CLUSTER (NAME(USER.TEST.CLUSTER) -
         INDEXED KEYS(8 0) RECORDSIZE(80 80))
/*
"""
    res = validate_jcl_detailed(jcl)
    idcams_errs = [i for i in res["issues"] if i["severity"] == Severity.ERROR]
    assert len(idcams_errs) == 0

def test_iefbr14_missing_space_on_new_dataset():
    jcl = """//JOB1 JOB (ACCT#),CLASS=A,MSGCLASS=X
//ALLOC EXEC PGM=IEFBR14
//NEWDS DD DSN=USER.TEST.NEW,DISP=(NEW,CATLG,DELETE)
"""
    res = validate_jcl_detailed(jcl)
    assert any(i["rule_id"] == "IEFBR14_MISSING_SPACE" for i in res["issues"])

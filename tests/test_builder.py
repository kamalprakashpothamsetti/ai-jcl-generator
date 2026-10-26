import pytest
from jcl_builder import (
    JobCard,
    DdStatement,
    JclStep,
    ManualBuildRequest,
    format_manual_jcl,
    get_preset_templates,
)
from jcl_validator import validate_jcl_detailed

def test_builder_basic_iefbr14():
    req = ManualBuildRequest(
        job=JobCard(job_name="ALLOCJOB", accounting="(ACCT#999)", programmer_name="'TEST'"),
        steps=[
            JclStep(
                step_name="STEP01",
                utility="IEFBR14",
                comments="Allocate sample dataset",
                dds=[
                    DdStatement(
                        dd_name="NEWDS",
                        dsn="USER.TEST.DATA",
                        disp="(NEW,CATLG,DELETE)",
                        unit="SYSDA",
                        space="(CYL,(2,1),RLSE)",
                        recfm="FB",
                        lrecl=80,
                        blksize=0,
                    )
                ]
            )
        ]
    )
    jcl = format_manual_jcl(req)
    assert "//ALLOCJOB JOB  " in jcl
    assert "//STEP01   EXEC PGM=IEFBR14" in jcl
    assert "DSN=USER.TEST.DATA" in jcl
    assert "DISP=(NEW,CATLG,DELETE)" in jcl
    assert "ILLUSTRATIVE MAINFRAME JCL GENERATOR" in jcl

    # Validate generated JCL
    val = validate_jcl_detailed(jcl)
    assert val["passed_basic_checks"] is True
    # Ensure no line exceeds 80 columns
    for idx, line in enumerate(jcl.splitlines(), 1):
        assert len(line) <= 80, f"Line {idx} exceeds 80 columns: {line}"

def test_builder_iebgener():
    req = ManualBuildRequest(
        job=JobCard(job_name="COPYJOB"),
        steps=[
            JclStep(
                step_name="COPY01",
                utility="IEBGENER",
                dds=[
                    DdStatement(dd_name="SYSUT1", dsn="USER.IN", disp="SHR"),
                    DdStatement(dd_name="SYSUT2", dsn="USER.OUT", disp="(NEW,CATLG,DELETE)", space="(CYL,(1,1))"),
                    DdStatement(dd_name="SYSPRINT", sysout="*"),
                    DdStatement(dd_name="SYSIN", dummy=True),
                ]
            )
        ]
    )
    jcl = format_manual_jcl(req)
    val = validate_jcl_detailed(jcl)
    assert val["passed_basic_checks"] is True

def test_builder_dfsort_with_instream():
    req = ManualBuildRequest(
        job=JobCard(job_name="SORTJOB"),
        steps=[
            JclStep(
                step_name="SORT01",
                utility="DFSORT",
                dds=[
                    DdStatement(dd_name="SORTIN", dsn="USER.IN", disp="SHR"),
                    DdStatement(dd_name="SORTOUT", dsn="USER.OUT", disp="(NEW,CATLG,DELETE)", space="(CYL,(1,1))"),
                    DdStatement(dd_name="SYSOUT", sysout="*"),
                    DdStatement(
                        dd_name="SYSIN",
                        instream_data="  SORT FIELDS=(1,10,CH,A)\n  RECORD FORMAT=FB,LENGTH=80"
                    ),
                ]
            )
        ]
    )
    jcl = format_manual_jcl(req)
    assert "SORT FIELDS=(1,10,CH,A)" in jcl
    assert "/*" in jcl
    val = validate_jcl_detailed(jcl)
    # Basic checks should pass (only SORTWK info issue may exist)
    errors = [i for i in val["issues"] if i["severity"] == "ERROR"]
    assert len(errors) == 0

def test_preset_templates():
    templates = get_preset_templates()
    assert "IEFBR14_ALLOCATE" in templates
    assert "IEFBR14_DELETE" in templates
    assert "IEBGENER_COPY" in templates
    assert "DFSORT_SORT" in templates
    assert "IDCAMS_DEFINE_CLUSTER" in templates
    assert "IDCAMS_REPRO" in templates

    # Test all templates render valid JCL
    for key, tmpl in templates.items():
        req = ManualBuildRequest.model_validate(tmpl["request"])
        jcl = format_manual_jcl(req)
        assert len(jcl) > 50
        for line in jcl.splitlines():
            assert len(line) <= 80
        val = validate_jcl_detailed(jcl)
        errors = [i for i in val["issues"] if i["severity"] == "ERROR"]
        assert len(errors) == 0, f"Template {key} produced validation errors: {errors}"

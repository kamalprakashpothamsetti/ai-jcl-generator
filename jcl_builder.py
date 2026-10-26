"""IBM z/OS Manual JCL Builder and Template Engine.

Builds structured, 80-column compliant JCL cards for:
- IEFBR14 (Dataset allocation and deletion)
- IEBGENER (Sequential copy)
- DFSORT (Sort, merge, and filter operations)
- IDCAMS (VSAM definitions, delete, and repro copy)
- Custom user-defined programs and steps

Guarantees:
- Output lines never exceed 71 code columns; continuation lines format with
  a trailing comma and column 16 alignment.
- Illustrative disclaimer banner included in generated comments.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class JobCard(BaseModel):
    job_name: str = Field(default="MYJOB01", max_length=8)
    accounting: str = Field(default="(ACCT#123)")
    programmer_name: str = Field(default="'SYSADMIN'")
    job_class: str = Field(default="A", max_length=1)
    msgclass: str = Field(default="X", max_length=1)
    msglevel: str = Field(default="(1,1)")
    notify: Optional[str] = Field(default="&SYSUID")
    region: Optional[str] = Field(default="0M")


class DdStatement(BaseModel):
    dd_name: str = Field(max_length=8)
    disp: Optional[str] = None
    dsn: Optional[str] = None
    space: Optional[str] = None
    unit: Optional[str] = None
    recfm: Optional[str] = None
    lrecl: Optional[int] = None
    blksize: Optional[int] = None
    sysout: Optional[str] = None
    dummy: bool = False
    instream_data: Optional[str] = None
    dlm: Optional[str] = None
    custom_params: Optional[str] = None


class JclStep(BaseModel):
    step_name: str = Field(default="STEP01", max_length=8)
    utility: Literal["IEFBR14", "IEBGENER", "DFSORT", "IDCAMS", "CUSTOM"] = "IEFBR14"
    pgm_override: Optional[str] = None
    comments: Optional[str] = None
    parm: Optional[str] = None
    region: Optional[str] = None
    cond: Optional[str] = None
    dds: List[DdStatement] = Field(default_factory=list)


class ManualBuildRequest(BaseModel):
    job: JobCard = Field(default_factory=JobCard)
    steps: List[JclStep] = Field(default_factory=list)
    include_header: bool = True


def wrap_operands(prefix: str, operands: List[str], max_col: int = 71, cont_indent: int = 13) -> List[str]:
    """Wraps JCL comma-separated operands across multiple lines so that no line exceeds max_col.
    
    prefix: e.g. "//JOBNAME  JOB " or "//DDNAME   DD   "
    cont_indent: default 13 spaces after "//", placing continuation operand at col 16 (1-indexed)
    """
    if not operands:
        return [prefix.rstrip()]

    lines: List[str] = []
    current_line = prefix
    cont_prefix = "//" + (" " * cont_indent)

    for i, op in enumerate(operands):
        is_last = (i == len(operands) - 1)
        suffix = "" if is_last else ","
        candidate = f"{op}{suffix}"

        # If adding candidate exceeds max_col, wrap to next line
        if len(current_line) + len(candidate) > max_col:
            # If current line has content beyond the prefix, end it with comma and wrap
            if current_line.endswith(","):
                lines.append(current_line)
                current_line = cont_prefix + candidate
            elif current_line.rstrip() == prefix.rstrip():
                # The operand itself is exceptionally long; append as is
                lines.append(current_line + candidate)
                current_line = cont_prefix
            else:
                lines.append(current_line + ",")
                current_line = cont_prefix + candidate
        else:
            current_line += candidate

    if current_line.strip() and current_line.strip() != "//":
        lines.append(current_line)

    return lines


def format_manual_jcl(req: ManualBuildRequest) -> str:
    """Renders formatted, 80-column compliant JCL from a structured ManualBuildRequest."""
    lines: List[str] = []

    # 1. Header Banner with Illustrative Disclaimer
    if req.include_header:
        lines.append("//**********************************************************************")
        lines.append("//* AI JCL STUDIO - ILLUSTRATIVE MAINFRAME JCL GENERATOR")
        lines.append("//* NOTE: Generated JCL is illustrative and must be validated in an")
        lines.append("//* actual z/OS environment before production execution.")
        lines.append("//**********************************************************************")

    # 2. JOB Card
    job = req.job
    job_name = (job.job_name or "MYJOB01").upper().strip()
    job_prefix = f"//{job_name:<8} JOB  "

    job_ops: List[str] = []
    if job.accounting:
        job_ops.append(job.accounting.strip())
    if job.programmer_name:
        job_ops.append(job.programmer_name.strip())
    if job.job_class:
        job_ops.append(f"CLASS={job.job_class.upper()}")
    if job.msgclass:
        job_ops.append(f"MSGCLASS={job.msgclass.upper()}")
    if job.msglevel:
        job_ops.append(f"MSGLEVEL={job.msglevel}")
    if job.notify:
        job_ops.append(f"NOTIFY={job.notify}")
    if job.region:
        job_ops.append(f"REGION={job.region}")

    lines.extend(wrap_operands(job_prefix, job_ops))

    # 3. Steps
    for step in req.steps:
        lines.append("//*")
        if step.comments:
            for comment_line in step.comments.splitlines():
                if comment_line.strip():
                    lines.append(f"//* {comment_line.strip()[:68]}")

        step_name = (step.step_name or "STEP01").upper().strip()
        pgm = (step.pgm_override or step.utility).upper().strip()
        exec_ops: List[str] = [f"PGM={pgm}"]
        if step.parm:
            exec_ops.append(f"PARM={step.parm.strip()}")
        if step.region:
            exec_ops.append(f"REGION={step.region.strip()}")
        if step.cond:
            exec_ops.append(f"COND={step.cond.strip()}")
        lines.extend(wrap_operands(f"//{step_name:<8} EXEC ", exec_ops))

        # DD Statements
        for dd in step.dds:
            dd_name = dd.dd_name.upper().strip()
            dd_prefix = f"//{dd_name:<8} DD   "

            if dd.dummy:
                lines.append(f"{dd_prefix}DUMMY")
                continue

            if dd.instream_data is not None:
                dlm_part = f",DLM={dd.dlm}" if dd.dlm else ""
                lines.append(f"{dd_prefix}*{dlm_part}")
                for data_line in dd.instream_data.splitlines():
                    # Ensure in-stream line doesn't exceed 80 columns
                    lines.append(data_line[:80])
                lines.append(dd.dlm if dd.dlm else "/*")
                continue

            # Standard dataset / sysout DD
            ops: List[str] = []
            if dd.dsn:
                ops.append(f"DSN={dd.dsn.strip()}")
            if dd.disp:
                ops.append(f"DISP={dd.disp.strip()}")
            if dd.sysout:
                ops.append(f"SYSOUT={dd.sysout.strip()}")
            if dd.unit:
                ops.append(f"UNIT={dd.unit.strip()}")
            if dd.space:
                ops.append(f"SPACE={dd.space.strip()}")

            # DCB parameters
            dcb_parts: List[str] = []
            if dd.recfm:
                dcb_parts.append(f"RECFM={dd.recfm.strip().upper()}")
            if dd.lrecl:
                dcb_parts.append(f"LRECL={dd.lrecl}")
            if dd.blksize is not None and dd.blksize > 0:
                dcb_parts.append(f"BLKSIZE={dd.blksize}")
            if dcb_parts:
                ops.append(f"DCB=({','.join(dcb_parts)})")

            if dd.custom_params:
                ops.append(dd.custom_params.strip())

            lines.extend(wrap_operands(dd_prefix, ops))

    lines.append("//")  # Null statement marking end of job stream
    return "\n".join(lines) + "\n"


def get_preset_templates() -> Dict[str, Any]:
    """Returns structured pre-configured templates for the 4 primary utilities."""
    return {
        "IEFBR14_ALLOCATE": {
            "title": "Allocate Sequential Dataset (IEFBR14)",
            "utility": "IEFBR14",
            "description": "Allocates a new fixed-block sequential dataset on DASD.",
            "request": {
                "job": {
                    "job_name": "ALLOCJOB",
                    "accounting": "(ACCT#123)",
                    "programmer_name": "'STORAGE.ADMIN'",
                    "job_class": "A",
                    "msgclass": "X",
                    "notify": "&SYSUID",
                    "region": "0M"
                },
                "steps": [
                    {
                        "step_name": "ALLOC01",
                        "utility": "IEFBR14",
                        "comments": "Allocate new sequential FB 80 dataset",
                        "dds": [
                            {
                                "dd_name": "NEWDS",
                                "dsn": "USER.SAMPLE.DATASET",
                                "disp": "(NEW,CATLG,DELETE)",
                                "unit": "SYSDA",
                                "space": "(CYL,(5,1),RLSE)",
                                "recfm": "FB",
                                "lrecl": 80,
                                "blksize": 0
                            }
                        ]
                    }
                ]
            }
        },
        "IEFBR14_DELETE": {
            "title": "Clean/Delete Dataset (IEFBR14)",
            "utility": "IEFBR14",
            "description": "Conditionally deletes a dataset if it exists prior to creation.",
            "request": {
                "job": {
                    "job_name": "DELJOB01",
                    "accounting": "(ACCT#123)",
                    "programmer_name": "'CLEANUP'",
                    "job_class": "A",
                    "msgclass": "X",
                    "notify": "&SYSUID"
                },
                "steps": [
                    {
                        "step_name": "CLEAN01",
                        "utility": "IEFBR14",
                        "comments": "Delete dataset if it exists; no error if absent",
                        "dds": [
                            {
                                "dd_name": "DELDS",
                                "dsn": "USER.TARGET.DATASET",
                                "disp": "(MOD,DELETE,DELETE)",
                                "unit": "SYSDA",
                                "space": "(TRK,0)"
                            }
                        ]
                    }
                ]
            }
        },
        "IEBGENER_COPY": {
            "title": "Copy Sequential Dataset (IEBGENER)",
            "utility": "IEBGENER",
            "description": "Standard sequential copy with required SYSUT1, SYSUT2, SYSPRINT, SYSIN.",
            "request": {
                "job": {
                    "job_name": "COPYJOB",
                    "accounting": "(ACCT#123)",
                    "programmer_name": "'DATA.OPS'",
                    "job_class": "A",
                    "msgclass": "X",
                    "notify": "&SYSUID"
                },
                "steps": [
                    {
                        "step_name": "COPY01",
                        "utility": "IEBGENER",
                        "comments": "Copy input dataset SYSUT1 to output dataset SYSUT2",
                        "dds": [
                            {
                                "dd_name": "SYSUT1",
                                "dsn": "USER.INPUT.DATA",
                                "disp": "SHR"
                            },
                            {
                                "dd_name": "SYSUT2",
                                "dsn": "USER.OUTPUT.COPY",
                                "disp": "(NEW,CATLG,DELETE)",
                                "unit": "SYSDA",
                                "space": "(CYL,(10,2),RLSE)",
                                "recfm": "FB",
                                "lrecl": 80,
                                "blksize": 0
                            },
                            {
                                "dd_name": "SYSPRINT",
                                "sysout": "*"
                            },
                            {
                                "dd_name": "SYSIN",
                                "dummy": True
                            }
                        ]
                    }
                ]
            }
        },
        "DFSORT_SORT": {
            "title": "Sort Records by Key (DFSORT)",
            "utility": "DFSORT",
            "description": "Sort input records in ascending order with work files and SYSIN control cards.",
            "request": {
                "job": {
                    "job_name": "SORTJOB",
                    "accounting": "(ACCT#123)",
                    "programmer_name": "'BATCH.SORT'",
                    "job_class": "A",
                    "msgclass": "X",
                    "notify": "&SYSUID"
                },
                "steps": [
                    {
                        "step_name": "SORT01",
                        "utility": "DFSORT",
                        "comments": "Sort input by columns 1-10 ascending character key",
                        "dds": [
                            {
                                "dd_name": "SORTIN",
                                "dsn": "USER.UNSORTED.DATA",
                                "disp": "SHR"
                            },
                            {
                                "dd_name": "SORTOUT",
                                "dsn": "USER.SORTED.DATA",
                                "disp": "(NEW,CATLG,DELETE)",
                                "unit": "SYSDA",
                                "space": "(CYL,(15,5),RLSE)",
                                "recfm": "FB",
                                "lrecl": 80,
                                "blksize": 0
                            },
                            {
                                "dd_name": "SORTWK01",
                                "unit": "SYSDA",
                                "space": "(CYL,(10,5))"
                            },
                            {
                                "dd_name": "SORTWK02",
                                "unit": "SYSDA",
                                "space": "(CYL,(10,5))"
                            },
                            {
                                "dd_name": "SYSOUT",
                                "sysout": "*"
                            },
                            {
                                "dd_name": "SYSIN",
                                "instream_data": "  SORT FIELDS=(1,10,CH,A)\n  RECORD FORMAT=FB,LENGTH=80"
                            }
                        ]
                    }
                ]
            }
        },
        "IDCAMS_DEFINE_CLUSTER": {
            "title": "Define VSAM KSDS Cluster (IDCAMS)",
            "utility": "IDCAMS",
            "description": "Deletes existing cluster then defines a new indexed VSAM KSDS dataset.",
            "request": {
                "job": {
                    "job_name": "IDCAMJOB",
                    "accounting": "(ACCT#123)",
                    "programmer_name": "'VSAM.ADMIN'",
                    "job_class": "A",
                    "msgclass": "X",
                    "notify": "&SYSUID"
                },
                "steps": [
                    {
                        "step_name": "DEFCLUST",
                        "utility": "IDCAMS",
                        "comments": "Define VSAM Key-Sequenced Dataset (KSDS)",
                        "dds": [
                            {
                                "dd_name": "SYSPRINT",
                                "sysout": "*"
                            },
                            {
                                "dd_name": "SYSIN",
                                "instream_data": (
                                    "  DELETE USER.SAMPLE.KSDS CLUSTER PURGE\n"
                                    "  SET MAXCC = 0\n"
                                    "  DEFINE CLUSTER (NAME(USER.SAMPLE.KSDS) -\n"
                                    "         INDEXED -\n"
                                    "         KEYS(10 0) -\n"
                                    "         RECORDSIZE(80 80) -\n"
                                    "         CYLINDERS(5 1) -\n"
                                    "         SHAREOPTIONS(2 3)) -\n"
                                    "         DATA (NAME(USER.SAMPLE.KSDS.DATA)) -\n"
                                    "         INDEX (NAME(USER.SAMPLE.KSDS.INDEX))"
                                )
                            }
                        ]
                    }
                ]
            }
        },
        "IDCAMS_REPRO": {
            "title": "REPRO Backup VSAM to Sequential (IDCAMS)",
            "utility": "IDCAMS",
            "description": "Copies VSAM cluster records into a sequential flat file.",
            "request": {
                "job": {
                    "job_name": "REPROJOB",
                    "accounting": "(ACCT#123)",
                    "programmer_name": "'BACKUP.OPS'",
                    "job_class": "A",
                    "msgclass": "X",
                    "notify": "&SYSUID"
                },
                "steps": [
                    {
                        "step_name": "REPRO01",
                        "utility": "IDCAMS",
                        "comments": "Backup VSAM KSDS to flat sequential dataset",
                        "dds": [
                            {
                                "dd_name": "SYSPRINT",
                                "sysout": "*"
                            },
                            {
                                "dd_name": "SYSIN",
                                "instream_data": "  REPRO INDATASET(USER.SAMPLE.KSDS) -\n        OUTDATASET(USER.BACKUP.FLAT)"
                            }
                        ]
                    }
                ]
            }
        }
    }

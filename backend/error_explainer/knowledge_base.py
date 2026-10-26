"""Authoritative local knowledge base of IBM z/OS system abends, user abends, return codes, and utility messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ErrorKnowledgeEntry:
    code: str
    category: str
    severity: str
    title: str
    description: str
    likely_causes: List[str]
    troubleshooting_steps: List[str]
    ibm_reference: str = "IBM z/OS MVS System Codes (SA38-0665)"
    reason_codes: Dict[str, str] = field(default_factory=dict)
    caveats: Optional[str] = None


KNOWLEDGE_BASE: Dict[str, ErrorKnowledgeEntry] = {
    # -------------------------------------------------------------------------
    # System ABENDs
    # -------------------------------------------------------------------------
    "S806": ErrorKnowledgeEntry(
        code="S806",
        category="abend",
        severity="error",
        title="Program Loading Failure (Load Module Not Found)",
        description="The system attempted to load an executable module specified on an EXEC statement or via LINK/LOAD/ATTACH, but the module could not be found.",
        likely_causes=[
            "Requested program could not be located or loaded",
            "Load library may be missing or incorrectly configured (missing STEPLIB or JOBLIB)",
            "Typo in the EXEC statement PGM parameter",
            "Program module resides in a dataset not included in LNKLST or LPALST",
            "Dataset containing load module is uncataloged or volume offline",
        ],
        troubleshooting_steps=[
            "Verify the EXEC PGM name matches the intended load module member exactly",
            "Check STEPLIB and JOBLIB DD statements in the job step",
            "Confirm the load module member exists in the partitioned dataset (PDS/PDSE)",
            "Verify the user/job has READ permission to the load library",
            "Ensure concatenated STEPLIB libraries are properly ordered and cataloged",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S806",
        reason_codes={
            "00000004": "The program was not found in the indicated private library, JOBLIB, STEPLIB, LPA, or LNKLST.",
            "04": "The program was not found in the indicated private library, JOBLIB, STEPLIB, LPA, or LNKLST.",
            "00000008": "An uncorrectable I/O error occurred during directory search.",
            "08": "An uncorrectable I/O error occurred during directory search.",
            "0000000C": "An authorized program attempted to load an unauthorized module from an unauthorized library.",
            "0C": "An authorized program attempted to load an unauthorized module from an unauthorized library.",
        },
    ),
    "S0C7": ErrorKnowledgeEntry(
        code="S0C7",
        category="abend",
        severity="error",
        title="Data Exception (Invalid Packed Decimal Data)",
        description="A decimal calculation or conversion instruction encountered non-numeric or improperly formatted packed decimal (COMP-3) data in an accumulator or field.",
        likely_causes=[
            "Uninitialized numeric or packed-decimal (COMP-3) field containing spaces (X'40') or low-values (X'00')",
            "Alphanumeric characters accidentally placed into a numeric calculation field",
            "File record layout mismatch: input record format does not match application copybook",
            "Subscript/index calculation pointing beyond valid record boundaries",
        ],
        troubleshooting_steps=[
            "Inspect the offset indicated in the SYSOUT/SYSUDUMP to locate the failing COBOL/PL/I statement",
            "Check input dataset fields for low-values, spaces, or corrupt non-numeric bytes",
            "Verify the record length (LRECL) and copybook offsets match the physical file layout",
            "Initialize all working-storage accumulator variables before arithmetic operations",
            "Use NUMERIC class tests before performing calculations on external input data",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S0C7",
    ),
    "S0C4": ErrorKnowledgeEntry(
        code="S0C4",
        category="abend",
        severity="error",
        title="Protection Exception / Storage Addressing Error",
        description="A program attempted to access or reference a virtual storage address that is either not allocated to the address space or protected with a storage key mismatch.",
        likely_causes=[
            "Array or table subscript/index went beyond defined table bounds",
            "Uninitialized pointer or invalid reference variable in application code",
            "Missing DD statement for a file opened by the application, causing null pointer dereference",
            "Calling a subprogram with incorrect or missing parameter list (CALL ... USING)",
            "Attempting to modify read-only or reentrant storage",
        ],
        troubleshooting_steps=[
            "Verify all table subscripts and OCCURS indexes are within declared range",
            "Confirm all parameters passed in CALL statements match the subprogram LINKAGE SECTION",
            "Ensure all required input and output DD statements are present in the JCL step",
            "Review the abend displacement and register values in the CEEDUMP or SYSUDUMP",
            "Check pointer initialization and dynamic memory allocations",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S0C4",
    ),
    "S0C1": ErrorKnowledgeEntry(
        code="S0C1",
        category="abend",
        severity="error",
        title="Operation Exception (Invalid Machine Instruction)",
        description="The processor attempted to execute a machine instruction with an invalid operation code, typically caused by branching into data or unallocated memory.",
        likely_causes=[
            "Branching or calling an uninitialized entry point address",
            "Overwriting the return address on the program call stack",
            "Failing to close or check return code from OPEN macro before reading file",
            "Executing data bytes as machine instructions due to missing branch/exit logic",
        ],
        troubleshooting_steps=[
            "Check that dynamic subprograms called by the step were successfully linked and loaded",
            "Examine the entry point address and call stack in CEEDUMP",
            "Ensure subprogram return statements (GOBACK, STOP RUN) are properly coded",
            "Check for buffer overflow corrupting executable instructions",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S0C1",
    ),
    "S013": ErrorKnowledgeEntry(
        code="S013",
        category="abend",
        severity="error",
        title="OPEN Macro Failure / Dataset Conflict",
        description="An error occurred during OPEN processing for a dataset. Common causes include DCB conflicts, BLKSIZE errors, or missing PDS members.",
        likely_causes=[
            "DCB parameter conflict between JCL and dataset label (e.g. BLKSIZE not multiple of LRECL for FB)",
            "Specified member does not exist in the partitioned dataset (PDS/PDSE)",
            "Attempting to open a sequential dataset with member syntax (DSN=dataset(member))",
            "Record format (RECFM) mismatch between program DCB and dataset DSCB",
        ],
        troubleshooting_steps=[
            "Verify the member name in DSN=dataset(member) exists in the PDS directory",
            "Ensure BLKSIZE is an exact integer multiple of LRECL for fixed-block (FB) datasets",
            "Check the DD statement DCB parameters against the physical dataset attributes",
            "Examine IEC141I console message for the specific reason code (e.g. 18 = member not found)",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S013",
        reason_codes={
            "18": "The member specified in the JCL DD statement was not found in the partitioned dataset.",
            "20": "An I/O error occurred reading the directory of the partitioned dataset.",
            "34": "The block size (BLKSIZE) specified is not a multiple of the record length (LRECL) for fixed-length records.",
        },
    ),
    "S322": ErrorKnowledgeEntry(
        code="S322",
        category="abend",
        severity="error",
        title="CPU Time Limit Exceeded",
        description="The job or job step exceeded the maximum allowable CPU time specified in the JCL TIME parameter or system JES installation default.",
        likely_causes=[
            "Application program entered an infinite processing loop (e.g. PERFORM UNTIL condition never met)",
            "JCL TIME parameter on JOB or EXEC statement is set too low for volume of data processed",
            "Inefficient database query or nested table lookup consuming excessive CPU cycles",
            "I/O wait condition looping continuously on file end-of-record",
        ],
        troubleshooting_steps=[
            "Inspect application logic for infinite loop conditions and loop counters",
            "Increase the TIME parameter on the EXEC statement (e.g. TIME=(5,0) or TIME=1440 for testing)",
            "Review SMF job execution records to determine typical CPU consumption for this job",
            "Profile application algorithm and index access paths",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S322",
    ),
    "S837": ErrorKnowledgeEntry(
        code="S837",
        category="abend",
        severity="error",
        title="End of Volume / Space Allocation Failure",
        description="An error occurred during end-of-volume processing. The system was unable to allocate additional space extents for a dataset on DASD or tape.",
        likely_causes=[
            "Dataset reached maximum of 16 extents on a non-SMS managed DASD volume and secondary allocation failed",
            "Target DASD volume has insufficient contiguous free space for secondary space extent",
            "No secondary space allocation parameter was specified in SPACE=(unit,(pri,sec))",
            "Multi-volume dataset exceeded the maximum allowed number of volumes",
        ],
        troubleshooting_steps=[
            "Increase primary or secondary space allocation parameters on the target DD statement",
            "Enable secondary allocation (e.g. SPACE=(CYL,(50,20),RLSE))",
            "Direct the dataset to an SMS storage group with adequate volume capacity",
            "Delete or archive old, unneeded generations or datasets on the target DASD pool",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S837",
    ),
    "S878": ErrorKnowledgeEntry(
        code="S878",
        category="abend",
        severity="error",
        title="Virtual Storage Exhausted (GETMAIN/STORAGE Failure)",
        description="The system was unable to satisfy a request for virtual storage (GETMAIN or STORAGE OBTAIN) in the user address space private area.",
        likely_causes=[
            "REGION parameter on JOB or EXEC statement is too small for application requirements",
            "Application memory leak repeatedly allocating storage without FREEMAIN",
            "Large internal working tables or in-memory sort workspace exceeding 24-bit/31-bit address space limits",
        ],
        troubleshooting_steps=[
            "Increase the REGION parameter on the EXEC or JOB statement (e.g. REGION=64M or REGION=0M)",
            "Review application storage allocations and ensure dynamically allocated buffers are freed",
            "Relocate large data tables to 64-bit memory (above the 2GB bar) if supported",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S878",
    ),
    "S913": ErrorKnowledgeEntry(
        code="S913",
        category="abend",
        severity="error",
        title="Security / RACF Authorization Failure",
        description="A program or user attempted to access a protected dataset or system resource without adequate SAF/RACF security authorization.",
        likely_causes=[
            "The submitting user ID lacks READ, UPDATE, or ALTER permission for the dataset profile in RACF",
            "Dataset password or volume password validation failed",
            "Job submitted under generic or unauthorized RACF group profile",
            "Target dataset belongs to a secure production HLQ protected by strict security rules",
        ],
        troubleshooting_steps=[
            "Inspect the ICH408I message in the job log for the exact user ID, dataset name, and access level required",
            "Request appropriate RACF dataset permission (READ/UPDATE) from security administrator",
            "Verify the USER and PASSWORD/GROUP parameters on the JOB statement",
            "Confirm whether execution requires a surrogate or production service ID",
        ],
        ibm_reference="z/OS MVS System Codes (SA38-0665) - S913",
    ),

    # -------------------------------------------------------------------------
    # User ABENDs
    # -------------------------------------------------------------------------
    "U4038": ErrorKnowledgeEntry(
        code="U4038",
        category="user_abend",
        severity="error",
        title="Language Environment (LE) Unhandled Condition Abend",
        description="Language Environment (LE) terminated the enclave with abend U4038 because an application condition of severity 2 or greater went unhandled.",
        likely_causes=[
            "A critical application error occurred (such as S0C7, S0C4, or divide-by-zero) and no ON ERROR or condition handler intercepted it",
            "COBOL program executed a STOP RUN with severe error status or abnormal termination",
            "Missing runtime library or incompatible LE compiler options",
        ],
        troubleshooting_steps=[
            "Inspect the CEEDUMP or SYSOUT for the underlying condition message (e.g. CEE3207S, CEE3204S)",
            "Locate the failing source code line number in the Language Environment condition report",
            "Fix the root application defect (such as data exception or subscript range violation)",
            "Verify LE runtime options (e.g. TRAP(ON,NOSPIE), ABTERMENC(ABEND))",
        ],
        ibm_reference="IBM Language Environment Debugging Guide (GA32-0908)",
    ),
    "U4083": ErrorKnowledgeEntry(
        code="U4083",
        category="user_abend",
        severity="error",
        title="Language Environment Storage Initialization Failure",
        description="Language Environment was unable to initialize required runtime storage pools or user heap.",
        likely_causes=[
            "REGION parameter is too small to initialize the Language Environment runtime enclave",
            "Conflicting HEAP or STACK runtime parameters",
        ],
        troubleshooting_steps=[
            "Increase the REGION parameter on the EXEC statement (e.g. REGION=64M)",
            "Check LE runtime parameter overrides in CEEOPTS DD",
        ],
        ibm_reference="IBM Language Environment Debugging Guide (GA32-0908)",
    ),

    # -------------------------------------------------------------------------
    # JCL and JES Messages
    # -------------------------------------------------------------------------
    "IEF450I": ErrorKnowledgeEntry(
        code="IEF450I",
        category="system_message",
        severity="error",
        title="Job Step Abnormal Termination",
        description="JES/MVS system message indicating that a job step terminated abnormally with a system or user ABEND code.",
        likely_causes=[
            "The program executed in the step suffered an unhandled system or user abend",
            "Resource allocation or catalog management error forced abnormal termination",
        ],
        troubleshooting_steps=[
            "Check the ABEND code (e.g. ABEND=S806) and REASON code reported in the message",
            "Review preceding SYSOUT, SYSPRINT, and system messages for the failing step",
            "Check the specific ABEND documentation for detailed corrective action",
        ],
        ibm_reference="z/OS MVS System Messages Vol 8 (SA38-0675) - IEF450I",
    ),
    "IEF452I": ErrorKnowledgeEntry(
        code="IEF452I",
        category="jcl_error",
        severity="error",
        title="Job Failed - JCL Error",
        description="The job was not executed because the JCL converter or interpreter detected syntax, parameter, or dataset catalog errors.",
        likely_causes=[
            "JCL syntax error (misspelled parameter, missing comma, unmatched parenthesis)",
            "Dataset referenced with DISP=OLD/SHR is not cataloged in the system catalog",
            "Duplicate DD statement name within the same job step",
            "Statement exceeds 80 columns or continuation format is broken",
        ],
        troubleshooting_steps=[
            "Inspect JESYSMSG for specific converter/interpreter error messages (e.g. IEFC6xxI)",
            "Verify all referenced input datasets are cataloged using IDCAMS LISTCAT",
            "Check syntax on the failing JCL statement highlighted in the job log",
            "Run JCL through JCL Studio AI static validator to resolve syntax issues prior to resubmission",
        ],
        ibm_reference="z/OS MVS System Messages Vol 8 (SA38-0675) - IEF452I",
    ),
    "IEF142I": ErrorKnowledgeEntry(
        code="IEF142I",
        category="system_message",
        severity="info",
        title="Step Executed - Step Completion Status",
        description="System message indicating that a job step executed and completed with the indicated condition code (COND CODE).",
        likely_causes=[
            "Normal step completion with return code (RC=0000 indicates success)",
            "Non-zero return code indicates application warnings (RC=0004) or errors (RC=0008, RC=0012)",
        ],
        troubleshooting_steps=[
            "Check the numeric COND CODE value; 0000 represents normal completion",
            "For non-zero condition codes, review the step output (SYSPRINT, SYSOUT)",
            "Verify whether subsequent steps with COND=(code,...) evaluated as expected",
        ],
        ibm_reference="z/OS MVS System Messages Vol 8 (SA38-0675) - IEF142I",
    ),
    "IEFC001I": ErrorKnowledgeEntry(
        code="IEFC001I",
        category="jcl_error",
        severity="error",
        title="JCL Syntax Error / Parameter Conflict",
        description="Converter/interpreter message indicating an unrecognized parameter, keyword error, or column format violation on a JCL statement.",
        likely_causes=[
            "Unrecognized keyword parameter on JOB, EXEC, or DD statement",
            "Missing space between operation and parameters",
            "Statement name exceeds 8 characters",
        ],
        troubleshooting_steps=[
            "Verify keyword spelling against IBM z/OS JCL Reference",
            "Check that statement name is 1-8 alphanumeric/national characters",
            "Ensure parameters start after column 3 space on continuation lines",
        ],
        ibm_reference="z/OS MVS System Messages Vol 8 (SA38-0675)",
    ),

    # -------------------------------------------------------------------------
    # Return Codes
    # -------------------------------------------------------------------------
    "RC=0000": ErrorKnowledgeEntry(
        code="RC=0000",
        category="return_code",
        severity="info",
        title="Normal Successful Completion (RC=0)",
        description="The step or utility completed successfully with no errors or warnings.",
        likely_causes=["All operations executed as intended without errors."],
        troubleshooting_steps=["No action required."],
        ibm_reference="IBM z/OS Standard Return Codes",
    ),
    "RC=0004": ErrorKnowledgeEntry(
        code="RC=0004",
        category="return_code",
        severity="warning",
        title="Informational Warning (RC=4)",
        description="The step or utility completed successfully with minor warnings or empty datasets.",
        likely_causes=[
            "Utility processed an empty dataset or table",
            "Compiler detected minor warnings (e.g. unused variables)",
            "IDCAMS completed an operation with minor non-fatal warnings",
        ],
        troubleshooting_steps=[
            "Review SYSPRINT/SYSOUT messages to confirm warnings are acceptable",
            "Verify whether subsequent steps expect RC=0 or can tolerate RC=4",
        ],
        ibm_reference="IBM z/OS Standard Return Codes",
    ),
    "RC=0008": ErrorKnowledgeEntry(
        code="RC=0008",
        category="return_code",
        severity="warning",
        title="Warning / Significant Condition (RC=8)",
        description="The step or utility completed with significant warnings or discrepancies. Subsequent processing may be impacted.",
        likely_causes=[
            "Compiler detected syntax or semantic errors resulting in code generation caveats",
            "IDCAMS encountered an object that did not match search criteria",
            "DFSORT encountered duplicate keys when unique keys were expected",
        ],
        troubleshooting_steps=[
            "Examine message logs (SYSPRINT, SYSOUT) for specific diagnostic codes",
            "Verify output datasets before relying on downstream steps",
        ],
        ibm_reference="IBM z/OS Standard Return Codes",
    ),
    "RC=0012": ErrorKnowledgeEntry(
        code="RC=0012",
        category="return_code",
        severity="error",
        title="Severe Error / Execution Failure (RC=12)",
        description="The step or utility suffered a severe error and could not complete processing successfully.",
        likely_causes=[
            "Severe compilation errors prevented load module creation",
            "IDCAMS command syntax error or failed dataset definition",
            "Missing essential DD statement or unrecoverable dataset I/O condition",
        ],
        troubleshooting_steps=[
            "Inspect SYSPRINT/SYSOUT for detailed utility error messages",
            "Correct the failing control statement or missing dataset",
            "Rerun the job step after fixing the reported cause",
        ],
        ibm_reference="IBM z/OS Standard Return Codes",
    ),
    "RC=0016": ErrorKnowledgeEntry(
        code="RC=0016",
        category="return_code",
        severity="error",
        title="Critical Error / Disaster Condition (RC=16)",
        description="The utility or application terminated due to an irrecoverable disaster condition or missing fundamental resource.",
        likely_causes=[
            "Severe internal catalog corruption or unrecoverable I/O failure",
            "Fatal system resource failure",
        ],
        troubleshooting_steps=[
            "Review console log and system programmer message output",
            "Verify volume and catalog integrity with system programmer",
        ],
        ibm_reference="IBM z/OS Standard Return Codes",
    ),

    # -------------------------------------------------------------------------
    # Utility Messages
    # -------------------------------------------------------------------------
    "ICE083A": ErrorKnowledgeEntry(
        code="ICE083A",
        category="utility",
        severity="error",
        title="DFSORT Missing or Inaccessible SORTIN Dataset",
        description="DFSORT was unable to open or read the input dataset specified by the SORTIN DD statement.",
        likely_causes=[
            "SORTIN DD statement is missing from the EXEC step",
            "SORTIN dataset is uncataloged or volume is inaccessible",
            "Dataset specified on SORTIN is empty and NOWORK option was not set",
        ],
        troubleshooting_steps=[
            "Ensure //SORTIN DD DSN=...,DISP=SHR is present in the DFSORT step",
            "Verify the input dataset is cataloged and contains records",
        ],
        ibm_reference="IBM DFSORT Messages, Codes and Diagnosis Guide (SC23-6885)",
    ),
    "ICE043A": ErrorKnowledgeEntry(
        code="ICE043A",
        category="utility",
        severity="error",
        title="DFSORT Invalid Control Statement Syntax",
        description="DFSORT detected a syntax error in the SYSIN control statement stream.",
        likely_causes=[
            "Invalid SORT FIELDS parameters (e.g. wrong count, invalid format code, or missing order)",
            "Control card begins in column 1 instead of columns 2-71",
            "Unclosed parenthesis or unmatched quote in control cards",
        ],
        troubleshooting_steps=[
            "Review the SORT FIELDS statement syntax in SYSIN DD *",
            "Ensure control cards start in column 2 or later (column 1 must be blank)",
            "Check field boundaries (start, length, format, order) against input LRECL",
        ],
        ibm_reference="IBM DFSORT Messages, Codes and Diagnosis Guide (SC23-6885)",
    ),
    "IDC3009I": ErrorKnowledgeEntry(
        code="IDC3009I",
        category="utility",
        severity="error",
        title="IDCAMS VSAM Catalog Management Error",
        description="An error occurred during catalog management service processing for a VSAM dataset or catalog request.",
        likely_causes=[
            "Duplicate dataset name already exists in catalog",
            "Target catalog is locked or has insufficient space",
            "Invalid volume serial or device type specified for cluster",
        ],
        troubleshooting_steps=[
            "Check the return code and reason code inside the IDC3009I message",
            "If duplicate entry, add DELETE before DEFINE CLUSTER or verify DSN",
            "Confirm target catalog has sufficient space extents",
        ],
        ibm_reference="z/OS MVS System Messages Vol 6 (SA38-0673) - IDC3009I",
    ),
    "IEB311I": ErrorKnowledgeEntry(
        code="IEB311I",
        category="utility",
        severity="error",
        title="IEBGENER Conflicting DCB Parameters",
        description="IEBGENER detected conflicting record formats or block sizes between SYSUT1 (input) and SYSUT2 (output).",
        likely_causes=[
            "SYSUT1 has fixed-block (FB) records while SYSUT2 specifies variable (VB) records",
            "SYSUT2 LRECL does not match SYSUT1 LRECL",
        ],
        troubleshooting_steps=[
            "Ensure SYSUT2 DCB matches SYSUT1 attributes (RECFM, LRECL)",
            "Omit DCB on SYSUT2 to let IEBGENER inherit attributes from SYSUT1",
        ],
        ibm_reference="z/OS DFSMSdfp Utilities (SC23-6864) - IEBGENER",
    ),
}


def lookup_error_knowledge(code: str) -> Optional[ErrorKnowledgeEntry]:
    """Look up an error in the local knowledge base by exact code or normalized code."""
    if not code:
        return None
    norm = code.strip().upper()
    # Direct match
    if norm in KNOWLEDGE_BASE:
        return KNOWLEDGE_BASE[norm]

    # Try standard prefixes
    if not norm.startswith("S") and f"S{norm}" in KNOWLEDGE_BASE:
        return KNOWLEDGE_BASE[f"S{norm}"]
    if not norm.startswith("RC=") and f"RC={norm}" in KNOWLEDGE_BASE:
        return KNOWLEDGE_BASE[f"RC={norm}"]

    # Return Code format check: e.g. 0012 -> RC=0012
    if norm.isdigit() and len(norm) <= 4:
        padded = f"RC={norm.zfill(4)}"
        if padded in KNOWLEDGE_BASE:
            return KNOWLEDGE_BASE[padded]

    return None

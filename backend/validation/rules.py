"""General JCL structural and dataset parameter validation rules."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.validation.models import Diagnostic, Severity
from backend.validation.parser import LogicalStatement, ParsedJcl, split_comma_parameters
from backend.validation.registry import find_close_program_match, is_known_program

VALID_DISP_STATUS = {"NEW", "OLD", "SHR", "MOD"}
VALID_NORMAL_DISP = {"DELETE", "KEEP", "PASS", "CATLG", "UNCATLG"}
VALID_ABEND_DISP = {"DELETE", "KEEP", "CATLG", "UNCATLG"}
VALID_RECFM_PREFIXES = {"F", "FB", "FS", "FBS", "FA", "FM", "V", "VB", "VS", "VBS", "VA", "VM", "U"}
VALID_SPACE_UNITS = {"TRK", "CYL", "ABSTR"}


def find_program_position(stmt: LogicalStatement, prog: str) -> Tuple[int, int]:
    """Dynamically calculates the 1-indexed (line, column) of a program name within physical source lines."""
    for line_num, line_str in stmt.physical_lines:
        pattern = r"\bPGM\s*=\s*['\"]?" + re.escape(prog) + r"['\"]?"
        m = re.search(pattern, line_str, re.IGNORECASE)
        if m:
            prog_offset = m.group(0).upper().find(prog.upper())
            return line_num, m.start() + prog_offset + 1
        m_bare = re.search(r"\b" + re.escape(prog) + r"\b", line_str, re.IGNORECASE)
        if m_bare:
            return line_num, m_bare.start() + 1
    return stmt.start_line, stmt.operands_column or 1


def find_empty_pgm_position(stmt: LogicalStatement) -> Tuple[int, int]:
    """Dynamically calculates the 1-indexed (line, column) of an empty PGM= parameter."""
    for line_num, line_str in stmt.physical_lines:
        m = re.search(r"\bPGM\s*=", line_str, re.IGNORECASE)
        if m:
            return line_num, m.end() + 1
    return stmt.start_line, stmt.operands_column or 1


def validate_general_jcl_rules(parsed: ParsedJcl) -> List[Diagnostic]:
    """Applies general JCL validation rules across all statements in the job."""
    diagnostics: List[Diagnostic] = []

    # 1. Structure: JOB and EXEC statement presence
    has_job = any(s.statement_type == "JOB" for s in parsed.statements)
    has_exec = any(s.statement_type == "EXEC" for s in parsed.statements)

    if not has_job:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="NO_JOB_STATEMENT",
                line=1 if parsed.raw_lines else 1,
                column=1,
                message="No JOB statement detected.",
                suggested_fix="Add a valid JOB statement at the start of the JCL stream (e.g. //MYJOB JOB (ACCT#123),'USER',CLASS=A).",
            )
        )

    if not has_exec:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="NO_EXEC_STATEMENT",
                line=1 if parsed.raw_lines else 1,
                column=1,
                message="No EXEC statement detected.",
                suggested_fix="Add an EXEC statement to specify the program or procedure to execute (e.g. //STEP01 EXEC PGM=IEFBR14).",
            )
        )

    # 2. Duplicate Step Names
    step_names: Dict[str, List[int]] = {}
    current_step_name: Optional[str] = None
    step_dd_names: Dict[str, Dict[str, List[int]]] = {}

    for stmt in parsed.statements:
        if stmt.statement_type == "EXEC":
            step_name = stmt.name.upper()
            if step_name:
                step_names.setdefault(step_name, []).append(stmt.start_line)
                current_step_name = step_name
                step_dd_names[step_name] = {}
            else:
                current_step_name = f"_UNNAMED_STEP_{stmt.start_line}"
                step_dd_names[current_step_name] = {}

            # Validate EXEC operands (must have PGM=, PROC=, or positional proc)
            has_pgm = "PGM" in stmt.keyword_params
            has_proc = "PROC" in stmt.keyword_params
            has_pos_proc = bool(stmt.positional_params and not stmt.positional_params[0].startswith("("))

            if not (has_pgm or has_proc or has_pos_proc):
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        rule_id="EXEC_MISSING_PROGRAM_OR_PROC",
                        line=stmt.start_line,
                        column=stmt.operands_column or 1,
                        message=f"Line {stmt.start_line}: EXEC statement '{stmt.name}' must specify PGM=program_name or PROC=proc_name.",
                        suggested_fix="Specify PGM=... (e.g. //STEP01 EXEC PGM=IEFBR14).",
                    )
                )
            elif has_pgm:
                raw_pgm = stmt.keyword_params.get("PGM", "")
                clean_pgm = raw_pgm.strip("'\"").strip()
                if not clean_pgm:
                    err_line, err_col = find_empty_pgm_position(stmt)
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            rule_id="MISSING_PROGRAM_NAME",
                            line=err_line,
                            column=err_col,
                            message=f"Line {err_line}: PGM parameter on EXEC statement '{stmt.name}' cannot be empty.",
                            suggested_fix="Specify a valid program name (e.g. PGM=IEFBR14).",
                        )
                    )
                else:
                    suggestion = find_close_program_match(clean_pgm)
                    if suggestion:
                        warn_line, warn_col = find_program_position(stmt, clean_pgm)
                        diagnostics.append(
                            Diagnostic(
                                severity=Severity.WARNING,
                                rule_id="SUSPICIOUS_PROGRAM_NAME",
                                line=warn_line,
                                column=warn_col,
                                message=f"Program {clean_pgm} is not in the configured registry. Did you mean {suggestion}?",
                                suggested_fix=f"Verify the program name or change PGM={clean_pgm} to PGM={suggestion}.",
                            )
                        )
            elif has_pos_proc and not has_proc:
                raw_pos = stmt.positional_params[0].strip("'\"").strip()
                if raw_pos:
                    suggestion = find_close_program_match(raw_pos)
                    if suggestion:
                        warn_line, warn_col = find_program_position(stmt, raw_pos)
                        diagnostics.append(
                            Diagnostic(
                                severity=Severity.WARNING,
                                rule_id="SUSPICIOUS_PROGRAM_NAME",
                                line=warn_line,
                                column=warn_col,
                                message=f"Program {raw_pos} is not in the configured registry. Did you mean {suggestion}?",
                                suggested_fix=f"Verify the program name or change PGM={raw_pos} to PGM={suggestion}.",
                            )
                        )

        elif stmt.statement_type == "DD":
            # Track DD names within current step to detect duplicate DDs
            dd_name = stmt.name.upper()
            if current_step_name and dd_name:
                # Unnamed DD is valid concatenation, non-empty DD must be unique in step
                step_dd_names[current_step_name].setdefault(dd_name, []).append(stmt.start_line)

            # Validate DD parameters
            diagnostics.extend(validate_dd_parameters(stmt))

        elif stmt.statement_type == "JOB":
            if not stmt.name:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        rule_id="JOB_NAME_MISSING",
                        line=stmt.start_line,
                        column=3,
                        message=f"Line {stmt.start_line}: JOB statement is missing a job name.",
                        suggested_fix="Provide a 1-8 character job name (e.g. //MYJOB01 JOB ...).",
                    )
                )

    # Check for duplicate steps
    for s_name, lines in step_names.items():
        if len(lines) > 1:
            line_str = ", ".join(str(l) for l in lines)
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="DUPLICATE_STEP_NAME",
                    line=lines[1],
                    column=3,
                    message=f"Duplicate step name '{s_name}' detected on lines {line_str}. Step names must be unique within a job.",
                    suggested_fix=f"Rename duplicate step '{s_name}' on line {lines[1]} to a unique name.",
                )
            )

    # Check for duplicate DD names within steps
    for s_name, dds in step_dd_names.items():
        for d_name, lines in dds.items():
            if len(lines) > 1:
                line_str = ", ".join(str(l) for l in lines)
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        rule_id="DUPLICATE_DD_NAME",
                        line=lines[1],
                        column=3,
                        message=f"Step '{s_name}': Duplicate DD name '{d_name}' defined on lines {line_str}.",
                        suggested_fix=f"Use a unique DD name or use an unnamed DD (// DD ...) for dataset concatenation.",
                    )
                )

    return diagnostics


def validate_dd_parameters(stmt: LogicalStatement) -> List[Diagnostic]:
    """Validates specific parameters on a DD statement (DSN, DISP, SPACE, DCB)."""
    diagnostics: List[Diagnostic] = []
    kw = stmt.keyword_params
    line_no = stmt.start_line
    dd_name = stmt.name or "(concatenation)"

    # 1. DISP parameter validation
    if "DISP" in kw:
        disp_val = kw["DISP"].strip()
        disp_diag = validate_disp_syntax(disp_val, line_no, dd_name)
        if disp_diag:
            diagnostics.extend(disp_diag)

    # 2. DSN / DSNAME parameter validation
    dsn_val = kw.get("DSN") or kw.get("DSNAME")
    if dsn_val:
        dsn_diag = validate_dsn_syntax(dsn_val.strip(), line_no, dd_name)
        if dsn_diag:
            diagnostics.extend(dsn_diag)

    # 3. SPACE parameter validation
    if "SPACE" in kw:
        space_val = kw["SPACE"].strip()
        space_diag = validate_space_syntax(space_val, line_no, dd_name)
        if space_diag:
            diagnostics.extend(space_diag)

    # 4. DCB parameter validation
    dcb_diag = validate_dcb_parameters(kw, line_no, dd_name)
    if dcb_diag:
        diagnostics.extend(dcb_diag)

    return diagnostics


def validate_disp_syntax(disp_str: str, line_no: int, dd_name: str) -> List[Diagnostic]:
    """Validates DISP parameter subparameters: status, normal termination, abnormal termination."""
    diagnostics: List[Diagnostic] = []

    # Strip outer parentheses if present
    content = disp_str.strip()
    if content.startswith("(") and content.endswith(")"):
        content = content[1:-1].strip()

    subparams = [s.strip().upper() for s in content.split(",")]

    if len(subparams) > 3:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="DISP_TOO_MANY_SUBPARAMETERS",
                line=line_no,
                message=f"DD '{dd_name}': DISP parameter contains {len(subparams)} subparameters; maximum allowed is 3: (status, normal, abend).",
                suggested_fix="Format DISP as DISP=(status,normal_disp,abend_disp) or DISP=status.",
            )
        )
        return diagnostics

    # First subparameter: Status (NEW, OLD, SHR, MOD)
    if subparams and subparams[0]:
        status = subparams[0]
        if status not in VALID_DISP_STATUS:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="INVALID_DISP_STATUS",
                    line=line_no,
                    message=f"DD '{dd_name}': Invalid DISP status '{status}'. Valid statuses are: {', '.join(sorted(VALID_DISP_STATUS))}.",
                    suggested_fix="Use one of: NEW, OLD, SHR, or MOD.",
                )
            )

    # Second subparameter: Normal disposition
    if len(subparams) >= 2 and subparams[1]:
        normal_disp = subparams[1]
        if normal_disp not in VALID_NORMAL_DISP:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="INVALID_NORMAL_DISP",
                    line=line_no,
                    message=f"DD '{dd_name}': Invalid normal disposition '{normal_disp}'. Valid options are: {', '.join(sorted(VALID_NORMAL_DISP))}.",
                    suggested_fix="Use one of: DELETE, KEEP, PASS, CATLG, or UNCATLG.",
                )
            )

    # Third subparameter: Abnormal disposition (abend)
    if len(subparams) == 3 and subparams[2]:
        abend_disp = subparams[2]
        if abend_disp not in VALID_ABEND_DISP:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="INVALID_ABEND_DISP",
                    line=line_no,
                    message=f"DD '{dd_name}': Invalid abnormal (abend) disposition '{abend_disp}'. Valid options are: {', '.join(sorted(VALID_ABEND_DISP))}.",
                    suggested_fix="Use one of: DELETE, KEEP, CATLG, or UNCATLG.",
                )
            )

    return diagnostics


def validate_dsn_syntax(dsn_str: str, line_no: int, dd_name: str) -> List[Diagnostic]:
    """Validates dataset name syntax, supporting GDG, PDS members, temporary datasets, and symbolics."""
    diagnostics: List[Diagnostic] = []

    # Strip quotes if enclosed
    dsn = dsn_str.strip("'\"").strip()

    # Allow DSN=NULLFILE
    if dsn.upper() == "NULLFILE":
        return diagnostics

    # Allow symbolic parameters (e.g. &SYSUID, &DSNAME, &ENV) without declare errors
    if "&" in dsn:
        # If temporary dataset: &&TEMP or &&DSN
        if dsn.startswith("&&"):
            temp_name = dsn[2:]
            if not re.match(r"^[A-Z$#@][A-Z0-9$#@]{0,7}$", temp_name, re.I):
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        rule_id="INVALID_TEMP_DSN",
                        line=line_no,
                        message=f"DD '{dd_name}': Temporary dataset name '{dsn}' should follow 1-8 alphanumeric character rules after '&&'.",
                        suggested_fix="Use format &&NAME (e.g. &&TEMPDSN).",
                    )
                )
            return diagnostics
        elif dsn.startswith("&") and not "." in dsn and not "(" in dsn:
            # Single symbolic parameter, valid
            return diagnostics

    # Check for Member or GDG Generation: DSN(MEMBER) or DSN(+1) or DSN(0)
    match_member = re.match(r"^([^\(]+)\(([^\)]+)\)$", dsn)
    base_dsn = dsn
    if match_member:
        base_dsn = match_member.group(1).strip()
        member_part = match_member.group(2).strip()

        # Check GDG generation (e.g. 0, +1, -1, +2)
        if re.match(r"^[+-]?\d+$", member_part):
            pass  # Valid GDG relative generation
        elif not re.match(r"^[A-Z$#@][A-Z0-9$#@]{0,7}$", member_part, re.I):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    rule_id="INVALID_PDS_MEMBER_NAME",
                    line=line_no,
                    message=f"DD '{dd_name}': PDS member name '{member_part}' exceeds 8 chars or has invalid characters.",
                    suggested_fix="Member name must be 1-8 alphanumeric/national characters.",
                )
            )

    # Validate base DSN length (max 44 characters)
    if len(base_dsn) > 44:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="DSN_LENGTH_EXCEEDED",
                line=line_no,
                message=f"DD '{dd_name}': Dataset name '{base_dsn}' exceeds the z/OS 44-character maximum limit (length: {len(base_dsn)}).",
                suggested_fix="Shorten dataset name to 44 characters or fewer.",
            )
        )

    # Normalize symbolic parameter period delimiter (e.g. &SYSUID..DATA -> &SYSUID.DATA)
    check_dsn = re.sub(r"(&[A-Z0-9$#@]+)\.\.", r"\1.", base_dsn, flags=re.I)

    # Validate segments (each segment 1-8 characters, separated by periods)
    segments = check_dsn.split(".")
    for seg in segments:
        if not seg:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="EMPTY_DSN_QUALIFIER",
                    line=line_no,
                    message=f"DD '{dd_name}': Dataset name '{base_dsn}' contains an empty qualifier (consecutive periods).",
                    suggested_fix="Remove duplicate period from dataset name.",
                )
            )
            continue

        # Allow qualifiers containing symbolic parameters (e.g. &HLQ or &SYSUID)
        if "&" in seg:
            continue

        if len(seg) > 8:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="DSN_QUALIFIER_TOO_LONG",
                    line=line_no,
                    message=f"DD '{dd_name}': Qualifier '{seg}' in DSN '{base_dsn}' exceeds the 8-character limit.",
                    suggested_fix="Each dataset qualifier must be between 1 and 8 characters.",
                )
            )
        elif not re.match(r"^[A-Z$#@-][A-Z0-9$#@-]*$", seg, re.I):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    rule_id="DSN_QUALIFIER_INVALID_CHARS",
                    line=line_no,
                    message=f"DD '{dd_name}': Qualifier '{seg}' in DSN '{base_dsn}' contains invalid characters.",
                    suggested_fix="Qualifiers should only contain alphanumeric, national (@, #, $), or hyphen characters.",
                )
            )

    return diagnostics


def validate_space_syntax(space_str: str, line_no: int, dd_name: str) -> List[Diagnostic]:
    """Validates SPACE=(unit,(primary,secondary,...)) parameter syntax."""
    diagnostics: List[Diagnostic] = []

    content = space_str.strip()
    if content.startswith("(") and content.endswith(")"):
        content = content[1:-1].strip()

    tokens = split_comma_parameters(content)
    if not tokens:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="MALFORMED_SPACE_PARAMETER",
                line=line_no,
                message=f"DD '{dd_name}': SPACE parameter is empty.",
                suggested_fix="Provide SPACE parameter (e.g. SPACE=(CYL,(5,1),RLSE)).",
            )
        )
        return diagnostics

    unit_token = tokens[0].upper()
    # Unit can be TRK, CYL, or a block size integer (e.g. 800 or 27920)
    is_valid_unit = (unit_token in VALID_SPACE_UNITS or unit_token.isdigit())
    if not is_valid_unit:
        diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                rule_id="INVALID_SPACE_UNIT",
                line=line_no,
                message=f"DD '{dd_name}': Unrecognized SPACE allocation unit '{unit_token}'. Expected TRK, CYL, or average block length integer.",
                suggested_fix="Use CYL or TRK (e.g. SPACE=(CYL,(5,1))).",
            )
        )

    # Check quantities: (primary, secondary, dir)
    if len(tokens) > 1:
        quantities = tokens[1].strip()
        if quantities.startswith("(") and quantities.endswith(")"):
            quantities = quantities[1:-1].strip()
        q_parts = [p.strip() for p in quantities.split(",")]
        if q_parts and not q_parts[0].isdigit():
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    rule_id="INVALID_PRIMARY_SPACE",
                    line=line_no,
                    message=f"DD '{dd_name}': Primary SPACE quantity '{q_parts[0]}' is not a valid non-negative integer.",
                    suggested_fix="Specify primary space as an integer (e.g. (10,2)).",
                )
            )

    return diagnostics


def validate_dcb_parameters(kw: Dict[str, str], line_no: int, dd_name: str) -> List[Diagnostic]:
    """Validates DCB subparameters or individual parameters RECFM, LRECL, and BLKSIZE."""
    diagnostics: List[Diagnostic] = []

    recfm: Optional[str] = kw.get("RECFM")
    lrecl_str: Optional[str] = kw.get("LRECL")
    blksize_str: Optional[str] = kw.get("BLKSIZE")

    # If DCB=(...) parameter is specified, extract subparameters
    if "DCB" in kw:
        dcb_val = kw["DCB"].strip()
        if dcb_val.startswith("(") and dcb_val.endswith(")"):
            dcb_val = dcb_val[1:-1].strip()
        dcb_parts = split_comma_parameters(dcb_val)
        for part in dcb_parts:
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip().upper()
                v = v.strip()
                if k == "RECFM" and not recfm:
                    recfm = v
                elif k == "LRECL" and not lrecl_str:
                    lrecl_str = v
                elif k == "BLKSIZE" and not blksize_str:
                    blksize_str = v

    # Check RECFM
    if recfm:
        recfm_clean = recfm.strip().upper()
        if not any(recfm_clean.startswith(p) for p in VALID_RECFM_PREFIXES):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    rule_id="UNKNOWN_RECFM",
                    line=line_no,
                    message=f"DD '{dd_name}': Unrecognized RECFM '{recfm_clean}'. Typical formats: FB, VB, F, V, U.",
                    suggested_fix="Specify standard record format (e.g. RECFM=FB).",
                )
            )

    # Check LRECL and BLKSIZE compatibility for Fixed Blocked (FB)
    if lrecl_str and blksize_str:
        if lrecl_str.isdigit() and blksize_str.isdigit():
            lrecl = int(lrecl_str)
            blksize = int(blksize_str)
            if recfm and "FB" in recfm.upper():
                if lrecl > 0 and blksize > 0:
                    if blksize < lrecl:
                        diagnostics.append(
                            Diagnostic(
                                severity=Severity.ERROR,
                                rule_id="BLKSIZE_LESS_THAN_LRECL",
                                line=line_no,
                                message=f"DD '{dd_name}': BLKSIZE ({blksize}) cannot be less than LRECL ({lrecl}).",
                                suggested_fix=f"Set BLKSIZE to a multiple of {lrecl} (or 0 for system-determined block size).",
                            )
                        )
                    elif blksize % lrecl != 0:
                        diagnostics.append(
                            Diagnostic(
                                severity=Severity.WARNING,
                                rule_id="BLKSIZE_NOT_MULTIPLE_OF_LRECL",
                                line=line_no,
                                message=f"DD '{dd_name}': BLKSIZE ({blksize}) is not an exact multiple of LRECL ({lrecl}) for RECFM=FB.",
                                suggested_fix=f"Ensure BLKSIZE is a multiple of {lrecl} (e.g. {lrecl * 10} or 0 for SDB).",
                            )
                        )

    return diagnostics

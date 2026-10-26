"""Utility-specific validation rules for IEFBR14, IEBGENER, DFSORT, and IDCAMS."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.validation.models import Diagnostic, Severity
from backend.validation.parser import LogicalStatement, ParsedJcl, split_comma_parameters

VALID_DFSORT_FORMATS = {
    "CH", "ZD", "PD", "BI", "FI", "FL", "AC", "AQ", "FS", "SS",
    "CSF", "Y2T", "Y2U", "Y2V", "Y2W", "Y2X", "Y2Y"
}
VALID_DFSORT_ORDERS = {"A", "D"}


@dataclass
class UtilityStep:
    name: str
    program: str
    start_line: int
    exec_stmt: LogicalStatement
    dd_statements: Dict[str, List[LogicalStatement]] = field(default_factory=dict)
    sysin_lines: List[Tuple[int, str]] = field(default_factory=list)


def extract_utility_steps(parsed: ParsedJcl) -> List[UtilityStep]:
    """Groups statements into steps starting at each EXEC statement."""
    steps: List[UtilityStep] = []
    current_step: Optional[UtilityStep] = None

    for stmt in parsed.statements:
        if stmt.statement_type == "EXEC":
            # Extract program name from PGM= or positional proc
            prog = stmt.keyword_params.get("PGM", "").upper()
            if not prog and stmt.positional_params:
                prog = stmt.positional_params[0].upper()
            if not prog and "PROC" in stmt.keyword_params:
                prog = stmt.keyword_params["PROC"].upper()

            current_step = UtilityStep(
                name=stmt.name or f"STEP_{stmt.start_line}",
                program=prog,
                start_line=stmt.start_line,
                exec_stmt=stmt,
            )
            steps.append(current_step)

        elif stmt.statement_type == "DD" and current_step is not None:
            dd_name = stmt.name.upper() if stmt.name else "_CONCAT_"
            current_step.dd_statements.setdefault(dd_name, []).append(stmt)
            if dd_name == "SYSIN" and stmt.instream_lines:
                current_step.sysin_lines.extend(stmt.instream_lines)

    return steps


from backend.validation.registry import get_canonical_utility


def validate_utility_specific_rules(parsed: ParsedJcl) -> List[Diagnostic]:
    """Evaluates utility-specific DD and control statement rules for known IBM utilities."""
    diagnostics: List[Diagnostic] = []
    steps = extract_utility_steps(parsed)

    for step in steps:
        prog = step.program
        canonical = get_canonical_utility(prog)

        # -------------------------------------------------------------
        # 1. IEFBR14 - Dummy utility commonly used to allocate/delete datasets
        # -------------------------------------------------------------
        if prog == "IEFBR14" or canonical == "IEFBR14":
            diagnostics.extend(validate_iefbr14_step(step))

        # -------------------------------------------------------------
        # 2. IEBGENER - Sequential copy utility
        # -------------------------------------------------------------
        elif prog == "IEBGENER" or canonical == "IEBGENER":
            diagnostics.extend(validate_iebgener_step(step))

        # -------------------------------------------------------------
        # 3. DFSORT / SORT / ICEMAN / SYNCSORT / ICETOOL - Mainframe sort program
        # -------------------------------------------------------------
        elif prog in ("SORT", "ICEMAN", "DFSORT", "SYNCSORT", "ICETOOL") or canonical == "SORT":
            diagnostics.extend(validate_dfsort_step(step))

        # -------------------------------------------------------------
        # 4. IDCAMS - Access Method Services
        # -------------------------------------------------------------
        elif prog == "IDCAMS" or canonical == "IDCAMS":
            diagnostics.extend(validate_idcams_step(step))

        # Custom / user programs: Do NOT impose IBM utility-specific DD requirements.

    return diagnostics


def validate_iefbr14_step(step: UtilityStep) -> List[Diagnostic]:
    """IEFBR14 rules: Do not require SYSPRINT or SYSIN; validate allocation DD parameters."""
    diagnostics: List[Diagnostic] = []

    for dd_name, dds in step.dd_statements.items():
        if dd_name == "_CONCAT_":
            continue
        for dd in dds:
            kw = dd.keyword_params
            disp_str = kw.get("DISP", "").upper()

            # Check for NEW dataset allocation missing SPACE
            if "NEW" in disp_str:
                has_space = "SPACE" in kw
                is_dummy = "DUMMY" in dd.positional_params or dd.keyword_params.get("DUMMY") is not None
                is_sysout = "SYSOUT" in kw

                if not has_space and not is_dummy and not is_sysout:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.WARNING,
                            rule_id="IEFBR14_MISSING_SPACE",
                            line=dd.start_line,
                            column=3,
                            message=f"Step '{step.name}' (IEFBR14): DD '{dd_name}' specifies DISP=NEW but is missing the SPACE parameter. DASD dataset allocation without SMS data class requires SPACE=(...).",
                            suggested_fix="Add SPACE parameter (e.g. SPACE=(CYL,(1,1),RLSE)).",
                        )
                    )

    return diagnostics


def validate_iebgener_step(step: UtilityStep) -> List[Diagnostic]:
    """IEBGENER rules: Require SYSUT1 and SYSUT2; check SYSPRINT and SYSIN."""
    diagnostics: List[Diagnostic] = []
    dds = step.dd_statements

    # SYSUT1 (Input)
    if "SYSUT1" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="IEBGENER_MISSING_SYSUT1",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' (IEBGENER) is missing required DD statement 'SYSUT1' (input dataset).",
                suggested_fix="Define //SYSUT1 DD DSN=input_dataset,DISP=SHR.",
            )
        )

    # SYSUT2 (Output)
    if "SYSUT2" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="IEBGENER_MISSING_SYSUT2",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' (IEBGENER) is missing required DD statement 'SYSUT2' (output dataset).",
                suggested_fix="Define //SYSUT2 DD DSN=output_dataset,DISP=(NEW,CATLG,DELETE),...",
            )
        )

    # SYSPRINT (Listing)
    if "SYSPRINT" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="IEBGENER_MISSING_SYSPRINT",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' (IEBGENER) is missing required DD statement 'SYSPRINT' (diagnostic message log).",
                suggested_fix="Define //SYSPRINT DD SYSOUT=*.",
            )
        )

    # SYSIN (Control cards, DUMMY or in-stream)
    if "SYSIN" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="IEBGENER_MISSING_SYSIN",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' (IEBGENER) is missing required DD statement 'SYSIN' (control statements, or DUMMY if none).",
                suggested_fix="Define //SYSIN DD DUMMY or provide in-stream control cards.",
            )
        )

    return diagnostics


def validate_dfsort_step(step: UtilityStep) -> List[Diagnostic]:
    """DFSORT rules: SORTIN, SORTOUT (or OUTFIL), SYSOUT, SYSIN, SORT FIELDS parsing."""
    diagnostics: List[Diagnostic] = []
    dds = step.dd_statements
    sysin_text = "\n".join(line for _, line in step.sysin_lines).upper()

    # Check for OUTFIL in SYSIN
    has_outfil = "OUTFIL" in sysin_text

    # SORTIN requirement
    has_sortin = any(k == "SORTIN" or k.startswith("SORTIN") for k in dds)
    if not has_sortin:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="DFSORT_MISSING_SORTIN",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' ({step.program}) is missing required DD statement 'SORTIN' (input dataset to sort/merge).",
                suggested_fix="Define //SORTIN DD DSN=input_dataset,DISP=SHR.",
            )
        )

    # SORTOUT requirement (unless OUTFIL is used)
    has_sortout = any(k == "SORTOUT" or k.startswith("SORTOUT") for k in dds)
    if not has_sortout and not has_outfil:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="DFSORT_MISSING_SORTOUT",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' ({step.program}) is missing required DD statement 'SORTOUT' (sorted output dataset).",
                suggested_fix="Define //SORTOUT DD DSN=output_dataset,DISP=(NEW,CATLG,DELETE),... or configure OUTFIL.",
            )
        )

    # SYSOUT or SYSPRINT message listing
    if "SYSOUT" not in dds and "SYSPRINT" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="DFSORT_MISSING_SYSOUT",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' ({step.program}) is missing required message DD statement 'SYSOUT' (or SYSPRINT).",
                suggested_fix="Define //SYSOUT DD SYSOUT=*.",
            )
        )

    # SYSIN requirement
    if "SYSIN" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="DFSORT_MISSING_SYSIN",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' ({step.program}) is missing required DD statement 'SYSIN' (sort control statements like SORT FIELDS=...).",
                suggested_fix="Define //SYSIN DD * with SORT FIELDS control card.",
            )
        )
    else:
        # Validate DFSORT SYSIN control cards if captured
        diagnostics.extend(validate_dfsort_control_cards(step, sysin_text))

    return diagnostics


def validate_dfsort_control_cards(step: UtilityStep, sysin_text: str) -> List[Diagnostic]:
    """Validates DFSORT control statements (SORT FIELDS, COPY, field boundary vs LRECL)."""
    diagnostics: List[Diagnostic] = []

    if not sysin_text.strip():
        return diagnostics

    # Detect known SORTIN LRECL if available
    sortin_lrecl: Optional[int] = None
    sortin_dds = step.dd_statements.get("SORTIN", [])
    if sortin_dds:
        kw = sortin_dds[0].keyword_params
        if "LRECL" in kw and kw["LRECL"].isdigit():
            sortin_lrecl = int(kw["LRECL"])
        elif "DCB" in kw:
            m = re.search(r"LRECL=(\d+)", kw["DCB"], re.I)
            if m:
                sortin_lrecl = int(m.group(1))

    # Parse SORT FIELDS=
    # Patterns: SORT FIELDS=COPY or SORT FIELDS=(start,length,format,order,...)
    if "SORT " in sysin_text:
        match_copy = re.search(r"\bFIELDS\s*=\s*COPY\b", sysin_text, re.I)
        if match_copy:
            pass  # Valid COPY operation
        else:
            match_fields = re.search(r"\bFIELDS\s*=\s*\((.*?)\)", sysin_text, re.I | re.DOTALL)
            if match_fields:
                fields_str = match_fields.group(1).replace("\n", " ").strip()
                tokens = [t.strip().upper() for t in fields_str.split(",") if t.strip()]

                if len(tokens) % 4 != 0:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.WARNING,
                            rule_id="DFSORT_INVALID_FIELDS_COUNT",
                            line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                            message=f"Step '{step.name}' (DFSORT): SORT FIELDS parameter expects groups of 4 values (start,length,format,order). Found {len(tokens)} items.",
                            suggested_fix="Format as SORT FIELDS=(start,length,format,order) (e.g. SORT FIELDS=(1,10,CH,A)).",
                        )
                    )
                else:
                    # Validate each group of 4
                    for i in range(0, len(tokens), 4):
                        start_str = tokens[i]
                        len_str = tokens[i + 1]
                        fmt = tokens[i + 2]
                        order = tokens[i + 3]

                        if not start_str.isdigit() or int(start_str) <= 0:
                            diagnostics.append(
                                Diagnostic(
                                    severity=Severity.ERROR,
                                    rule_id="DFSORT_INVALID_FIELD_START",
                                    line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                                    message=f"Step '{step.name}' (DFSORT): Field start position '{start_str}' must be a positive integer.",
                                    suggested_fix="Specify 1-based start column (e.g. 1).",
                                )
                            )
                        if not len_str.isdigit() or int(len_str) <= 0:
                            diagnostics.append(
                                Diagnostic(
                                    severity=Severity.ERROR,
                                    rule_id="DFSORT_INVALID_FIELD_LENGTH",
                                    line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                                    message=f"Step '{step.name}' (DFSORT): Field length '{len_str}' must be a positive integer.",
                                    suggested_fix="Specify field length (e.g. 10).",
                                )
                            )
                        if fmt not in VALID_DFSORT_FORMATS:
                            diagnostics.append(
                                Diagnostic(
                                    severity=Severity.WARNING,
                                    rule_id="DFSORT_UNKNOWN_FIELD_FORMAT",
                                    line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                                    message=f"Step '{step.name}' (DFSORT): Unrecognized sort format '{fmt}'. Standard formats: CH, ZD, PD, BI, FI.",
                                    suggested_fix="Use CH for character, ZD for zoned decimal, PD for packed decimal.",
                                )
                            )
                        if order not in VALID_DFSORT_ORDERS:
                            diagnostics.append(
                                Diagnostic(
                                    severity=Severity.ERROR,
                                    rule_id="DFSORT_INVALID_FIELD_ORDER",
                                    line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                                    message=f"Step '{step.name}' (DFSORT): Sort order '{order}' must be 'A' (ascending) or 'D' (descending).",
                                    suggested_fix="Specify 'A' or 'D'.",
                                )
                            )

                        # Check field boundary against known LRECL
                        if sortin_lrecl and start_str.isdigit() and len_str.isdigit():
                            start_val = int(start_str)
                            len_val = int(len_str)
                            end_byte = start_val + len_val - 1
                            if end_byte > sortin_lrecl:
                                diagnostics.append(
                                    Diagnostic(
                                        severity=Severity.ERROR,
                                        rule_id="DFSORT_FIELD_EXCEEDS_LRECL",
                                        line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                                        message=f"Step '{step.name}' (DFSORT): Sort field byte range ({start_val}-{end_byte}) exceeds input dataset LRECL of {sortin_lrecl}.",
                                        suggested_fix=f"Adjust field start or length so the end byte does not exceed {sortin_lrecl}.",
                                    )
                                )

    return diagnostics


def validate_idcams_step(step: UtilityStep) -> List[Diagnostic]:
    """IDCAMS rules: SYSPRINT, SYSIN, command syntax (DEFINE, REPRO, DELETE, LISTCAT)."""
    diagnostics: List[Diagnostic] = []
    dds = step.dd_statements
    sysin_text = "\n".join(line for _, line in step.sysin_lines).upper()

    # SYSPRINT requirement
    if "SYSPRINT" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="IDCAMS_MISSING_SYSPRINT",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' (IDCAMS) is missing required DD statement 'SYSPRINT' (message listing).",
                suggested_fix="Define //SYSPRINT DD SYSOUT=*.",
            )
        )

    # SYSIN requirement
    if "SYSIN" not in dds:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                rule_id="IDCAMS_MISSING_SYSIN",
                line=step.start_line,
                column=1,
                message=f"Step '{step.name}' (IDCAMS) is missing required DD statement 'SYSIN' (AMS control commands).",
                suggested_fix="Define //SYSIN DD * with IDCAMS command stream.",
            )
        )
    else:
        # Check for REPRO DD references: INFILE(ddname) or OUTFILE(ddname)
        if "REPRO" in sysin_text:
            infile_matches = re.findall(r"\b(?:INFILE|IFILE)\s*\(\s*([A-Z0-9$#@]{1,8})\s*\)", sysin_text, re.I)
            for inf in infile_matches:
                inf_upper = inf.upper()
                if inf_upper not in dds:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            rule_id="IDCAMS_REPRO_MISSING_INFILE_DD",
                            line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                            message=f"Step '{step.name}' (IDCAMS): REPRO specifies INFILE('{inf_upper}') but DD '//{inf_upper}' is not defined in this step.",
                            suggested_fix=f"Add // {inf_upper} DD DSN=...,DISP=SHR to step '{step.name}'.",
                        )
                    )

            outfile_matches = re.findall(r"\b(?:OUTFILE|OFILE)\s*\(\s*([A-Z0-9$#@]{1,8})\s*\)", sysin_text, re.I)
            for outf in outfile_matches:
                outf_upper = outf.upper()
                if outf_upper not in dds:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            rule_id="IDCAMS_REPRO_MISSING_OUTFILE_DD",
                            line=step.sysin_lines[0][0] if step.sysin_lines else step.start_line,
                            message=f"Step '{step.name}' (IDCAMS): REPRO specifies OUTFILE('{outf_upper}') but DD '//{outf_upper}' is not defined in this step.",
                            suggested_fix=f"Add // {outf_upper} DD DSN=...,DISP=(NEW,CATLG,DELETE),... to step '{step.name}'.",
                        )
                    )

    return diagnostics

"""JCL Parser for physical-line parsing, logical statement assembly, and in-stream data tracking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.validation.models import Diagnostic, Severity

# Standard JCL name pattern: 1-8 chars, alphanumeric or national characters (@, #, $), starting with alpha or national
JCL_NAME_REGEX = re.compile(r"^[A-Z$#@][A-Z0-9$#@]{0,7}$", re.IGNORECASE)

KNOWN_OPERATIONS = {
    "JOB", "EXEC", "DD", "PROC", "PEND", "SET", "INCLUDE", "JCLLIB",
    "IF", "THEN", "ELSE", "ENDIF", "CNTL", "ENDCNTL", "OUTPUT", "XMIT"
}


@dataclass
class PhysicalLine:
    line_number: int
    raw_text: str
    length: int
    is_comment: bool = False
    is_delimiter: bool = False
    is_null: bool = False
    is_jcl_stmt: bool = False
    is_continuation: bool = False


@dataclass
class LogicalStatement:
    statement_type: str  # "JOB", "EXEC", "DD", "COMMENT", "DELIMITER", "NULL", "IF", etc.
    name: str = ""
    operation: str = ""
    start_line: int = 0
    end_line: int = 0
    physical_lines: List[Tuple[int, str]] = field(default_factory=list)
    continuation_lines: List[Tuple[int, str]] = field(default_factory=list)
    raw_operands: str = ""
    in_line_comment: str = ""
    positional_params: List[str] = field(default_factory=list)
    keyword_params: Dict[str, str] = field(default_factory=dict)
    instream_lines: List[Tuple[int, str]] = field(default_factory=list)
    is_instream_terminated: bool = True
    instream_delimiter: str = "/*"
    instream_type: str = ""  # "STAR" or "DATA"
    step_name: Optional[str] = None
    source_column: int = 1
    name_column: Optional[int] = None
    operation_column: Optional[int] = None
    operands_column: Optional[int] = None


@dataclass
class ParsedJcl:
    raw_lines: List[str]
    physical_lines: List[PhysicalLine]
    statements: List[LogicalStatement]
    diagnostics: List[Diagnostic] = field(default_factory=list)


def split_operands_and_comment(text: str) -> Tuple[str, str]:
    """Splits an operands string into operand field and trailing comment.
    In JCL, the first blank outside quotes or parentheses ends the operands field."""
    in_quote = False
    paren_depth = 0
    for idx, ch in enumerate(text):
        if ch == "'" and not in_quote:
            in_quote = True
        elif ch == "'" and in_quote:
            # Check for escaped quote ''
            if idx + 1 < len(text) and text[idx + 1] == "'":
                continue
            in_quote = False
        elif not in_quote:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                if paren_depth > 0:
                    paren_depth -= 1
            elif ch == " " and paren_depth == 0:
                operands_part = text[:idx].rstrip()
                comment_part = text[idx:].strip()
                return operands_part, comment_part
    return text.rstrip(), ""


def split_comma_parameters(text: str) -> List[str]:
    """Splits comma-separated parameters respecting single quotes and parentheses."""
    tokens: List[str] = []
    current: List[str] = []
    in_quote = False
    paren_depth = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if ch == "'" and not in_quote:
            in_quote = True
            current.append(ch)
        elif ch == "'" and in_quote:
            # Check for double quote escape ''
            if i + 1 < n and text[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_quote = False
                current.append(ch)
        elif not in_quote:
            if ch == "(":
                paren_depth += 1
                current.append(ch)
            elif ch == ")":
                if paren_depth > 0:
                    paren_depth -= 1
                current.append(ch)
            elif ch == "," and paren_depth == 0:
                tokens.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        else:
            current.append(ch)
        i += 1

    if current:
        tokens.append("".join(current).strip())
    return [t for t in tokens if t]


def parse_parameters(operands: str) -> Tuple[List[str], Dict[str, str]]:
    """Separates positional and keyword parameters (e.g. KEY=VALUE)."""
    positional: List[str] = []
    keyword: Dict[str, str] = {}
    tokens = split_comma_parameters(operands)

    for token in tokens:
        # Check if keyword (KEY=VALUE) where '=' is not inside quotes or parentheses
        eq_idx = -1
        in_quote = False
        paren_depth = 0
        for idx, ch in enumerate(token):
            if ch == "'":
                in_quote = not in_quote
            elif not in_quote:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    if paren_depth > 0:
                        paren_depth -= 1
                elif ch == "=" and paren_depth == 0:
                    eq_idx = idx
                    break

        if eq_idx != -1:
            key = token[:eq_idx].strip().upper()
            val = token[eq_idx + 1:].strip()
            keyword[key] = val
        else:
            positional.append(token)

    return positional, keyword


def parse_jcl_structure(jcl_text: str) -> ParsedJcl:
    """Parses raw JCL text into physical lines, logical statements, and parser diagnostics."""
    raw_lines = jcl_text.splitlines()
    physical_lines: List[PhysicalLine] = []
    statements: List[LogicalStatement] = []
    diagnostics: List[Diagnostic] = []

    if not raw_lines:
        return ParsedJcl(raw_lines=[], physical_lines=[], statements=[], diagnostics=[])

    in_stream = False
    in_stream_type = "STAR"
    in_stream_delimiter = "/*"
    current_instream_stmt: Optional[LogicalStatement] = None

    has_trailing_continuation = False
    continuation_source_line = 0
    current_logical_stmt: Optional[LogicalStatement] = None
    current_step_name: Optional[str] = None

    for line_idx, line in enumerate(raw_lines, start=1):
        line_len = len(line)
        p_line = PhysicalLine(line_number=line_idx, raw_text=line, length=line_len)
        physical_lines.append(p_line)

        # 1. 80-Column constraint check
        if line_len > 80:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    rule_id="LINE_EXCEEDS_80",
                    line=line_idx,
                    column=81,
                    message=f"Line {line_idx} exceeds 80 columns.",
                    suggested_fix="Shorten line or split operands across multiple lines using continuation.",
                )
            )

        # 2. Handle in-stream data mode
        if in_stream:
            stripped = line.rstrip()
            # Check for delimiter match (/* or custom DLM)
            is_delim = (
                stripped == in_stream_delimiter or
                stripped.startswith(in_stream_delimiter) or
                (in_stream_delimiter == "/*" and line.startswith("/*"))
            )

            if is_delim:
                in_stream = False
                if current_instream_stmt:
                    current_instream_stmt.is_instream_terminated = True
                stmt_delim = LogicalStatement(
                    statement_type="DELIMITER",
                    operation="/*",
                    start_line=line_idx,
                    end_line=line_idx,
                    physical_lines=[(line_idx, line)],
                    step_name=current_step_name,
                    source_column=1,
                )
                statements.append(stmt_delim)
                continue

            # In-stream data record: retained under current in-stream statement,
            # never parsed as an independent executable JCL statement.
            if current_instream_stmt:
                current_instream_stmt.instream_lines.append((line_idx, line))
            continue

        # 3. Delimiter statement: /*
        if line.startswith("/*"):
            p_line.is_delimiter = True
            if has_trailing_continuation:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        rule_id="CONTINUATION_BROKEN_BY_DELIMITER",
                        line=line_idx,
                        column=1,
                        message=f"Line {line_idx}: Delimiter statement appears after unresolved continuation from line {continuation_source_line}.",
                        suggested_fix="Ensure previous statement is properly completed before delimiter.",
                    )
                )
                has_trailing_continuation = False
            statements.append(
                LogicalStatement(
                    statement_type="DELIMITER",
                    operation="/*",
                    start_line=line_idx,
                    end_line=line_idx,
                    physical_lines=[(line_idx, line)],
                    step_name=current_step_name,
                    source_column=1,
                )
            )
            continue

        # 4. Comment statement: //*
        if line.startswith("//*"):
            p_line.is_comment = True
            statements.append(
                LogicalStatement(
                    statement_type="COMMENT",
                    operation="//*",
                    start_line=line_idx,
                    end_line=line_idx,
                    physical_lines=[(line_idx, line)],
                    raw_operands=line[3:].strip(),
                    step_name=current_step_name,
                    source_column=1,
                )
            )
            continue

        # 5. Null statement: // alone (rest of line spaces)
        if line.strip() == "//":
            p_line.is_null = True
            has_trailing_continuation = False
            statements.append(
                LogicalStatement(
                    statement_type="NULL",
                    operation="//",
                    start_line=line_idx,
                    end_line=line_idx,
                    physical_lines=[(line_idx, line)],
                    step_name=current_step_name,
                    source_column=1,
                )
            )
            continue

        # 6. Non-JCL line (doesn't start with //)
        if not line.startswith("//"):
            if line.strip():
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        rule_id="INVALID_STATEMENT_PREFIX",
                        line=line_idx,
                        column=1,
                        message=f"Line {line_idx}: Line does not start with '//' or '/*'. In-stream data must be placed under 'DD *' or 'DD DATA'.",
                        suggested_fix="Prefix statement with '//' or define a DD * dataset for in-stream records.",
                    )
                )
            continue

        # 7. Line starts with // -> Check if continuation line
        p_line.is_jcl_stmt = True
        is_continuation_line = (len(line) >= 3 and line[2] == " ")

        if has_trailing_continuation:
            if not is_continuation_line:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        rule_id="CONTINUATION_MISSING_COL3_BLANK",
                        line=line_idx,
                        column=3,
                        message=f"Line {line_idx}: Expected JCL continuation statement starting with '// ' (columns 1-2 '//', column 3 blank) following line {continuation_source_line}.",
                        suggested_fix="Insert a space in column 3 to indicate continuation, or remove trailing comma from previous line.",
                    )
                )
            else:
                # Column 4-16 operand placement rule
                after_slashes = line[2:]
                leading_blanks = len(after_slashes) - len(after_slashes.lstrip(" "))
                first_operand_col = 3 + leading_blanks  # 1-indexed column
                if first_operand_col > 16:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.WARNING,
                            rule_id="CONTINUATION_COL_OUT_OF_BOUNDS",
                            line=line_idx,
                            column=first_operand_col,
                            message=f"Line {line_idx}: Continuation operand begins at column {first_operand_col}. Standard z/OS continuation operands begin between columns 4 and 16.",
                            suggested_fix="Align continuation operands to column 16 (or between cols 4-16).",
                        )
                    )

            # Assemble continuation onto current logical statement
            if current_logical_stmt is not None:
                current_logical_stmt.end_line = line_idx
                current_logical_stmt.physical_lines.append((line_idx, line))
                current_logical_stmt.continuation_lines.append((line_idx, line))

                cont_content = line[2:].strip()
                operands_part, comment_part = split_operands_and_comment(cont_content)
                if current_logical_stmt.raw_operands:
                    current_logical_stmt.raw_operands += operands_part
                else:
                    current_logical_stmt.raw_operands = operands_part

                if comment_part:
                    current_logical_stmt.in_line_comment = (
                        (current_logical_stmt.in_line_comment + " " + comment_part).strip()
                    )

                # Check if this continuation line itself continues onto the next line
                has_trailing_continuation = operands_part.rstrip().endswith(",")
                continuation_source_line = line_idx

                # Re-parse parameters now that operands are extended
                pos, kw = parse_parameters(current_logical_stmt.raw_operands)
                current_logical_stmt.positional_params = pos
                current_logical_stmt.keyword_params = kw

                # Check if this DD defined in-stream data
                if current_logical_stmt.statement_type == "DD":
                    raw_ops_upper = current_logical_stmt.raw_operands.upper()
                    if "*" in current_logical_stmt.positional_params or "DATA" in current_logical_stmt.positional_params:
                        in_stream = True
                        in_stream_type = "DATA" if "DATA" in current_logical_stmt.positional_params else "STAR"
                        current_instream_stmt = current_logical_stmt
                        if "DLM" in current_logical_stmt.keyword_params:
                            dlm_val = current_logical_stmt.keyword_params["DLM"].strip("'\"")
                            in_stream_delimiter = dlm_val

                continue
        else:
            if is_continuation_line:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        rule_id="UNEXPECTED_CONTINUATION",
                        line=line_idx,
                        column=3,
                        message=f"Line {line_idx}: Statement appears formatted as a continuation (column 3 blank), but preceding line {line_idx - 1} did not end with a continuation comma.",
                        suggested_fix="Add a statement name or remove column 3 space if this is a new statement.",
                    )
                )

        # 8. Parse standard new JCL statement
        # Format: //NAME OPERATION PARAMETERS [COMMENTS]
        # or unnamed: // OPERATION PARAMETERS [COMMENTS]
        stmt_match = re.match(r"^//([A-Z0-9$#@]{1,8})?\s+([A-Z]{1,10})\b(.*)$", line, re.IGNORECASE)

        if not stmt_match:
            # Check for name longer than 8 characters
            bad_name = re.match(r"^//(\S+)", line)
            if bad_name:
                cand_name = bad_name.group(1)
                if len(cand_name) > 8:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            rule_id="NAME_EXCEEDS_8_CHARS",
                            line=line_idx,
                            column=3,
                            message=f"Line {line_idx}: Statement name '{cand_name}' exceeds maximum z/OS limit of 8 characters.",
                            suggested_fix="Shorten statement name to 1-8 alphanumeric/national characters.",
                        )
                    )
            # Create generic unknown statement
            stmt_unrec = LogicalStatement(
                statement_type="UNKNOWN",
                start_line=line_idx,
                end_line=line_idx,
                physical_lines=[(line_idx, line)],
                raw_operands=line[2:].strip(),
                step_name=current_step_name,
                source_column=1,
            )
            statements.append(stmt_unrec)
            current_logical_stmt = stmt_unrec
            has_trailing_continuation = False
            continue

        raw_name = (stmt_match.group(1) or "").upper()
        operation = stmt_match.group(2).upper()
        rest_of_line = stmt_match.group(3).strip()

        operands_field, comment_field = split_operands_and_comment(rest_of_line)
        pos_params, kw_params = parse_parameters(operands_field)

        name_col = 3 if raw_name else None

        # Operation column: locate operation after column 2
        op_match = re.search(r"\b" + re.escape(operation) + r"\b", line[2:])
        op_col = (op_match.start() + 3) if op_match else 3

        # Operands column: locate operands field start after operation
        operands_col = None
        if operands_field:
            after_op = line[op_col - 1 + len(operation):]
            leading_spaces = len(after_op) - len(after_op.lstrip(" "))
            operands_col = op_col + len(operation) + leading_spaces

        if operation == "JOB":
            current_step_name = None
            assigned_step = None
        elif operation == "EXEC":
            current_step_name = raw_name or f"STEP_{line_idx}"
            assigned_step = current_step_name
        else:
            assigned_step = current_step_name

        logical_stmt = LogicalStatement(
            statement_type=operation,
            name=raw_name,
            operation=operation,
            start_line=line_idx,
            end_line=line_idx,
            physical_lines=[(line_idx, line)],
            raw_operands=operands_field,
            in_line_comment=comment_field,
            positional_params=pos_params,
            keyword_params=kw_params,
            step_name=assigned_step,
            source_column=1,
            name_column=name_col,
            operation_column=op_col,
            operands_column=operands_col,
        )
        statements.append(logical_stmt)
        current_logical_stmt = logical_stmt

        # Check if line ends with comma indicating continuation
        has_trailing_continuation = operands_field.rstrip().endswith(",")
        continuation_source_line = line_idx

        # Check for in-stream dataset definition: DD * or DD DATA
        if operation == "DD":
            is_star = "*" in pos_params or any(re.search(r"(?:^|\s)\*(?:\s|,|$)", p) for p in pos_params)
            is_data = "DATA" in pos_params or any(re.search(r"(?:^|\s)DATA(?:\s|,|$)", p) for p in pos_params)

            if is_star or is_data:
                in_stream = True
                in_stream_type = "DATA" if is_data else "STAR"
                in_stream_delimiter = "/*"
                logical_stmt.instream_type = in_stream_type
                current_instream_stmt = logical_stmt

                if "DLM" in kw_params:
                    in_stream_delimiter = kw_params["DLM"].strip("'\"")
                    logical_stmt.instream_delimiter = in_stream_delimiter

    # Post-parse: If in-stream mode was still active when file ended
    if in_stream and current_instream_stmt:
        diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                rule_id="UNTERMINATED_IN_STREAM_DATA",
                line=current_instream_stmt.start_line,
                column=1,
                message=f"In-stream dataset under DD '{current_instream_stmt.name or 'SYSIN'}' was not terminated with delimiter '{in_stream_delimiter}'.",
                suggested_fix=f"Add '{in_stream_delimiter}' delimiter statement at the end of the in-stream payload.",
            )
        )

    return ParsedJcl(
        raw_lines=raw_lines,
        physical_lines=physical_lines,
        statements=statements,
        diagnostics=diagnostics,
    )

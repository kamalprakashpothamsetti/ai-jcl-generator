"""Deterministic analyzer for IBM z/OS job logs, abends, and JCL error correlation."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from backend.error_explainer.knowledge_base import (
    ErrorKnowledgeEntry,
    lookup_error_knowledge,
)
from backend.error_explainer.models import (
    DetectedError,
    ExplainErrorResponse,
    RelatedJclLine,
)
from backend.error_explainer.patterns import (
    PATTERN_EXPLICIT_ABEND,
    PATTERN_IEC_ABEND,
    PATTERN_IEF142I,
    PATTERN_IEF450I,
    PATTERN_IEF452I,
    PATTERN_JCL_MESSAGES,
    PATTERN_JOB_NAME,
    PATTERN_REASON_CODE,
    PATTERN_RETURN_CODE,
    PATTERN_STANDALONE_S_ABEND,
    PATTERN_STEP_NAME,
    PATTERN_SYSTEM_ABEND_PHRASE,
    PATTERN_USER_ABEND,
    PATTERN_UTILITY_MESSAGES,
)
from backend.validation.parser import LogicalStatement, parse_jcl_structure


def analyze_log(log_text: str, jcl: Optional[str] = None) -> ExplainErrorResponse:
    """Performs deterministic, offline analysis of mainframe job logs, abends, and utility messages."""
    if not log_text or not log_text.strip():
        raise ValueError("Log text cannot be empty.")

    raw_lines = log_text.splitlines()
    detected: List[DetectedError] = []
    seen_keys: Set[Tuple[str, int]] = set()

    extracted_job_name: Optional[str] = None
    extracted_step_name: Optional[str] = None

    for line_idx, line in enumerate(raw_lines, start=1):
        line_clean = line.strip()
        if not line_clean:
            continue

        # -------------------------------------------------------------
        # 1. Structured IEF450I: Step Abnormal Termination
        # -------------------------------------------------------------
        m_450 = PATTERN_IEF450I.search(line_clean)
        if m_450:
            job = m_450.group("job").upper()
            step = m_450.group("step").upper()
            abend_raw = m_450.group("abend").upper()
            reason = m_450.group("reason")
            extracted_job_name = extracted_job_name or job
            extracted_step_name = extracted_step_name or step

            # Normalize abend code (e.g. S806 or 806 -> S806)
            abend_code = abend_raw
            if not abend_code.startswith("S") and not abend_code.startswith("U"):
                abend_code = f"S{abend_code}"

            kb_abend = lookup_error_knowledge(abend_code)
            reason_desc = ""
            if kb_abend and reason and reason.upper() in kb_abend.reason_codes:
                reason_desc = f" ({kb_abend.reason_codes[reason.upper()]})"

            abend_msg = (
                f"{kb_abend.title if kb_abend else 'Abnormal program termination'}{reason_desc}"
            )

            # Record ABEND error
            key = (abend_code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                detected.append(
                    DetectedError(
                        code=abend_code,
                        category="abend" if abend_code.startswith("S") else "user_abend",
                        severity="error",
                        message=abend_msg,
                        source_line=line_idx,
                        evidence=line_clean,
                        step_name=step,
                        job_name=job,
                        reason_code=reason,
                    )
                )

            # Also record IEF450I message
            key_450 = ("IEF450I", line_idx)
            if key_450 not in seen_keys:
                seen_keys.add(key_450)
                detected.append(
                    DetectedError(
                        code="IEF450I",
                        category="system_message",
                        severity="error",
                        message=f"Step '{step}' in job '{job}' terminated abnormally with {abend_code}.",
                        source_line=line_idx,
                        evidence=line_clean,
                        step_name=step,
                        job_name=job,
                        reason_code=reason,
                    )
                )
            continue

        # -------------------------------------------------------------
        # 2. Structured IEF452I: Job Failed JCL Error
        # -------------------------------------------------------------
        m_452 = PATTERN_IEF452I.search(line_clean)
        if m_452:
            job = m_452.group("job").upper()
            extracted_job_name = extracted_job_name or job
            key_452 = ("IEF452I", line_idx)
            if key_452 not in seen_keys:
                seen_keys.add(key_452)
                detected.append(
                    DetectedError(
                        code="IEF452I",
                        category="jcl_error",
                        severity="error",
                        message=f"Job Failed - JCL Error: Job '{job}' failed due to JCL converter or interpreter errors.",
                        source_line=line_idx,
                        evidence=line_clean,
                        job_name=job,
                    )
                )
            continue

        # -------------------------------------------------------------
        # 3. Structured IEF142I: Step Executed Condition Code
        # -------------------------------------------------------------
        m_142 = PATTERN_IEF142I.search(line_clean)
        if m_142:
            job = m_142.group("job").upper()
            step = m_142.group("step").upper()
            rc_str = m_142.group("rc")
            rc_int = int(rc_str)
            extracted_job_name = extracted_job_name or job
            extracted_step_name = extracted_step_name or step

            rc_code = f"RC={rc_str}"
            severity = (
                "info" if rc_int == 0 else ("warning" if rc_int <= 4 else "error")
            )

            key_rc = (rc_code, line_idx)
            if key_rc not in seen_keys:
                seen_keys.add(key_rc)
                kb_rc = lookup_error_knowledge(rc_code)
                detected.append(
                    DetectedError(
                        code=rc_code,
                        category="return_code",
                        severity=severity,
                        message=kb_rc.title if kb_rc else f"Step executed with condition code {rc_str}",
                        source_line=line_idx,
                        evidence=line_clean,
                        step_name=step,
                        job_name=job,
                    )
                )
            continue

        # -------------------------------------------------------------
        # 4. IEC Messages & Explicit ABEND= or Phrase
        # -------------------------------------------------------------
        m_iec = PATTERN_IEC_ABEND.search(line_clean)
        if m_iec:
            code_raw = m_iec.group("code").upper()
            reason = m_iec.group("reason")
            code = code_raw if code_raw.startswith("S") else f"S{code_raw}"
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                reason_desc = ""
                if kb and reason and reason.upper() in kb.reason_codes:
                    reason_desc = f" ({kb.reason_codes[reason.upper()]})"
                detected.append(
                    DetectedError(
                        code=code,
                        category="abend",
                        severity="error",
                        message=f"{kb.title if kb else f'System abend {code}'}{reason_desc}",
                        source_line=line_idx,
                        evidence=line_clean,
                        reason_code=reason,
                    )
                )

        m_ab = PATTERN_EXPLICIT_ABEND.search(line_clean)
        if m_ab:
            code = m_ab.group("code").upper()
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                detected.append(
                    DetectedError(
                        code=code,
                        category="abend" if code.startswith("S") else "user_abend",
                        severity="error",
                        message=kb.title if kb else f"Abend condition {code}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        m_sys_phrase = PATTERN_SYSTEM_ABEND_PHRASE.search(line_clean)
        if m_sys_phrase:
            code = f"S{m_sys_phrase.group('code').upper()}"
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                detected.append(
                    DetectedError(
                        code=code,
                        category="abend",
                        severity="error",
                        message=kb.title if kb else f"System abend {code}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        # -------------------------------------------------------------
        # 5. Standalone System ABEND codes (S0C7, S0C4, S013, etc.)
        # -------------------------------------------------------------
        m_s = PATTERN_STANDALONE_S_ABEND.finditer(line_clean)
        for match in m_s:
            code = match.group("code").upper()
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                detected.append(
                    DetectedError(
                        code=code,
                        category="abend",
                        severity="error",
                        message=kb.title if kb else f"System abend {code}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        # -------------------------------------------------------------
        # 6. Standalone User ABEND codes (e.g. U4038)
        # -------------------------------------------------------------
        m_u = PATTERN_USER_ABEND.finditer(line_clean)
        for match in m_u:
            code = match.group("code").upper()
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                detected.append(
                    DetectedError(
                        code=code,
                        category="user_abend",
                        severity="error",
                        message=kb.title if kb else f"User abend {code}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        # -------------------------------------------------------------
        # 7. Generic Return Code / Condition Code (RC=..., COND CODE ...)
        # -------------------------------------------------------------
        m_rc = PATTERN_RETURN_CODE.finditer(line_clean)
        for match in m_rc:
            rc_raw = match.group("rc")
            rc_int = int(rc_raw)
            rc_code = f"RC={rc_raw.zfill(4)}"
            key = (rc_code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(rc_code)
                severity = (
                    "info" if rc_int == 0 else ("warning" if rc_int <= 4 else "error")
                )
                detected.append(
                    DetectedError(
                        code=rc_code,
                        category="return_code",
                        severity=severity,
                        message=kb.title if kb else f"Return code {rc_raw}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        # -------------------------------------------------------------
        # 8. Utility message IDs (DFSORT ICE..., IDCAMS IDC..., IEBGENER IEB...)
        # -------------------------------------------------------------
        m_util = PATTERN_UTILITY_MESSAGES.finditer(line_clean)
        for match in m_util:
            code = match.group("code").upper()
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                detected.append(
                    DetectedError(
                        code=code,
                        category="utility",
                        severity="error",
                        message=kb.title if kb else f"IBM utility message {code}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        # -------------------------------------------------------------
        # 9. Generic JCL / JES Messages (IEFC001I, IEF210I, etc.)
        # -------------------------------------------------------------
        m_jcl = PATTERN_JCL_MESSAGES.finditer(line_clean)
        for match in m_jcl:
            code = match.group("code").upper()
            if code in ("IEF450I", "IEF452I", "IEF142I"):
                continue  # Handled with higher structure above
            key = (code, line_idx)
            if key not in seen_keys:
                seen_keys.add(key)
                kb = lookup_error_knowledge(code)
                detected.append(
                    DetectedError(
                        code=code,
                        category="jcl_error",
                        severity="error",
                        message=kb.title if kb else f"JCL system message {code}",
                        source_line=line_idx,
                        evidence=line_clean,
                    )
                )

        # Check for secondary step/job hints on the line
        if not extracted_step_name:
            st = PATTERN_STEP_NAME.search(line_clean)
            if st:
                extracted_step_name = st.group("step").upper()
        if not extracted_job_name:
            jb = PATTERN_JOB_NAME.search(line_clean)
            if jb:
                extracted_job_name = jb.group("job").upper()

    # Backfill step_name and job_name if found anywhere in log
    for err in detected:
        if not err.step_name and extracted_step_name:
            err.step_name = extracted_step_name
        if not err.job_name and extracted_job_name:
            err.job_name = extracted_job_name

    # -----------------------------------------------------------------
    # Build Synthesized Summary, Likely Causes, Troubleshooting Steps
    # -----------------------------------------------------------------
    likely_causes: List[str] = []
    troubleshooting_steps: List[str] = []
    seen_causes: Set[str] = set()
    seen_steps: Set[str] = set()

    # Sort errors prioritizing ABENDs and errors over warnings/info
    def sort_key(e: DetectedError):
        sev_rank = {"error": 0, "warning": 1, "info": 2}.get(e.severity, 3)
        cat_rank = {"abend": 0, "user_abend": 1, "jcl_error": 2, "utility": 3, "return_code": 4}.get(e.category, 5)
        return (sev_rank, cat_rank, e.source_line)

    detected.sort(key=sort_key)

    primary_error: Optional[DetectedError] = detected[0] if detected else None

    if not detected:
        summary = (
            "No standard IBM ABEND codes, JCL error messages, or non-zero condition codes "
            "were identified in the provided log text."
        )
        likely_causes = [
            "The provided log text does not contain recognized JES messages (such as IEF450I, IEF452I), system ABENDs (e.g. S0C7, S806), or return codes.",
            "The job output may be incomplete, truncated, or copied from a non-z/OS system.",
        ]
        troubleshooting_steps = [
            "Verify that you have pasted the JESYSMSG, JESMSGLG, or SYSOUT output from the job execution.",
            "Check for lines starting with 'IEF' or containing 'ABEND' or 'COND CODE'.",
        ]
    else:
        # Check if only normal completion (e.g. RC=0000)
        has_errors = any(e.severity == "error" for e in detected)
        has_warnings = any(e.severity == "warning" for e in detected)

        if not has_errors and not has_warnings:
            summary = (
                f"The job step completed successfully with {primary_error.code}. No execution failures detected."
            )
        else:
            step_phrase = f"in step '{primary_error.step_name}' " if primary_error.step_name else ""
            job_phrase = f"for job '{primary_error.job_name}' " if primary_error.job_name else ""
            summary = f"The job execution {job_phrase}{step_phrase}encountered {primary_error.code}: {primary_error.message}."

        for err in detected:
            kb = lookup_error_knowledge(err.code)
            if kb:
                for c in kb.likely_causes:
                    if c not in seen_causes:
                        seen_causes.add(c)
                        likely_causes.append(c)
                for s in kb.troubleshooting_steps:
                    if s not in seen_steps:
                        seen_steps.add(s)
                        troubleshooting_steps.append(s)

    # -----------------------------------------------------------------
    # JCL Error Correlation
    # -----------------------------------------------------------------
    related_jcl_lines: List[RelatedJclLine] = []
    if jcl and jcl.strip():
        parsed_jcl = parse_jcl_structure(jcl)
        target_step = extracted_step_name

        # If a step is known, locate the EXEC statement and related DDs
        if target_step:
            exec_stmts = [
                s for s in parsed_jcl.statements
                if s.statement_type == "EXEC" and s.name.upper() == target_step
            ]
            for exec_stmt in exec_stmts:
                pgm_val = exec_stmt.keyword_params.get("PGM", "")
                relevance_msg = f"Step '{target_step}' EXEC statement"
                if any(e.code == "S806" for e in detected):
                    relevance_msg += f" specifying PGM={pgm_val or 'unspecified'}, which failed to locate or load."
                else:
                    relevance_msg += f" (PGM={pgm_val})."

                related_jcl_lines.append(
                    RelatedJclLine(
                        line_number=exec_stmt.start_line,
                        statement_type="EXEC",
                        content=exec_stmt.physical_lines[0][1] if exec_stmt.physical_lines else f"//{target_step} EXEC ...",
                        relevance=relevance_msg,
                    )
                )

                # For S806, inspect if STEPLIB or JOBLIB is present
                if any(e.code == "S806" for e in detected):
                    steplib_dds = [
                        s for s in parsed_jcl.statements
                        if s.statement_type == "DD" and s.step_name == target_step and s.name.upper() == "STEPLIB"
                    ]
                    joblib_dds = [
                        s for s in parsed_jcl.statements
                        if s.statement_type == "DD" and s.name.upper() == "JOBLIB"
                    ]
                    for s_dd in steplib_dds:
                        related_jcl_lines.append(
                            RelatedJclLine(
                                line_number=s_dd.start_line,
                                statement_type="DD",
                                content=s_dd.physical_lines[0][1] if s_dd.physical_lines else "//STEPLIB DD ...",
                                relevance="STEPLIB private load library defined for this step.",
                            )
                        )
                    for j_dd in joblib_dds:
                        related_jcl_lines.append(
                            RelatedJclLine(
                                line_number=j_dd.start_line,
                                statement_type="DD",
                                content=j_dd.physical_lines[0][1] if j_dd.physical_lines else "//JOBLIB DD ...",
                                relevance="JOBLIB job-wide load library defined for this job.",
                            )
                        )

                # For dataset errors (S013, S837, S913, ICE083A, IEB311I), check for mentioned DDs
                dataset_codes = {"S013", "S837", "S913", "ICE083A", "IEB311I"}
                if any(e.code in dataset_codes for e in detected):
                    step_dds = [
                        s for s in parsed_jcl.statements
                        if s.statement_type == "DD" and s.step_name == target_step
                    ]
                    for d_stmt in step_dds:
                        dd_name = d_stmt.name.upper()
                        # Check if DD name is mentioned in log text
                        if re.search(r"\b" + re.escape(dd_name) + r"\b", log_text, re.IGNORECASE):
                            related_jcl_lines.append(
                                RelatedJclLine(
                                    line_number=d_stmt.start_line,
                                    statement_type="DD",
                                    content=d_stmt.physical_lines[0][1] if d_stmt.physical_lines else f"//{dd_name} DD ...",
                                    relevance=f"DD '{dd_name}' referenced in error log.",
                                )
                            )

    limitations = [
        "Diagnosis is based on supplied log text, not live JES access or active z/OS catalog verification.",
        "Always verify dataset dispositions, security permissions, and load modules in your specific z/OS environment.",
    ]

    return ExplainErrorResponse(
        detected_errors=detected,
        summary=summary,
        likely_causes=likely_causes,
        troubleshooting_steps=troubleshooting_steps,
        related_jcl_lines=related_jcl_lines,
        limitations=limitations,
        ai_used=False,
        confidence_notes="Deterministic rules matched based on authoritative IBM z/OS System Codes and message reference catalogs.",
    )

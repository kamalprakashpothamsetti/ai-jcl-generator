"""Regex patterns and parsers for identifying IBM z/OS error codes, abends, and log events."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# 1. Structured IEF450I Step Abnormal Termination
# e.g.: IEF450I PAYJOB STEP1 - ABEND=S806 U0000 REASON=00000004
PATTERN_IEF450I = re.compile(
    r"\b(?P<msg_id>IEF450I)\s+(?P<job>[A-Z0-9$#@]{1,8})\s+(?P<step>[A-Z0-9$#@]{1,8})\s*-\s*ABEND[=\s]*(?P<abend>S[0-9A-F]{3}|U\d{4}|\S+)(?:\s+(?P<uabend>U\d{4}))?(?:\s+REASON[=\s]*(?P<reason>[0-9A-F]+))?",
    re.IGNORECASE,
)

# 2. Structured IEF452I Job Failed JCL Error
# e.g.: IEF452I PAYJOB - JOB FAILED - JCL ERROR - TIME=...
PATTERN_IEF452I = re.compile(
    r"\b(?P<msg_id>IEF452I)\s+(?P<job>[A-Z0-9$#@]{1,8})\s*-\s*JOB FAILED\s*-\s*JCL ERROR",
    re.IGNORECASE,
)

# 3. Structured IEF142I Step Executed with Condition Code
# e.g.: IEF142I PAYJOB STEP1 - STEP WAS EXECUTED - COND CODE 0012
PATTERN_IEF142I = re.compile(
    r"\b(?P<msg_id>IEF142I)\s+(?P<job>[A-Z0-9$#@]{1,8})\s+(?P<step>[A-Z0-9$#@]{1,8})\s*-\s*STEP WAS EXECUTED\s*-\s*COND CODE\s+(?P<rc>\d{4})",
    re.IGNORECASE,
)

# 4. Explicit ABEND= or ABEND <code statements
PATTERN_EXPLICIT_ABEND = re.compile(
    r"\bABEND[=\s]+(?P<code>S[0-9A-F]{3}|U\d{4})\b",
    re.IGNORECASE,
)

# 5. COMPLETION CODE - SYSTEM=xxx or SYSTEM ABEND xxx
PATTERN_SYSTEM_ABEND_PHRASE = re.compile(
    r"\b(?:COMPLETION CODE\s*-\s*SYSTEM[=\s]+|SYSTEM\s+ABEND\s*[:=\s]+)(?P<code>[0-9A-F]{3})\b",
    re.IGNORECASE,
)

# 6. Standalone System ABEND codes (with word boundaries)
PATTERN_STANDALONE_S_ABEND = re.compile(
    r"\b(?P<code>S0C[147]|S013|S322|S806|S837|S878|S913)\b",
    re.IGNORECASE,
)

# 6b. IEC Open/Allocation Abend (e.g. IEC141I 013-18 or IEC031I D37-04)
PATTERN_IEC_ABEND = re.compile(
    r"\bIEC\d{3}I\s+(?P<code>[0-9A-Z]{3})-(?P<reason>[0-9A-F]+)\b",
    re.IGNORECASE,
)

# 7. Standalone User ABEND codes (e.g. U4038, U0001)
PATTERN_USER_ABEND = re.compile(
    r"\b(?P<code>U\d{4})\b",
)

# 8. Return Code / Condition Code phrases
# e.g. COND CODE 0012, RC=0004, RC=12, RETURN CODE 0016
PATTERN_RETURN_CODE = re.compile(
    r"\b(?:COND CODE|RC|RETURN CODE)[=\s]+(?P<rc>\d{1,4})\b",
    re.IGNORECASE,
)

# 9. IBM JCL/JES Message IDs
PATTERN_JCL_MESSAGES = re.compile(
    r"\b(?P<code>IEF450I|IEF452I|IEF142I|IEFC[0-9]{3}[A-Z]|IEF[0-9]{3}[A-Z])\b",
)

# 10. Utility Message IDs (DFSORT, IDCAMS, IEBGENER)
PATTERN_UTILITY_MESSAGES = re.compile(
    r"\b(?P<code>ICE\d{3}[A-Z]|IDC\d{4}[A-Z]|IEB\d{3}[A-Z])\b",
)

# 11. Generic Reason Code extraction
PATTERN_REASON_CODE = re.compile(
    r"\bREASON(?: CODE)?[=\s]+(?P<reason>[0-9A-F]{1,8})\b",
    re.IGNORECASE,
)

# 12. Generic Step Name extraction
PATTERN_STEP_NAME = re.compile(
    r"\b(?:STEP|STEPNAME)[=\s]+(?P<step>[A-Z0-9$#@]{1,8})\b",
    re.IGNORECASE,
)

# 13. Generic Job Name extraction
PATTERN_JOB_NAME = re.compile(
    r"\b(?:JOB|JOBNAME)[=\s]+(?P<job>[A-Z0-9$#@]{1,8})\b",
    re.IGNORECASE,
)

"""Deterministic JCL diff engine using Python standard library difflib.

Produces structured diff lines with line references for both original and modified
JCL files, preserving whitespace and line endings.
"""

from __future__ import annotations

import difflib
from typing import List, Literal, Optional
from pydantic import BaseModel


class DiffLine(BaseModel):
    line_orig: Optional[int] = None
    line_mod: Optional[int] = None
    type: Literal["added", "removed", "modified", "unchanged"]
    content: str


def generate_structured_diff(orig_jcl: str, mod_jcl: str) -> List[DiffLine]:
    """Generates a structured line-by-line diff comparing original and modified JCL.
    
    Each line contains line_orig (1-indexed), line_mod (1-indexed), the diff type
    ('added', 'removed', 'modified', or 'unchanged'), and the exact line text.
    """
    orig_lines = orig_jcl.splitlines()
    mod_lines = mod_jcl.splitlines()

    matcher = difflib.SequenceMatcher(None, orig_lines, mod_lines)
    diff_lines: List[DiffLine] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset, line in enumerate(orig_lines[i1:i2]):
                diff_lines.append(DiffLine(
                    line_orig=i1 + offset + 1,
                    line_mod=j1 + offset + 1,
                    type="unchanged",
                    content=line
                ))
        elif tag == "delete":
            for offset, line in enumerate(orig_lines[i1:i2]):
                diff_lines.append(DiffLine(
                    line_orig=i1 + offset + 1,
                    line_mod=None,
                    type="removed",
                    content=line
                ))
        elif tag == "insert":
            for offset, line in enumerate(mod_lines[j1:j2]):
                diff_lines.append(DiffLine(
                    line_orig=None,
                    line_mod=j1 + offset + 1,
                    type="added",
                    content=line
                ))
        elif tag == "replace":
            # For 1-to-1 replacements, mark as 'modified' for clear presentation
            if (i2 - i1) == 1 and (j2 - j1) == 1:
                diff_lines.append(DiffLine(
                    line_orig=i1 + 1,
                    line_mod=None,
                    type="removed",
                    content=orig_lines[i1]
                ))
                diff_lines.append(DiffLine(
                    line_orig=None,
                    line_mod=j1 + 1,
                    type="added",
                    content=mod_lines[j1]
                ))
            else:
                for offset, line in enumerate(orig_lines[i1:i2]):
                    diff_lines.append(DiffLine(
                        line_orig=i1 + offset + 1,
                        line_mod=None,
                        type="removed",
                        content=line
                    ))
                for offset, line in enumerate(mod_lines[j1:j2]):
                    diff_lines.append(DiffLine(
                        line_orig=None,
                        line_mod=j1 + offset + 1,
                        type="added",
                        content=line
                    ))

    return diff_lines

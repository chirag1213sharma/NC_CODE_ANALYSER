"""
NC Code Analyser - Operation Separator

Separates NC file lines into named operations.
The main() function is the single entry-point consumed by the rest of the
pipeline (nc_parser, diff_engine, etc.).  Populate the body to implement
whatever detection heuristic is needed; the contract below must be kept.
"""

from typing import Dict, List
import os
import re
from multiprocessing import Pool
from pathlib import Path
from collections import defaultdict
import json


def detect_encoding(file_path: Path) -> str:
    """Detect the file encoding by trying common encodings."""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                f.read()
            return encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    # Default to latin-1 if all fail
    return 'latin-1'


def clean_line(line : str) -> str:
    line = line.removesuffix("\n")    # Remove \n from end
    line = re.sub(r'^N\d+\s', '', line)   # Remove N number from start of line
    return line.strip()

def clean_operation(operation : str) -> str:
    operation = operation.removeprefix("(")
    operation = operation.removesuffix(")")
    return operation.strip()


def main(lines: List[str]) -> Dict[str, List[str]]:
    """
    Separate NC file lines into named operations.

    Args:
        lines: All raw line strings from an NC file, in file order.
               May be from either a baseline or a result file.

    Returns:
        Ordered dictionary (insertion order = file order) where:
            Key   – operation name  (str)
            Value – list of lines that belong to that operation,
                    *excluding* the operation-name line itself.

        Lines that contain only a program/sub-program number (O-word)
        or a bare tool-number call are ignored and do not appear in any
        value list.

        Example:
            {
                "Profile Milling":  ["G90 G94 G17", "G0 X10. Y5.", ...],
                "Center Drilling":  ["G43 H2", "G81 X0. Y0. Z-5. R2.", ...],
            }

    Notes:
        - Return an empty dict {} if no named operations can be detected;
          the parser will fall back to tool-change-based boundaries.
        - Preserve the order operations appear in the file so that the
          diff engine can correlate baseline vs. result operations.
    """
    nc_map = defaultdict(list)
    continue_operation = False
    current_operation = ""
    for line in lines:
        if line == "\n":
            continue_operation = False
        line = clean_line(line)
        if line.startswith('( '):
            current_operation = clean_operation(line)
            continue_operation = True
            nc_map[current_operation]
        elif continue_operation:
            nc_map[current_operation].append(line)

    return nc_map


if __name__ == "__main__":
    file_path = r"C:\NC_CODE_ANALYSER\Example_Result\Sample1.txt"
    lines = []
    with open(file_path, "r", encoding=detect_encoding(file_path)) as nc:
        for line in nc:
            lines.append(line)
    nc_map = main(lines)
    for key, value in nc_map.items():
        print(key)
        print(value)
"""
NC Code Analyser - Difference Detection Engine
"""

import difflib
import re
import time
from typing import List, Optional, Tuple, Dict
from datetime import datetime
import uuid

# Regex used to strip the leading NC block / sequence number (e.g. "N100 ").
# Block numbers are renumbered automatically when an operation gains or loses
# lines, which would otherwise cascade as "diffs" through every subsequent
# operation even though the actual G/M-code content is unchanged.
_N_NUMBER_PREFIX_RE = re.compile(r'^\s*N\d+\s*', re.IGNORECASE)


def _strip_n_number(text: Optional[str]) -> Optional[str]:
    """Remove a leading N-block-number from an NC line.

    Returns the input unchanged if it is None or has no leading N number.
    """
    if text is None:
        return None
    return _N_NUMBER_PREFIX_RE.sub('', text, count=1)

from src.parser import NCParser, NCProgram, NCCommand, ParseResult
from src.parser.gcode_definitions import is_critical_change, get_gcode_info, get_mcode_info
from src.diff_engine.models import (
    DiffResult, LineDiff, CommandDiff, OperationDiff,
    ComparisonSummary, ChangeType, ChangeSeverity, ChangeCategory,
    AnalysisResult, ClassificationResult
)
from src.core import get_logger

logger = get_logger(__name__)


class DiffEngine:
    """Engine for detecting and analyzing differences between NC files."""

    def __init__(self):
        """Initialize the diff engine."""
        self.parser = NCParser()

    def compare_files(
        self,
        baseline_path: str,
        new_path: str,
    ) -> DiffResult:
        """Compare two NC files and return differences."""
        # Parse both files
        baseline_result = self.parser.parse_file(baseline_path)
        new_result = self.parser.parse_file(new_path)

        if not baseline_result.success or not baseline_result.program:
            raise ValueError(f"Failed to parse baseline file: {baseline_result.errors}")
        if not new_result.success or not new_result.program:
            raise ValueError(f"Failed to parse new file: {new_result.errors}")

        return self._compare_programs(
            baseline_result.program,
            new_result.program,
        )

    def compare_content(
        self,
        baseline_content: str,
        new_content: str,
        baseline_name: str = "baseline.nc",
        new_name: str = "new.nc",
    ) -> DiffResult:
        """Compare NC content strings and return differences."""
        # Parse both contents
        baseline_result = self.parser.parse_content(baseline_content, baseline_name)
        new_result = self.parser.parse_content(new_content, new_name)

        if not baseline_result.success or not baseline_result.program:
            raise ValueError(f"Failed to parse baseline content: {baseline_result.errors}")
        if not new_result.success or not new_result.program:
            raise ValueError(f"Failed to parse new content: {new_result.errors}")

        return self._compare_programs(
            baseline_result.program,
            new_result.program,
        )

    def _compare_programs(
        self,
        baseline: NCProgram,
        new: NCProgram,
    ) -> DiffResult:
        """Compare two parsed NC programs."""
        start_time = time.time()

        # Check if files are identical
        if baseline.file_hash == new.file_hash:
            return DiffResult(
                baseline_file=baseline.file_name,
                baseline_hash=baseline.file_hash,
                new_file=new.file_name,
                new_hash=new.file_hash,
                files_identical=True,
                summary=ComparisonSummary(
                    total_lines_old=baseline.total_lines,
                    total_lines_new=new.total_lines,
                    total_operations_old=baseline.total_operations,
                    total_operations_new=new.total_operations,
                    lines_unchanged=baseline.total_lines,
                ),
                comparison_time_ms=(time.time() - start_time) * 1000
            )

        # Get line-level differences
        line_diffs = self._compute_line_diffs(baseline, new)

        # Get command-level differences (more detailed)
        command_diffs = self._compute_command_diffs(baseline, new, line_diffs)

        # Get operation-level differences
        operation_diffs = self._compute_operation_diffs(baseline, new, command_diffs)

        # Compute summary
        summary = self._compute_summary(baseline, new, line_diffs, command_diffs, operation_diffs)

        comparison_time = (time.time() - start_time) * 1000

        # Build line-number -> raw-text lookups so the AI prompt builder can
        # attach ±N lines of unchanged context around each changed line.
        baseline_lines_by_number = {
            cmd.line_number: cmd.raw_text for cmd in baseline.all_commands
        }
        new_lines_by_number = {
            cmd.line_number: cmd.raw_text for cmd in new.all_commands
        }

        return DiffResult(
            baseline_file=baseline.file_name,
            baseline_hash=baseline.file_hash,
            new_file=new.file_name,
            new_hash=new.file_hash,
            files_identical=False,
            line_diffs=line_diffs,
            command_diffs=command_diffs,
            operation_diffs=operation_diffs,
            summary=summary,
            comparison_time_ms=comparison_time,
            baseline_lines_by_number=baseline_lines_by_number,
            new_lines_by_number=new_lines_by_number,
        )

    def _compute_line_diffs(
        self,
        baseline: NCProgram,
        new: NCProgram,
    ) -> List[LineDiff]:
        """Compute line-by-line differences."""
        diffs: List[LineDiff] = []

        # Get raw lines, with leading N block numbers stripped so that block
        # renumbering caused by an operation gaining/losing lines does not
        # cascade as spurious diffs through every subsequent operation.
        baseline_lines = [_strip_n_number(cmd.raw_text) for cmd in baseline.all_commands]
        new_lines = [_strip_n_number(cmd.raw_text) for cmd in new.all_commands]

        # Use difflib for sequence matching
        matcher = difflib.SequenceMatcher(None, baseline_lines, new_lines)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # Lines are the same
                for idx, (old_idx, new_idx) in enumerate(zip(range(i1, i2), range(j1, j2))):
                    diffs.append(LineDiff(
                        line_number_old=baseline.all_commands[old_idx].line_number,
                        line_number_new=new.all_commands[new_idx].line_number,
                        content_old=baseline_lines[old_idx],
                        content_new=new_lines[new_idx],
                        change_type=ChangeType.UNCHANGED,
                    ))
            elif tag == 'replace':
                # Lines were modified
                for old_idx in range(i1, i2):
                    new_idx = j1 + (old_idx - i1) if j1 + (old_idx - i1) < j2 else None
                    diffs.append(LineDiff(
                        line_number_old=baseline.all_commands[old_idx].line_number,
                        line_number_new=new.all_commands[new_idx].line_number if new_idx is not None else None,
                        content_old=baseline_lines[old_idx],
                        content_new=new_lines[new_idx] if new_idx is not None else None,
                        change_type=ChangeType.MODIFIED,
                    ))
                # Handle case where new has more lines than old in this block
                for new_idx in range(j1 + (i2 - i1), j2):
                    diffs.append(LineDiff(
                        line_number_new=new.all_commands[new_idx].line_number,
                        content_new=new_lines[new_idx],
                        change_type=ChangeType.ADDED,
                    ))
            elif tag == 'delete':
                # Lines were removed
                for old_idx in range(i1, i2):
                    diffs.append(LineDiff(
                        line_number_old=baseline.all_commands[old_idx].line_number,
                        content_old=baseline_lines[old_idx],
                        change_type=ChangeType.REMOVED,
                    ))
            elif tag == 'insert':
                # Lines were added
                for new_idx in range(j1, j2):
                    diffs.append(LineDiff(
                        line_number_new=new.all_commands[new_idx].line_number,
                        content_new=new_lines[new_idx],
                        change_type=ChangeType.ADDED,
                    ))

        return diffs

    def _compute_command_diffs(
        self,
        baseline: NCProgram,
        new: NCProgram,
        line_diffs: List[LineDiff],
    ) -> List[CommandDiff]:
        """Compute command-level differences with parsed details."""
        command_diffs: List[CommandDiff] = []

        # Create lookup maps
        baseline_cmds = {cmd.line_number: cmd for cmd in baseline.all_commands}
        new_cmds = {cmd.line_number: cmd for cmd in new.all_commands}

        for line_diff in line_diffs:
            if line_diff.change_type == ChangeType.UNCHANGED:
                continue

            old_cmd = baseline_cmds.get(line_diff.line_number_old) if line_diff.line_number_old else None
            new_cmd = new_cmds.get(line_diff.line_number_new) if line_diff.line_number_new else None

            cmd_diff = CommandDiff(line_diff=line_diff)

            if line_diff.change_type == ChangeType.MODIFIED and old_cmd and new_cmd:
                # Analyze the specific changes
                cmd_diff = self._analyze_command_change(old_cmd, new_cmd, line_diff)
            elif line_diff.change_type == ChangeType.ADDED and new_cmd:
                cmd_diff.g_codes_added = new_cmd.g_codes
                cmd_diff.m_codes_added = new_cmd.m_codes
                cmd_diff.change_description = f"Added: {_strip_n_number(new_cmd.raw_text).strip()}"
                cmd_diff.is_critical = is_critical_change(new_cmd.g_codes, new_cmd.m_codes)
            elif line_diff.change_type == ChangeType.REMOVED and old_cmd:
                cmd_diff.g_codes_removed = old_cmd.g_codes
                cmd_diff.m_codes_removed = old_cmd.m_codes
                cmd_diff.change_description = f"Removed: {_strip_n_number(old_cmd.raw_text).strip()}"
                cmd_diff.is_critical = is_critical_change(old_cmd.g_codes, old_cmd.m_codes)

            # Determine category and severity
            self._categorize_change(cmd_diff)

            command_diffs.append(cmd_diff)

        return command_diffs

    def _analyze_command_change(
        self,
        old_cmd: NCCommand,
        new_cmd: NCCommand,
        line_diff: LineDiff,
    ) -> CommandDiff:
        """Analyze specific changes between two commands."""
        cmd_diff = CommandDiff(line_diff=line_diff)

        # G-code changes
        old_g = set(old_cmd.g_codes)
        new_g = set(new_cmd.g_codes)
        cmd_diff.g_codes_added = list(new_g - old_g)
        cmd_diff.g_codes_removed = list(old_g - new_g)

        # M-code changes
        old_m = set(old_cmd.m_codes)
        new_m = set(new_cmd.m_codes)
        cmd_diff.m_codes_added = list(new_m - old_m)
        cmd_diff.m_codes_removed = list(old_m - new_m)

        # Coordinate changes
        if old_cmd.coordinates and new_cmd.coordinates:
            for axis in ['x', 'y', 'z', 'a', 'b', 'c', 'i', 'j', 'k', 'r']:
                old_val = getattr(old_cmd.coordinates, axis)
                new_val = getattr(new_cmd.coordinates, axis)
                if old_val != new_val:
                    cmd_diff.coordinate_changes[axis.upper()] = (old_val, new_val)
        elif old_cmd.coordinates or new_cmd.coordinates:
            # One has coordinates, other doesn't
            coords = old_cmd.coordinates or new_cmd.coordinates
            for axis in ['x', 'y', 'z', 'a', 'b', 'c']:
                val = getattr(coords, axis)
                if val is not None:
                    if old_cmd.coordinates:
                        cmd_diff.coordinate_changes[axis.upper()] = (val, None)
                    else:
                        cmd_diff.coordinate_changes[axis.upper()] = (None, val)

        # Feed rate change
        if old_cmd.feed_rate != new_cmd.feed_rate:
            cmd_diff.feed_change = (old_cmd.feed_rate, new_cmd.feed_rate)

        # Spindle speed change
        if old_cmd.spindle_speed != new_cmd.spindle_speed:
            cmd_diff.speed_change = (old_cmd.spindle_speed, new_cmd.spindle_speed)

        # Tool change
        if old_cmd.tool_number != new_cmd.tool_number:
            cmd_diff.tool_change = (old_cmd.tool_number, new_cmd.tool_number)

        # Check if critical
        cmd_diff.is_critical = (
            is_critical_change(cmd_diff.g_codes_added + cmd_diff.g_codes_removed, 
                              cmd_diff.m_codes_added + cmd_diff.m_codes_removed) or
            bool(cmd_diff.coordinate_changes) or
            cmd_diff.tool_change is not None
        )

        # Build description
        descriptions = []
        if cmd_diff.g_codes_added:
            descriptions.append(f"Added G-codes: {', '.join(cmd_diff.g_codes_added)}")
        if cmd_diff.g_codes_removed:
            descriptions.append(f"Removed G-codes: {', '.join(cmd_diff.g_codes_removed)}")
        if cmd_diff.m_codes_added:
            descriptions.append(f"Added M-codes: {', '.join(cmd_diff.m_codes_added)}")
        if cmd_diff.m_codes_removed:
            descriptions.append(f"Removed M-codes: {', '.join(cmd_diff.m_codes_removed)}")
        if cmd_diff.coordinate_changes:
            coord_strs = [f"{k}: {v[0]} → {v[1]}" for k, v in cmd_diff.coordinate_changes.items()]
            descriptions.append(f"Coordinates: {', '.join(coord_strs)}")
        if cmd_diff.feed_change:
            descriptions.append(f"Feed: {cmd_diff.feed_change[0]} → {cmd_diff.feed_change[1]}")
        if cmd_diff.speed_change:
            descriptions.append(f"Speed: {cmd_diff.speed_change[0]} → {cmd_diff.speed_change[1]}")
        if cmd_diff.tool_change:
            descriptions.append(f"Tool: T{cmd_diff.tool_change[0]} → T{cmd_diff.tool_change[1]}")

        cmd_diff.change_description = "; ".join(descriptions) if descriptions else "Content modified"

        return cmd_diff

    def _categorize_change(self, cmd_diff: CommandDiff) -> None:
        """Categorize a command diff and assign severity."""
        line_diff = cmd_diff.line_diff

        # Determine category
        if cmd_diff.tool_change:
            line_diff.change_category = ChangeCategory.TOOL
            line_diff.severity = ChangeSeverity.CRITICAL
        elif cmd_diff.coordinate_changes:
            line_diff.change_category = ChangeCategory.COORDINATE
            line_diff.severity = ChangeSeverity.CRITICAL
        elif cmd_diff.g_codes_added or cmd_diff.g_codes_removed:
            # Determine based on G-code type
            all_g = cmd_diff.g_codes_added + cmd_diff.g_codes_removed
            if any(g in ['G00', 'G01', 'G02', 'G03', 'G0', 'G1', 'G2', 'G3'] for g in all_g):
                line_diff.change_category = ChangeCategory.MOTION
                line_diff.severity = ChangeSeverity.HIGH
            elif any(g.startswith('G8') for g in all_g):  # G80-G89 canned cycles
                line_diff.change_category = ChangeCategory.CANNED_CYCLE
                line_diff.severity = ChangeSeverity.HIGH
            elif any(g in ['G54', 'G55', 'G56', 'G57', 'G58', 'G59'] for g in all_g):
                line_diff.change_category = ChangeCategory.WORK_OFFSET
                line_diff.severity = ChangeSeverity.CRITICAL
            else:
                line_diff.change_category = ChangeCategory.MOTION
                line_diff.severity = ChangeSeverity.MEDIUM
        elif cmd_diff.m_codes_added or cmd_diff.m_codes_removed:
            all_m = cmd_diff.m_codes_added + cmd_diff.m_codes_removed
            if any(m in ['M03', 'M04', 'M05', 'M3', 'M4', 'M5'] for m in all_m):
                line_diff.change_category = ChangeCategory.SPINDLE
                line_diff.severity = ChangeSeverity.HIGH
            elif any(m in ['M07', 'M08', 'M09', 'M7', 'M8', 'M9'] for m in all_m):
                line_diff.change_category = ChangeCategory.COOLANT
                line_diff.severity = ChangeSeverity.MEDIUM
            elif any(m in ['M00', 'M01', 'M02', 'M30', 'M0', 'M1', 'M2'] for m in all_m):
                line_diff.change_category = ChangeCategory.PROGRAM_CONTROL
                line_diff.severity = ChangeSeverity.MEDIUM
            else:
                line_diff.change_category = ChangeCategory.UNKNOWN
                line_diff.severity = ChangeSeverity.MEDIUM
        elif cmd_diff.feed_change:
            line_diff.change_category = ChangeCategory.FEED_SPEED
            line_diff.severity = ChangeSeverity.HIGH
        elif cmd_diff.speed_change:
            line_diff.change_category = ChangeCategory.FEED_SPEED
            line_diff.severity = ChangeSeverity.HIGH
        else:
            # Check if it's just a comment change
            if line_diff.content_old and line_diff.content_new:
                old_stripped = line_diff.content_old.strip()
                new_stripped = line_diff.content_new.strip()
                if old_stripped.startswith('(') or old_stripped.startswith(';'):
                    line_diff.change_category = ChangeCategory.COMMENT
                    line_diff.severity = ChangeSeverity.INFO
                else:
                    line_diff.change_category = ChangeCategory.FORMATTING
                    line_diff.severity = ChangeSeverity.LOW
            else:
                line_diff.change_category = ChangeCategory.UNKNOWN
                line_diff.severity = ChangeSeverity.MEDIUM

    def _compute_operation_diffs(
        self,
        baseline: NCProgram,
        new: NCProgram,
        command_diffs: List[CommandDiff],
    ) -> List[OperationDiff]:
        """Compute operation-level differences."""
        operation_diffs: List[OperationDiff] = []

        baseline_ops = list(baseline.operations)
        new_ops = list(new.operations)

        # Track which new operations have been matched
        matched_new_indices: set = set()

        for old_op in baseline_ops:
            matched = False
            for ni, new_op in enumerate(new_ops):
                if ni in matched_new_indices:
                    continue

                # Match by operation name first, then by tool number
                name_match = (old_op.operation_name and new_op.operation_name and
                              old_op.operation_name == new_op.operation_name)
                tool_match = (old_op.tool and new_op.tool and
                              old_op.tool.tool_number == new_op.tool.tool_number)
                if name_match or tool_match:
                    matched = True
                    matched_new_indices.add(ni)

                    # Get command diffs for this operation
                    op_cmd_diffs = [
                        cd for cd in command_diffs
                        if (cd.line_diff.line_number_old and
                            old_op.start_line <= cd.line_diff.line_number_old <= old_op.end_line) or
                           (cd.line_diff.line_number_new and
                            new_op.start_line <= cd.line_diff.line_number_new <= new_op.end_line)
                    ]

                    if op_cmd_diffs:
                        operation_diffs.append(OperationDiff(
                            operation_id=old_op.operation_id,
                            operation_name_old=old_op.operation_name,
                            operation_name_new=new_op.operation_name,
                            change_type=ChangeType.MODIFIED,
                            tool_old=old_op.tool.tool_number if old_op.tool else None,
                            tool_new=new_op.tool.tool_number if new_op.tool else None,
                            start_line_old=old_op.start_line,
                            end_line_old=old_op.end_line,
                            start_line_new=new_op.start_line,
                            end_line_new=new_op.end_line,
                            command_diffs=op_cmd_diffs,
                            lines_added=sum(1 for cd in op_cmd_diffs if cd.line_diff.change_type == ChangeType.ADDED),
                            lines_removed=sum(1 for cd in op_cmd_diffs if cd.line_diff.change_type == ChangeType.REMOVED),
                            lines_modified=sum(1 for cd in op_cmd_diffs if cd.line_diff.change_type == ChangeType.MODIFIED),
                            critical_changes=sum(1 for cd in op_cmd_diffs if cd.is_critical),
                            raw_lines_old=[_strip_n_number(cmd.raw_text).rstrip() for cmd in old_op.commands],
                            raw_lines_new=[_strip_n_number(cmd.raw_text).rstrip() for cmd in new_op.commands],
                        ))
                    break

            if not matched:
                # Operation was removed
                operation_diffs.append(OperationDiff(
                    operation_id=old_op.operation_id,
                    operation_name_old=old_op.operation_name,
                    change_type=ChangeType.REMOVED,
                    tool_old=old_op.tool.tool_number if old_op.tool else None,
                    start_line_old=old_op.start_line,
                    end_line_old=old_op.end_line,
                    lines_removed=old_op.end_line - old_op.start_line + 1,
                    raw_lines_old=[_strip_n_number(cmd.raw_text).rstrip() for cmd in old_op.commands],
                ))

        # Check for added operations
        for ni, new_op in enumerate(new_ops):
            if ni not in matched_new_indices:
                operation_diffs.append(OperationDiff(
                    operation_id=new_op.operation_id,
                    operation_name_new=new_op.operation_name,
                    change_type=ChangeType.ADDED,
                    tool_new=new_op.tool.tool_number if new_op.tool else None,
                    start_line_new=new_op.start_line,
                    end_line_new=new_op.end_line,
                    lines_added=new_op.end_line - new_op.start_line + 1,
                    raw_lines_new=[_strip_n_number(cmd.raw_text).rstrip() for cmd in new_op.commands],
                ))

        return operation_diffs

    def _compute_summary(
        self,
        baseline: NCProgram,
        new: NCProgram,
        line_diffs: List[LineDiff],
        command_diffs: List[CommandDiff],
        operation_diffs: List[OperationDiff],
    ) -> ComparisonSummary:
        """Compute summary statistics."""
        # Count line changes
        lines_added = sum(1 for d in line_diffs if d.change_type == ChangeType.ADDED)
        lines_removed = sum(1 for d in line_diffs if d.change_type == ChangeType.REMOVED)
        lines_modified = sum(1 for d in line_diffs if d.change_type == ChangeType.MODIFIED)
        lines_unchanged = sum(1 for d in line_diffs if d.change_type == ChangeType.UNCHANGED)

        # Count operation changes
        ops_added = sum(1 for d in operation_diffs if d.change_type == ChangeType.ADDED)
        ops_removed = sum(1 for d in operation_diffs if d.change_type == ChangeType.REMOVED)
        ops_modified = sum(1 for d in operation_diffs if d.change_type == ChangeType.MODIFIED)

        # Count by severity
        severity_counts = {s: 0 for s in ChangeSeverity}
        category_counts: Dict[str, int] = {}
        
        for diff in line_diffs:
            if diff.change_type != ChangeType.UNCHANGED:
                severity_counts[diff.severity] = severity_counts.get(diff.severity, 0) + 1
                cat = diff.change_category.value
                category_counts[cat] = category_counts.get(cat, 0) + 1

        return ComparisonSummary(
            total_lines_old=baseline.total_lines,
            total_lines_new=new.total_lines,
            total_operations_old=baseline.total_operations,
            total_operations_new=new.total_operations,
            lines_added=lines_added,
            lines_removed=lines_removed,
            lines_modified=lines_modified,
            lines_unchanged=lines_unchanged,
            operations_added=ops_added,
            operations_removed=ops_removed,
            operations_modified=ops_modified,
            critical_changes=severity_counts.get(ChangeSeverity.CRITICAL, 0),
            high_changes=severity_counts.get(ChangeSeverity.HIGH, 0),
            medium_changes=severity_counts.get(ChangeSeverity.MEDIUM, 0),
            low_changes=severity_counts.get(ChangeSeverity.LOW, 0),
            info_changes=severity_counts.get(ChangeSeverity.INFO, 0),
            changes_by_category=category_counts,
        )

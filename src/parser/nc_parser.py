"""
NC Code Analyser - NC Code Parser
"""

import re
import hashlib
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from datetime import datetime
import time

from src.parser.models import (
    NCCommand, NCProgram, Operation, ToolInfo, Coordinate,
    ParseResult, MachineType, UnitSystem
)
from src.parser.gcode_definitions import get_gcode_info, get_mcode_info
from src.core import get_logger
from src.op_seperation.op_seperator import main as separate_operations, clean_line as op_clean_line, clean_operation as op_clean_operation

logger = get_logger(__name__)


class NCParser:
    """Parser for NC (G-code) files."""

    # Regex patterns for parsing
    # Note: Patterns handle various number formats: 10, 10.5, 10., .5, -10.5, etc.
    PATTERNS = {
        'block_number': re.compile(r'N(\d+)', re.IGNORECASE),
        'g_code': re.compile(r'G(\d+\.?\d*)', re.IGNORECASE),
        'm_code': re.compile(r'M(\d+)', re.IGNORECASE),
        'x_coord': re.compile(r'X([+-]?\d*\.?\d*)', re.IGNORECASE),
        'y_coord': re.compile(r'Y([+-]?\d*\.?\d*)', re.IGNORECASE),
        'z_coord': re.compile(r'Z([+-]?\d*\.?\d*)', re.IGNORECASE),
        'a_coord': re.compile(r'A([+-]?\d*\.?\d*)', re.IGNORECASE),
        'b_coord': re.compile(r'B([+-]?\d*\.?\d*)', re.IGNORECASE),
        'c_coord': re.compile(r'C([+-]?\d*\.?\d*)', re.IGNORECASE),
        'i_offset': re.compile(r'I([+-]?\d*\.?\d*)', re.IGNORECASE),
        'j_offset': re.compile(r'J([+-]?\d*\.?\d*)', re.IGNORECASE),
        'k_offset': re.compile(r'K([+-]?\d*\.?\d*)', re.IGNORECASE),
        'r_value': re.compile(r'R([+-]?\d*\.?\d*)', re.IGNORECASE),
        'feed_rate': re.compile(r'F(\d*\.?\d*)', re.IGNORECASE),
        'spindle_speed': re.compile(r'S(\d*\.?\d*)', re.IGNORECASE),
        'tool_number': re.compile(r'T(\d+)', re.IGNORECASE),
        'tool_offset_h': re.compile(r'H(\d+)', re.IGNORECASE),
        'tool_offset_d': re.compile(r'D(\d+)', re.IGNORECASE),
        'program_number': re.compile(r'^[O%](\d+)', re.IGNORECASE),
        'comment_paren': re.compile(r'\(([^)]*)\)'),
        'comment_semicolon': re.compile(r';(.*)$'),
        'operation_comment': re.compile(r'\(\s*(OPERATION|OP|TOOL\s*PATH|TOOLPATH)[:\s]*([^)]*)\)', re.IGNORECASE),
        'tool_comment': re.compile(r'\(\s*TOOL[:\s#]*(\d+)[:\s-]*([^)]*)\)', re.IGNORECASE),
    }

    def __init__(self):
        """Initialize the parser."""
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def parse_file(self, file_path: str) -> ParseResult:
        """Parse an NC file and return structured data."""
        start_time = time.time()
        self.errors = []
        self.warnings = []

        try:
            path = Path(file_path)
            if not path.exists():
                return ParseResult(
                    success=False,
                    errors=[f"File not found: {file_path}"]
                )

            # Read file content
            content = path.read_text(encoding='utf-8', errors='replace')
            file_hash = hashlib.sha256(content.encode()).hexdigest()

            # Parse the content
            program = self._parse_content(content, file_path, path.name, file_hash)

            parse_time = (time.time() - start_time) * 1000

            return ParseResult(
                success=True,
                program=program,
                errors=self.errors,
                warnings=self.warnings,
                parse_time_ms=parse_time
            )

        except Exception as e:
            logger.error("Failed to parse NC file", file=file_path, error=str(e))
            return ParseResult(
                success=False,
                errors=[f"Parse error: {str(e)}"]
            )

    def parse_content(self, content: str, file_name: str = "unnamed.nc") -> ParseResult:
        """Parse NC content from a string."""
        start_time = time.time()
        self.errors = []
        self.warnings = []

        try:
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            program = self._parse_content(content, "", file_name, file_hash)
            parse_time = (time.time() - start_time) * 1000

            return ParseResult(
                success=True,
                program=program,
                errors=self.errors,
                warnings=self.warnings,
                parse_time_ms=parse_time
            )

        except Exception as e:
            logger.error("Failed to parse NC content", error=str(e))
            return ParseResult(
                success=False,
                errors=[f"Parse error: {str(e)}"]
            )

    def _parse_content(
        self, 
        content: str, 
        file_path: str, 
        file_name: str, 
        file_hash: str
    ) -> NCProgram:
        """Internal method to parse NC content."""
        lines = content.splitlines()
        all_commands: List[NCCommand] = []
        header_comments: List[str] = []
        footer_comments: List[str] = []
        program_number: Optional[str] = None
        program_name: Optional[str] = None
        unit_system: Optional[UnitSystem] = None
        machine_type: Optional[MachineType] = None

        # First pass: parse all lines
        in_header = True
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if not stripped:
                continue

            # Check for program number at start
            if program_number is None:
                prog_match = self.PATTERNS['program_number'].match(stripped)
                if prog_match:
                    program_number = prog_match.group(1)

            # Parse the command
            command = self._parse_line(line_num, line)
            all_commands.append(command)

            # Extract header comments
            if in_header and command.is_comment_only:
                header_comments.append(command.comment or stripped)
                # Try to extract program name from comments
                if program_name is None and command.comment:
                    name_match = re.search(r'PROGRAM[:\s]+(.+)', command.comment, re.IGNORECASE)
                    if name_match:
                        program_name = name_match.group(1).strip()
            else:
                in_header = False

            # Detect unit system
            if unit_system is None:
                if 'G20' in command.g_codes:
                    unit_system = UnitSystem.INCH
                elif 'G21' in command.g_codes:
                    unit_system = UnitSystem.METRIC

        # Detect machine type based on G-codes used
        machine_type = self._detect_machine_type(all_commands)

        # Ask the op_separator for named operation boundaries.
        # It returns {op_name: [lines]} in file order; we mirror its
        # detection logic to build a 0-based-line-index → op_name lookup.
        ops_dict = separate_operations(lines)
        line_to_op: Dict[int, str] = {}
        if ops_dict:
            op_names = set(ops_dict.keys())
            current_op_name: Optional[str] = None
            for idx, raw_line in enumerate(lines):
                cleaned = op_clean_line(raw_line)
                if cleaned.startswith('( '):
                    candidate = op_clean_operation(cleaned)
                    if candidate in op_names:
                        current_op_name = candidate
                        line_to_op[idx] = current_op_name
                        continue
                if current_op_name:
                    line_to_op[idx] = current_op_name

        # Second pass: group into operations
        operations = self._extract_operations(all_commands, line_to_op or None)

        # Extract unique tools
        tools_used = self._extract_tools(all_commands)

        return NCProgram(
            file_path=file_path,
            file_name=file_name,
            file_hash=file_hash,
            program_number=program_number,
            program_name=program_name,
            machine_type=machine_type,
            unit_system=unit_system,
            total_lines=len(lines),
            operations=operations,
            all_commands=all_commands,
            tools_used=tools_used,
            total_operations=len(operations),
            total_tools=len(tools_used),
            header_comments=header_comments,
            footer_comments=footer_comments,
        )

    def _parse_line(self, line_number: int, raw_text: str) -> NCCommand:
        """Parse a single line of NC code."""
        stripped = raw_text.strip()
        
        # Initialize command
        command = NCCommand(
            line_number=line_number,
            raw_text=raw_text,
        )

        # Check for comment-only lines
        if stripped.startswith('(') and stripped.endswith(')'):
            command.comment = stripped[1:-1]
            command.is_comment_only = True
            return command
        
        if stripped.startswith(';'):
            command.comment = stripped[1:].strip()
            command.is_comment_only = True
            return command

        # Remove inline comments for parsing, but preserve them
        work_text = stripped
        comment_match = self.PATTERNS['comment_paren'].search(work_text)
        if comment_match:
            command.comment = comment_match.group(1)
            work_text = self.PATTERNS['comment_paren'].sub('', work_text)
        
        semicolon_match = self.PATTERNS['comment_semicolon'].search(work_text)
        if semicolon_match:
            if command.comment:
                command.comment += " | " + semicolon_match.group(1)
            else:
                command.comment = semicolon_match.group(1)
            work_text = self.PATTERNS['comment_semicolon'].sub('', work_text)

        # Parse block number
        block_match = self.PATTERNS['block_number'].search(work_text)
        if block_match:
            command.block_number = int(block_match.group(1))

        # Parse G-codes
        g_matches = self.PATTERNS['g_code'].findall(work_text)
        command.g_codes = [f"G{g}" for g in g_matches]

        # Parse M-codes
        m_matches = self.PATTERNS['m_code'].findall(work_text)
        command.m_codes = [f"M{m}" for m in m_matches]

        # Parse coordinates
        coords = self._parse_coordinates(work_text)
        if any(v is not None for v in [coords.x, coords.y, coords.z, coords.a, coords.b, coords.c]):
            command.coordinates = coords

        # Parse feed rate
        feed_match = self.PATTERNS['feed_rate'].search(work_text)
        if feed_match:
            value_str = feed_match.group(1)
            if value_str and value_str not in ('', '.'):
                if value_str.endswith('.'):
                    value_str = value_str + '0'
                try:
                    command.feed_rate = float(value_str)
                except ValueError:
                    pass

        # Parse spindle speed
        speed_match = self.PATTERNS['spindle_speed'].search(work_text)
        if speed_match:
            value_str = speed_match.group(1)
            if value_str and value_str not in ('', '.'):
                if value_str.endswith('.'):
                    value_str = value_str + '0'
                try:
                    command.spindle_speed = float(value_str)
                except ValueError:
                    pass

        # Parse tool number
        tool_match = self.PATTERNS['tool_number'].search(work_text)
        if tool_match:
            command.tool_number = int(tool_match.group(1))

        # Parse tool offset
        offset_h = self.PATTERNS['tool_offset_h'].search(work_text)
        offset_d = self.PATTERNS['tool_offset_d'].search(work_text)
        if offset_h:
            command.tool_offset = int(offset_h.group(1))
        elif offset_d:
            command.tool_offset = int(offset_d.group(1))

        return command

    def _parse_coordinates(self, text: str) -> Coordinate:
        """Parse coordinate values from text."""
        coord = Coordinate()

        patterns = {
            'x': 'x_coord', 'y': 'y_coord', 'z': 'z_coord',
            'a': 'a_coord', 'b': 'b_coord', 'c': 'c_coord',
            'i': 'i_offset', 'j': 'j_offset', 'k': 'k_offset',
            'r': 'r_value'
        }

        for attr, pattern_name in patterns.items():
            match = self.PATTERNS[pattern_name].search(text)
            if match:
                value_str = match.group(1)
                if value_str and value_str not in ('', '.', '+', '-'):
                    # Handle numbers like "90." -> "90.0"
                    if value_str.endswith('.'):
                        value_str = value_str + '0'
                    try:
                        setattr(coord, attr, float(value_str))
                    except ValueError:
                        pass  # Skip invalid values

        return coord

    def _detect_machine_type(self, commands: List[NCCommand]) -> Optional[MachineType]:
        """Detect the type of machine based on G-codes used."""
        all_g_codes = set()
        has_y_axis = False
        has_rotary = False
        has_turning_codes = False

        for cmd in commands:
            all_g_codes.update(cmd.g_codes)
            if cmd.coordinates:
                if cmd.coordinates.y is not None:
                    has_y_axis = True
                if any([cmd.coordinates.a, cmd.coordinates.b, cmd.coordinates.c]):
                    has_rotary = True

        # Check for turning-specific codes
        turning_codes = {'G70', 'G71', 'G72', 'G73', 'G74', 'G75', 'G76'}
        if turning_codes.intersection(all_g_codes):
            has_turning_codes = True

        # Determine machine type
        if has_rotary:
            if has_turning_codes:
                return MachineType.MILL_TURN
            return MachineType.MULTIAXIS
        elif has_turning_codes:
            return MachineType.TURN
        elif has_y_axis:
            return MachineType.MILL
        
        return None

    def _extract_operations(
        self,
        commands: List[NCCommand],
        line_to_op: Optional[Dict[int, str]] = None,
    ) -> List[Operation]:
        """Group parsed commands into named operations.

        When *line_to_op* is provided (built from op_seperator.main output) it
        drives both operation boundaries and names.  If the separator returned
        nothing (empty dict → None), we fall back to tool-change boundaries
        with generic names.
        """
        operations: List[Operation] = []
        current_op: Optional[Operation] = None
        op_counter = 0

        if line_to_op:
            # ── Primary path: op_separator supplied names ──────────────────
            current_op_name: Optional[str] = None
            for cmd in commands:
                op_name = line_to_op.get(cmd.line_number - 1)  # 0-based index

                if op_name and op_name != current_op_name:
                    # Boundary: start of a new named operation
                    if current_op:
                        operations.append(current_op)
                    op_counter += 1
                    current_op_name = op_name
                    current_op = Operation(
                        operation_id=f"OP_{op_counter:03d}",
                        operation_name=current_op_name,
                        start_line=cmd.line_number,
                        end_line=cmd.line_number,
                        tool=ToolInfo(tool_number=cmd.tool_number) if cmd.tool_number else None,
                    )

                if current_op:
                    current_op.commands.append(cmd)
                    current_op.end_line = cmd.line_number
                    if cmd.tool_number and not current_op.tool:
                        current_op.tool = ToolInfo(tool_number=cmd.tool_number)

        else:
            # ── Fallback path: tool-change boundaries, generic names ───────
            for cmd in commands:
                if cmd.tool_number is not None or 'M06' in cmd.m_codes or 'M6' in cmd.m_codes:
                    if current_op:
                        operations.append(current_op)
                    op_counter += 1
                    current_op = Operation(
                        operation_id=f"OP_{op_counter:03d}",
                        operation_name=f"Tool {cmd.tool_number}" if cmd.tool_number else "Tool Change",
                        start_line=cmd.line_number,
                        end_line=cmd.line_number,
                        tool=ToolInfo(tool_number=cmd.tool_number or 0) if cmd.tool_number else None,
                    )

                if current_op:
                    current_op.commands.append(cmd)
                    current_op.end_line = cmd.line_number

        if current_op:
            operations.append(current_op)

        # If no operations were found, create a default one
        if not operations and commands:
            operations.append(Operation(
                operation_id="OP_001",
                operation_name="Main Program",
                start_line=commands[0].line_number,
                end_line=commands[-1].line_number,
                commands=commands,
            ))

        return operations

    def _extract_tools(self, commands: List[NCCommand]) -> List[ToolInfo]:
        """Extract unique tools from commands."""
        tools: dict[int, ToolInfo] = {}

        for cmd in commands:
            if cmd.tool_number is not None and cmd.tool_number not in tools:
                tool_info = ToolInfo(
                    tool_number=cmd.tool_number,
                    offset_number=cmd.tool_offset,
                )
                
                # Try to extract tool name from comment
                if cmd.comment:
                    tool_match = self.PATTERNS['tool_comment'].search(f"({cmd.comment})")
                    if tool_match:
                        tool_info.tool_name = tool_match.group(2).strip()

                tools[cmd.tool_number] = tool_info

        return list(tools.values())

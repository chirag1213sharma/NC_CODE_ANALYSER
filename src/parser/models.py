"""
NC Code Analyser - Data Models for NC Code
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class MachineType(str, Enum):
    """Types of CNC machines."""
    MILL = "mill"
    TURN = "turn"
    MILL_TURN = "mill_turn"
    MULTIAXIS = "multiaxis"


class MotionType(str, Enum):
    """Types of motion commands."""
    RAPID = "rapid"           # G00
    LINEAR = "linear"         # G01
    CW_ARC = "cw_arc"         # G02
    CCW_ARC = "ccw_arc"       # G03
    DWELL = "dwell"           # G04


class CoordinateMode(str, Enum):
    """Coordinate positioning modes."""
    ABSOLUTE = "absolute"     # G90
    INCREMENTAL = "incremental"  # G91


class PlaneSelect(str, Enum):
    """Work plane selection."""
    XY = "xy"  # G17
    XZ = "xz"  # G18
    YZ = "yz"  # G19


class UnitSystem(str, Enum):
    """Unit system."""
    INCH = "inch"     # G20
    METRIC = "metric"  # G21


class Coordinate(BaseModel):
    """3D coordinate with optional rotary axes."""
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    a: Optional[float] = None  # Rotary axis
    b: Optional[float] = None  # Rotary axis
    c: Optional[float] = None  # Rotary axis
    i: Optional[float] = None  # Arc center offset
    j: Optional[float] = None  # Arc center offset
    k: Optional[float] = None  # Arc center offset
    r: Optional[float] = None  # Arc radius


class ToolInfo(BaseModel):
    """Tool information."""
    tool_number: int
    tool_name: Optional[str] = None
    tool_type: Optional[str] = None
    diameter: Optional[float] = None
    length: Optional[float] = None
    offset_number: Optional[int] = None


class SpindleState(BaseModel):
    """Spindle state information."""
    speed: Optional[float] = None  # S value (RPM)
    direction: Optional[str] = None  # CW (M03), CCW (M04), OFF (M05)
    css_mode: bool = False  # Constant surface speed


class CoolantState(BaseModel):
    """Coolant state information."""
    flood: bool = False   # M08
    mist: bool = False    # M07
    through_tool: bool = False


class NCCommand(BaseModel):
    """A single NC command/block."""
    line_number: int
    raw_text: str
    block_number: Optional[int] = None  # N number
    g_codes: List[str] = Field(default_factory=list)
    m_codes: List[str] = Field(default_factory=list)
    coordinates: Optional[Coordinate] = None
    feed_rate: Optional[float] = None  # F value
    spindle_speed: Optional[float] = None  # S value
    tool_number: Optional[int] = None  # T value
    tool_offset: Optional[int] = None  # H or D value
    comment: Optional[str] = None
    is_comment_only: bool = False


class Operation(BaseModel):
    """A machining operation (group of related commands)."""
    operation_id: str
    operation_name: str
    operation_type: Optional[str] = None  # e.g., "Rough Mill", "Finish Turn"
    tool: Optional[ToolInfo] = None
    start_line: int
    end_line: int
    commands: List[NCCommand] = Field(default_factory=list)
    
    # Computed properties
    total_distance: Optional[float] = None
    estimated_time: Optional[float] = None
    min_coordinates: Optional[Coordinate] = None
    max_coordinates: Optional[Coordinate] = None


class NCProgram(BaseModel):
    """Complete parsed NC program."""
    file_path: str
    file_name: str
    file_hash: str
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Program metadata
    program_number: Optional[str] = None
    program_name: Optional[str] = None
    machine_type: Optional[MachineType] = None
    unit_system: Optional[UnitSystem] = None
    
    # Content
    total_lines: int
    operations: List[Operation] = Field(default_factory=list)
    all_commands: List[NCCommand] = Field(default_factory=list)
    tools_used: List[ToolInfo] = Field(default_factory=list)
    
    # Statistics
    total_operations: int = 0
    total_tools: int = 0
    has_subprograms: bool = False
    
    # Raw content for reference
    header_comments: List[str] = Field(default_factory=list)
    footer_comments: List[str] = Field(default_factory=list)


class ParseResult(BaseModel):
    """Result of parsing an NC file."""
    success: bool
    program: Optional[NCProgram] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    parse_time_ms: float = 0

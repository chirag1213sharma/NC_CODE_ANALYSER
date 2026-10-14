"""
NC Code Analyser - Diff Engine Models
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class ChangeType(str, Enum):
    """Types of changes detected."""
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    MOVED = "moved"
    UNCHANGED = "unchanged"


class ChangeSeverity(str, Enum):
    """Severity level of a change."""
    CRITICAL = "critical"     # Affects machine motion or safety
    HIGH = "high"             # Affects machining quality
    MEDIUM = "medium"         # Affects performance
    LOW = "low"               # Minor changes
    INFO = "info"             # Cosmetic/comment changes


class ChangeCategory(str, Enum):
    """Categories of changes for classification."""
    COORDINATE = "coordinate"        # X, Y, Z position changes
    FEED_SPEED = "feed_speed"        # Feed rate or spindle speed
    TOOL = "tool"                    # Tool selection or offset
    MOTION = "motion"                # G-code motion type
    COOLANT = "coolant"              # Coolant control
    SPINDLE = "spindle"              # Spindle control
    OPERATION = "operation"          # Operation added/removed
    COMMENT = "comment"              # Comment changes only
    FORMATTING = "formatting"        # Whitespace, line numbers
    PROGRAM_CONTROL = "program_control"  # M00, M30, etc.
    CANNED_CYCLE = "canned_cycle"    # G81, G82, etc.
    WORK_OFFSET = "work_offset"      # G54, G55, etc.
    UNKNOWN = "unknown"


class ClassificationResult(str, Enum):
    """AI classification of change impact."""
    REGRESSION = "regression"      # Undesired change - potential bug
    PROGRESSION = "progression"    # Expected improvement
    NEUTRAL = "neutral"            # No functional impact
    UNCERTAIN = "uncertain"        # Needs human review


class LineDiff(BaseModel):
    """Difference at the line level."""
    line_number_old: Optional[int] = None
    line_number_new: Optional[int] = None
    content_old: Optional[str] = None
    content_new: Optional[str] = None
    change_type: ChangeType
    change_category: ChangeCategory = ChangeCategory.UNKNOWN
    severity: ChangeSeverity = ChangeSeverity.INFO


class CommandDiff(BaseModel):
    """Difference at the command level with parsed details."""
    line_diff: LineDiff
    
    # Parsed differences
    g_codes_added: List[str] = Field(default_factory=list)
    g_codes_removed: List[str] = Field(default_factory=list)
    m_codes_added: List[str] = Field(default_factory=list)
    m_codes_removed: List[str] = Field(default_factory=list)
    
    # Coordinate changes
    coordinate_changes: Dict[str, tuple] = Field(default_factory=dict)  # axis: (old, new)
    
    # Value changes
    feed_change: Optional[tuple] = None  # (old, new)
    speed_change: Optional[tuple] = None  # (old, new)
    tool_change: Optional[tuple] = None  # (old, new)
    
    # Analysis
    is_critical: bool = False
    change_description: str = ""


class OperationDiff(BaseModel):
    """Difference at the operation level."""
    operation_id: str
    operation_name_old: Optional[str] = None
    operation_name_new: Optional[str] = None
    change_type: ChangeType
    
    # Tool comparison
    tool_old: Optional[int] = None
    tool_new: Optional[int] = None
    
    # Line ranges
    start_line_old: Optional[int] = None
    end_line_old: Optional[int] = None
    start_line_new: Optional[int] = None
    end_line_new: Optional[int] = None
    
    # Command-level diffs
    command_diffs: List[CommandDiff] = Field(default_factory=list)
    
    # Summary statistics
    lines_added: int = 0
    lines_removed: int = 0
    lines_modified: int = 0
    critical_changes: int = 0
    
    # Raw operation G-code lines for side-by-side display
    raw_lines_old: List[str] = Field(default_factory=list)
    raw_lines_new: List[str] = Field(default_factory=list)


class ComparisonSummary(BaseModel):
    """Summary statistics of the comparison."""
    total_lines_old: int
    total_lines_new: int
    total_operations_old: int
    total_operations_new: int
    
    # Change counts
    lines_added: int = 0
    lines_removed: int = 0
    lines_modified: int = 0
    lines_unchanged: int = 0
    
    operations_added: int = 0
    operations_removed: int = 0
    operations_modified: int = 0
    
    # Severity breakdown
    critical_changes: int = 0
    high_changes: int = 0
    medium_changes: int = 0
    low_changes: int = 0
    info_changes: int = 0
    
    # Category breakdown
    changes_by_category: Dict[str, int] = Field(default_factory=dict)


class DiffResult(BaseModel):
    """Complete result of comparing two NC files."""
    # File information
    baseline_file: str
    baseline_hash: str
    new_file: str
    new_hash: str
    compared_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Are files identical?
    files_identical: bool = False
    
    # Differences
    line_diffs: List[LineDiff] = Field(default_factory=list)
    command_diffs: List[CommandDiff] = Field(default_factory=list)
    operation_diffs: List[OperationDiff] = Field(default_factory=list)
    
    # Summary
    summary: Optional[ComparisonSummary] = None
    
    # AI Classification (filled by AI module)
    classification: Optional[ClassificationResult] = None
    classification_confidence: Optional[float] = None
    classification_reasoning: Optional[str] = None
    
    # Raw line content keyed by 1-based source line number, used by the AI
    # prompt builder to attach ±N lines of context around each changed line.
    # Not persisted; populated only during in-memory comparison.
    baseline_lines_by_number: Dict[int, str] = Field(default_factory=dict)
    new_lines_by_number: Dict[int, str] = Field(default_factory=dict)
    
    # Processing info
    comparison_time_ms: float = 0


class AnalysisRequest(BaseModel):
    """Request to analyze NC file differences."""
    baseline_file_path: Optional[str] = None
    baseline_content: Optional[str] = None
    new_file_path: Optional[str] = None
    new_content: Optional[str] = None
    include_ai_classification: bool = True
    machine_type: Optional[str] = None


class AnalysisResult(BaseModel):
    """Complete analysis result including AI classification."""
    analysis_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Input files
    baseline_file: str
    new_file: str
    
    # Diff result
    diff_result: DiffResult
    
    # AI Analysis
    classification: ClassificationResult
    confidence: float
    reasoning: str
    recommendations: List[str] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    
    # QA Feedback (if provided)
    qa_reviewed: bool = False
    qa_classification: Optional[ClassificationResult] = None
    qa_notes: Optional[str] = None
    qa_reviewer: Optional[str] = None
    qa_reviewed_at: Optional[datetime] = None

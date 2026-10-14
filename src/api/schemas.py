"""
NC Code Analyser - API Request/Response Models
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class FileUploadResponse(BaseModel):
    """Response after file upload."""
    file_id: str
    file_name: str
    file_path: str
    file_hash: str
    uploaded_at: datetime
    file_size: int


class CompareRequest(BaseModel):
    """Request to compare two NC files."""
    baseline_file_id: Optional[str] = None
    baseline_content: Optional[str] = None
    new_file_id: Optional[str] = None
    new_content: Optional[str] = None
    include_ai_classification: bool = True


class CompareResponse(BaseModel):
    """Response from comparison."""
    analysis_id: str
    baseline_file: str
    new_file: str
    files_identical: bool
    
    # Summary
    lines_added: int
    lines_removed: int
    lines_modified: int
    critical_changes: int
    
    # AI Classification
    classification: str
    confidence: float
    reasoning: str
    recommendations: List[str]
    key_findings: List[str] = []
    operations_with_changes: int = 0
    operation_diffs: List[Dict[str, Any]] = []
    
    # Timing
    comparison_time_ms: float
    created_at: datetime


class FeedbackRequest(BaseModel):
    """Request to submit QA feedback."""
    analysis_id: str
    classification: str  # REGRESSION, PROGRESSION, NEUTRAL
    notes: str
    reviewer: str


class FeedbackResponse(BaseModel):
    """Response after feedback submission."""
    feedback_id: str
    analysis_id: str
    accepted: bool
    message: str


class FeedbackStats(BaseModel):
    """Feedback statistics."""
    total_feedback: int
    corrections: int
    correction_rate: float
    by_classification: Dict[str, int]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    ai_available: bool
    database_connected: bool
    feedback_count: int


class OperationSummary(BaseModel):
    """Summary of an operation."""
    operation_id: str
    operation_name: str
    tool_number: Optional[int]
    start_line: int
    end_line: int
    command_count: int


class ParseResponse(BaseModel):
    """Response from parsing an NC file."""
    file_name: str
    program_number: Optional[str]
    program_name: Optional[str]
    machine_type: Optional[str]
    unit_system: Optional[str]
    total_lines: int
    total_operations: int
    total_tools: int
    operations: List[OperationSummary]
    tools: List[Dict[str, Any]]
    parse_time_ms: float


class DiffDetailResponse(BaseModel):
    """Detailed diff response."""
    analysis_id: str
    baseline_file: str
    new_file: str
    files_identical: bool
    
    # Full diff details
    line_diffs: List[Dict[str, Any]]
    command_diffs: List[Dict[str, Any]]
    operation_diffs: List[Dict[str, Any]]
    summary: Dict[str, Any]
    
    # Classification
    classification: str
    confidence: float
    reasoning: str
    recommendations: List[str]
    
    # QA Review status
    qa_reviewed: bool
    qa_classification: Optional[str]
    qa_notes: Optional[str]
    qa_reviewer: Optional[str]


class ReportFormat(str, Enum):
    """Available report formats."""
    HTML = "html"
    PDF = "pdf"
    JSON = "json"


class ReportRequest(BaseModel):
    """Request to generate a report."""
    analysis_id: str
    format: ReportFormat = ReportFormat.HTML
    include_details: bool = True


# --- Folder Comparison Schemas ---

class FolderCompareRequest(BaseModel):
    """Request to compare two folders of NC files.

    To minimise network I/O the client may pre-classify files by name + hash
    and only upload content for files that actually need diff analysis. The
    ``pre_classified_*`` lists tell the server which files are already known
    to be missing, new, or identical so it can record them in the response
    without needing their content.
    """
    baseline_files: Dict[str, str]  # filename -> content (only files needing diff)
    result_files: Dict[str, str]    # filename -> content (only files needing diff)
    include_ai_classification: bool = True
    # Optional client-side pre-classification (saves uploading unchanged/missing files).
    pre_classified_missing: List[str] = []     # baseline-only, never had a result
    pre_classified_new: List[str] = []         # result-only, no baseline counterpart
    pre_classified_unchanged: List[str] = []   # name-matched and hash-equal on client


class FileCompareResult(BaseModel):
    """Result of comparing a single file pair in folder comparison."""
    file_name: str
    status: str  # "no_change", "regression", "progression", "neutral", "missing_in_result", "new_in_result"
    analysis_id: Optional[str] = None
    files_identical: bool = True
    lines_added: int = 0
    lines_removed: int = 0
    lines_modified: int = 0
    critical_changes: int = 0
    classification: Optional[str] = None
    confidence: float = 0.0
    reasoning: str = ""
    recommendations: List[str] = []
    key_findings: List[str] = []
    operations_with_changes: int = 0
    operation_diffs: List[Dict[str, Any]] = []
    comparison_time_ms: float = 0.0


class FolderDashboard(BaseModel):
    """Numeric dashboard for folder comparison."""
    total_files: int = 0
    files_with_diffs: int = 0
    no_changes: int = 0
    regressions: int = 0
    progressions: int = 0
    neutral: int = 0
    result_file_missing: int = 0
    new_in_result: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0
    total_lines_modified: int = 0
    total_critical_changes: int = 0


class FolderCompareResponse(BaseModel):
    """Response from folder comparison."""
    folder_analysis_id: str
    dashboard: FolderDashboard
    file_results: List[FileCompareResult]
    created_at: datetime


class FolderFeedbackRequest(BaseModel):
    """Request to submit feedback for a specific file in folder comparison."""
    folder_analysis_id: str
    file_name: str
    classification: str  # REGRESSION, PROGRESSION, NEUTRAL
    notes: str
    reviewer: str

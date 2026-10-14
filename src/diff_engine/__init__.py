"""
NC Code Analyser - Diff Engine Module
"""

from src.diff_engine.diff_engine import DiffEngine
from src.diff_engine.models import (
    DiffResult, LineDiff, CommandDiff, OperationDiff,
    ComparisonSummary, ChangeType, ChangeSeverity, ChangeCategory,
    ClassificationResult, AnalysisRequest, AnalysisResult
)

__all__ = [
    "DiffEngine",
    "DiffResult",
    "LineDiff",
    "CommandDiff",
    "OperationDiff",
    "ComparisonSummary",
    "ChangeType",
    "ChangeSeverity",
    "ChangeCategory",
    "ClassificationResult",
    "AnalysisRequest",
    "AnalysisResult",
]

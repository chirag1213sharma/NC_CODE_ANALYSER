"""
NC Code Analyser - Comparison Routes
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Body

from src.core import get_logger
from src.api.schemas import CompareRequest, CompareResponse, DiffDetailResponse
from src.api.routes.files import file_registry
from src.api.routes.analysis_store import persist_analysis
from src.diff_engine import DiffEngine
from src.ai import GeminiClassifier

router = APIRouter(prefix="/compare", tags=["Comparison"])
logger = get_logger(__name__)

# Initialize components
diff_engine = DiffEngine()
ai_classifier = GeminiClassifier()

# In-memory analysis storage (in production, use database)
analysis_registry: dict = {}


@router.post("", response_model=CompareResponse)
async def compare_files(request: CompareRequest):
    """Compare baseline and new NC files."""
    
    # Validate input
    if not request.baseline_file_id and not request.baseline_content:
        raise HTTPException(
            status_code=400,
            detail="Either baseline_file_id or baseline_content is required"
        )
    if not request.new_file_id and not request.new_content:
        raise HTTPException(
            status_code=400,
            detail="Either new_file_id or new_content is required"
        )

    # Get file paths or content
    baseline_path = None
    baseline_content = request.baseline_content
    new_path = None
    new_content = request.new_content

    if request.baseline_file_id:
        if request.baseline_file_id not in file_registry:
            raise HTTPException(status_code=404, detail="Baseline file not found")
        baseline_path = file_registry[request.baseline_file_id]["file_path"]

    if request.new_file_id:
        if request.new_file_id not in file_registry:
            raise HTTPException(status_code=404, detail="New file not found")
        new_path = file_registry[request.new_file_id]["file_path"]

    try:
        # Perform comparison
        if baseline_path and new_path:
            diff_result = diff_engine.compare_files(baseline_path, new_path)
        else:
            baseline_name = "baseline.nc"
            new_name = "new.nc"
            
            if baseline_path:
                import aiofiles
                async with aiofiles.open(baseline_path, 'r') as f:
                    baseline_content = await f.read()
                baseline_name = file_registry[request.baseline_file_id]["file_name"]
            
            if new_path:
                import aiofiles
                async with aiofiles.open(new_path, 'r') as f:
                    new_content = await f.read()
                new_name = file_registry[request.new_file_id]["file_name"]
            
            diff_result = diff_engine.compare_content(
                baseline_content, new_content, baseline_name, new_name
            )

        # AI Classification
        classification = "NEUTRAL"
        confidence = 0.0
        reasoning = "Files are identical"
        recommendations = []
        key_findings = []

        if not diff_result.files_identical and request.include_ai_classification:
            # Run AI classification (vector-DB RAG removed; feedback is now
            # captured to feedback.json for fine-tuning instead).
            analysis_result = await ai_classifier.classify_changes(
                diff_result, None
            )

            classification = analysis_result.classification.value
            confidence = analysis_result.confidence
            reasoning = analysis_result.reasoning
            recommendations = analysis_result.recommendations
            key_findings = analysis_result.key_findings

            # Store analysis (memory + disk so feedback survives restarts)
            analysis_registry[analysis_result.analysis_id] = {
                "analysis": analysis_result,
                "diff_result": diff_result,
                "created_at": datetime.utcnow(),
            }
            persist_analysis(analysis_result, diff_result)

            analysis_id = analysis_result.analysis_id
        else:
            analysis_id = str(uuid.uuid4())
            if diff_result.files_identical:
                classification = "NEUTRAL"
                confidence = 1.0
                reasoning = "Files are identical - no changes detected"
                recommendations = []
                key_findings = ["Files are identical - no changes detected"]

        # Build operation diffs summary for response
        op_diffs_summary = [
            {
                "operation_name": d.operation_name_old or d.operation_name_new or "Unknown",
                "change_type": d.change_type.value,
                "lines_modified": d.lines_modified,
                "lines_added": d.lines_added,
                "lines_removed": d.lines_removed,
                "critical_changes": d.critical_changes,
                "tool_old": d.tool_old,
                "tool_new": d.tool_new,
            }
            for d in diff_result.operation_diffs
        ]

        # Build response
        summary = diff_result.summary

        return CompareResponse(
            analysis_id=analysis_id,
            baseline_file=diff_result.baseline_file,
            new_file=diff_result.new_file,
            files_identical=diff_result.files_identical,
            lines_added=summary.lines_added if summary else 0,
            lines_removed=summary.lines_removed if summary else 0,
            lines_modified=summary.lines_modified if summary else 0,
            critical_changes=summary.critical_changes if summary else 0,
            classification=classification,
            confidence=confidence,
            reasoning=reasoning,
            recommendations=recommendations,
            key_findings=key_findings,
            operations_with_changes=len(op_diffs_summary),
            operation_diffs=op_diffs_summary,
            comparison_time_ms=diff_result.comparison_time_ms,
            created_at=datetime.utcnow(),
        )

    except Exception as e:
        logger.error("Comparison failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")


@router.get("/{analysis_id}", response_model=DiffDetailResponse)
async def get_analysis_details(analysis_id: str):
    """Get detailed analysis results."""
    if analysis_id not in analysis_registry:
        raise HTTPException(status_code=404, detail="Analysis not found")

    stored = analysis_registry[analysis_id]
    analysis = stored["analysis"]
    diff_result = stored["diff_result"]

    # Convert to response format
    line_diffs = [
        {
            "line_number_old": d.line_number_old,
            "line_number_new": d.line_number_new,
            "content_old": d.content_old,
            "content_new": d.content_new,
            "change_type": d.change_type.value,
            "category": d.change_category.value,
            "severity": d.severity.value,
        }
        for d in diff_result.line_diffs
        if d.change_type.value != "unchanged"
    ]

    command_diffs = [
        {
            "line_number": d.line_diff.line_number_old or d.line_diff.line_number_new,
            "change_type": d.line_diff.change_type.value,
            "description": d.change_description,
            "is_critical": d.is_critical,
            "g_codes_added": d.g_codes_added,
            "g_codes_removed": d.g_codes_removed,
            "m_codes_added": d.m_codes_added,
            "m_codes_removed": d.m_codes_removed,
            "coordinate_changes": d.coordinate_changes,
            "feed_change": d.feed_change,
            "speed_change": d.speed_change,
            "tool_change": d.tool_change,
        }
        for d in diff_result.command_diffs
    ]

    operation_diffs = [
        {
            "operation_id": d.operation_id,
            "operation_name_old": d.operation_name_old,
            "operation_name_new": d.operation_name_new,
            "change_type": d.change_type.value,
            "tool_old": d.tool_old,
            "tool_new": d.tool_new,
            "lines_added": d.lines_added,
            "lines_removed": d.lines_removed,
            "lines_modified": d.lines_modified,
            "critical_changes": d.critical_changes,
        }
        for d in diff_result.operation_diffs
    ]

    summary = {}
    if diff_result.summary:
        summary = {
            "total_lines_old": diff_result.summary.total_lines_old,
            "total_lines_new": diff_result.summary.total_lines_new,
            "lines_added": diff_result.summary.lines_added,
            "lines_removed": diff_result.summary.lines_removed,
            "lines_modified": diff_result.summary.lines_modified,
            "critical_changes": diff_result.summary.critical_changes,
            "high_changes": diff_result.summary.high_changes,
            "medium_changes": diff_result.summary.medium_changes,
            "low_changes": diff_result.summary.low_changes,
            "changes_by_category": diff_result.summary.changes_by_category,
        }

    return DiffDetailResponse(
        analysis_id=analysis_id,
        baseline_file=diff_result.baseline_file,
        new_file=diff_result.new_file,
        files_identical=diff_result.files_identical,
        line_diffs=line_diffs,
        command_diffs=command_diffs,
        operation_diffs=operation_diffs,
        summary=summary,
        classification=analysis.classification.value,
        confidence=analysis.confidence,
        reasoning=analysis.reasoning,
        recommendations=analysis.recommendations,
        qa_reviewed=analysis.qa_reviewed,
        qa_classification=analysis.qa_classification.value if analysis.qa_classification else None,
        qa_notes=analysis.qa_notes,
        qa_reviewer=analysis.qa_reviewer,
    )


@router.get("")
async def list_analyses(limit: int = 50):
    """List recent analyses."""
    analyses = []
    
    for analysis_id, stored in analysis_registry.items():
        analysis = stored["analysis"]
        analyses.append({
            "analysis_id": analysis_id,
            "baseline_file": analysis.baseline_file,
            "new_file": analysis.new_file,
            "classification": analysis.classification.value,
            "confidence": analysis.confidence,
            "qa_reviewed": analysis.qa_reviewed,
            "created_at": stored["created_at"].isoformat(),
        })

    # Sort by created_at (newest first)
    analyses.sort(key=lambda x: x["created_at"], reverse=True)

    return {"analyses": analyses[:limit], "total": len(analyses)}

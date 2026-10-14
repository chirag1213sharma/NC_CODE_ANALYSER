"""
NC Code Analyser - Folder Comparison Routes
"""

import asyncio
import hashlib
import os
import uuid
import difflib
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from src.core import get_logger
from src.api.schemas import (
    FolderCompareRequest, FolderCompareResponse, FolderDashboard,
    FileCompareResult, FolderFeedbackRequest, FeedbackResponse,
)
from src.diff_engine import DiffEngine
from src.ai import GeminiClassifier
from src.feedback import FeedbackStore

router = APIRouter(prefix="/folder-compare", tags=["Folder Comparison"])
logger = get_logger(__name__)

# Initialize components
diff_engine = DiffEngine()
ai_classifier = GeminiClassifier()
feedback_store = FeedbackStore()

# In-memory storage for folder analyses
folder_analysis_registry: dict = {}

# Concurrency tunables (overridable via env)
_DIFF_WORKERS = max(1, int(os.environ.get("NC_DIFF_WORKERS", os.cpu_count() or 4)))
_AI_CONCURRENCY = max(1, int(os.environ.get("NC_AI_CONCURRENCY", "4")))


def _content_hash(content: str) -> str:
    """Fast SHA-256 of file content, used to short-circuit identical files
    without invoking the (much heavier) parser + diff engine."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _diff_worker(args: Tuple[str, str, str]):
    """Run in a worker process: parse both contents and compute the diff.

    Returns ``(file_name, diff_result, error_message)`` where exactly one of
    ``diff_result`` / ``error_message`` is set. ``DiffResult`` is a Pydantic
    model, so it pickles cleanly back to the parent process.
    """
    file_name, baseline_content, result_content = args
    try:
        engine = DiffEngine()
        diff = engine.compare_content(
            baseline_content, result_content, file_name, file_name
        )
        return file_name, diff, None
    except Exception as exc:  # pragma: no cover - reported back to caller
        return file_name, None, str(exc)


@router.post("", response_model=FolderCompareResponse)
async def compare_folders(request: FolderCompareRequest):
    """Compare baseline and result folders, matching files by name."""

    folder_analysis_id = str(uuid.uuid4())
    file_results: list[FileCompareResult] = []

    # --- Phase 0: trust the client's name + hash triage ------------------
    # The browser walks the two folders, drops files that exist only on one
    # side, and hash-compares the remaining pairs. It then uploads content
    # only for files that actually differ. The lists below tell us about the
    # files the client *did not* upload so we can still report them in the
    # final dashboard without re-doing the work.
    results_by_name: dict[str, FileCompareResult] = {}

    for name in request.pre_classified_missing:
        results_by_name[name] = FileCompareResult(
            file_name=name,
            status="missing_in_result",
            files_identical=False,
            reasoning="Result file is missing - baseline file has no corresponding result.",
        )
    for name in request.pre_classified_new:
        results_by_name[name] = FileCompareResult(
            file_name=name,
            status="new_in_result",
            files_identical=False,
            reasoning="New file found in result folder with no baseline counterpart.",
        )
    for name in request.pre_classified_unchanged:
        results_by_name[name] = FileCompareResult(
            file_name=name,
            status="no_change",
            files_identical=True,
            reasoning="Files are identical (hash match on client) - no changes detected.",
        )

    all_baseline_names = set(request.baseline_files.keys())
    all_result_names = set(request.result_files.keys())

    # Total file count for the dashboard = pre-classified + uploaded pairs +
    # any orphans in the uploaded maps (defensive - shouldn't normally happen).
    all_names = sorted(
        set(results_by_name.keys())
        | all_baseline_names
        | all_result_names
    )

    # --- Phase 1: triage uploaded pairs (server-side safety net) ---------
    # The client should only upload changed pairs, but we still handle
    # missing/new/identical here so the API works for older clients or any
    # request that bypasses the client triage.
    pending_diffs: list[tuple[str, str, str]] = []  # (name, baseline, result)

    for file_name in all_baseline_names | all_result_names:
        if file_name in results_by_name:
            # Already classified by the client; don't second-guess it.
            continue

        has_baseline = file_name in request.baseline_files
        has_result = file_name in request.result_files

        if has_baseline and not has_result:
            results_by_name[file_name] = FileCompareResult(
                file_name=file_name,
                status="missing_in_result",
                files_identical=False,
                reasoning="Result file is missing - baseline file has no corresponding result.",
            )
            continue

        if not has_baseline and has_result:
            results_by_name[file_name] = FileCompareResult(
                file_name=file_name,
                status="new_in_result",
                files_identical=False,
                reasoning="New file found in result folder with no baseline counterpart.",
            )
            continue

        baseline_content = request.baseline_files[file_name]
        result_content = request.result_files[file_name]

        # Fast path: identical-by-hash files skip the parser + diff + AI.
        if _content_hash(baseline_content) == _content_hash(result_content):
            results_by_name[file_name] = FileCompareResult(
                file_name=file_name,
                status="no_change",
                files_identical=True,
                reasoning="Files are identical - no changes detected.",
            )
            continue

        pending_diffs.append((file_name, baseline_content, result_content))

    # --- Phase 2: parallel diffing (CPU-bound) ---------------------------
    # Run parser + diff engine for changed files concurrently across worker
    # processes. The number of workers defaults to os.cpu_count() but can be
    # tuned via the NC_DIFF_WORKERS env var.
    diff_by_name: dict[str, object] = {}
    if pending_diffs:
        loop = asyncio.get_running_loop()
        workers = min(_DIFF_WORKERS, len(pending_diffs))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            tasks = [
                loop.run_in_executor(pool, _diff_worker, args)
                for args in pending_diffs
            ]
            for file_name, diff_result, error in await asyncio.gather(*tasks):
                if error is not None:
                    logger.error(
                        "Comparison failed for file",
                        file_name=file_name,
                        error=error,
                    )
                    results_by_name[file_name] = FileCompareResult(
                        file_name=file_name,
                        status="neutral",
                        reasoning=f"Comparison error: {error}",
                    )
                else:
                    diff_by_name[file_name] = diff_result

    # Some diffs may report identical even though hashes differed (e.g. only
    # whitespace differences after normalization). Pull those out before AI.
    ai_targets: list[tuple[str, object]] = []
    for file_name, diff_result in diff_by_name.items():
        if diff_result.files_identical:
            results_by_name[file_name] = FileCompareResult(
                file_name=file_name,
                status="no_change",
                files_identical=True,
                reasoning="Files are identical after normalization - no functional changes.",
            )
        else:
            ai_targets.append((file_name, diff_result))

    # --- Phase 3: concurrent AI classification ---------------------------
    ai_semaphore = asyncio.Semaphore(_AI_CONCURRENCY)

    async def _classify(file_name: str, diff_result):
        if not request.include_ai_classification:
            return file_name, diff_result, None, None
        async with ai_semaphore:
            try:
                analysis_result = await ai_classifier.classify_changes(
                    diff_result, None
                )
                return file_name, diff_result, analysis_result, None
            except Exception as exc:
                logger.error(
                    "AI classification failed",
                    file_name=file_name,
                    error=str(exc),
                )
                return file_name, diff_result, None, str(exc)

    ai_results = await asyncio.gather(
        *[_classify(name, diff) for name, diff in ai_targets]
    )

    # Import here to avoid circulars at module-load time.
    from src.api.routes.compare import analysis_registry
    from src.api.routes.analysis_store import persist_analysis

    for file_name, diff_result, analysis_result, ai_error in ai_results:
        classification = "NEUTRAL"
        confidence = 0.0
        reasoning = ""
        recommendations: list = []
        key_findings: list = []
        analysis_id = str(uuid.uuid4())

        if analysis_result is not None:
            classification = analysis_result.classification.value.upper()
            confidence = analysis_result.confidence
            reasoning = analysis_result.reasoning
            recommendations = analysis_result.recommendations
            key_findings = analysis_result.key_findings
            analysis_id = analysis_result.analysis_id
            analysis_registry[analysis_id] = {
                "analysis": analysis_result,
                "diff_result": diff_result,
                "created_at": datetime.utcnow(),
            }
            persist_analysis(analysis_result, diff_result)
        elif ai_error is not None:
            reasoning = f"AI classification unavailable: {ai_error}"

        summary = diff_result.summary
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

        status = classification.lower()
        if status not in ("regression", "progression", "neutral"):
            status = "neutral"

        results_by_name[file_name] = FileCompareResult(
            file_name=file_name,
            status=status,
            analysis_id=analysis_id,
            files_identical=False,
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
        )

    # Preserve sorted (filename) order in the response.
    file_results = [results_by_name[name] for name in all_names if name in results_by_name]

    # Build dashboard
    dashboard = FolderDashboard(
        total_files=len(all_names),
        files_with_diffs=sum(1 for r in file_results if not r.files_identical and r.status not in ("missing_in_result", "new_in_result")),
        no_changes=sum(1 for r in file_results if r.status == "no_change"),
        regressions=sum(1 for r in file_results if r.status == "regression"),
        progressions=sum(1 for r in file_results if r.status == "progression"),
        neutral=sum(1 for r in file_results if r.status == "neutral"),
        result_file_missing=sum(1 for r in file_results if r.status == "missing_in_result"),
        new_in_result=sum(1 for r in file_results if r.status == "new_in_result"),
        total_lines_added=sum(r.lines_added for r in file_results),
        total_lines_removed=sum(r.lines_removed for r in file_results),
        total_lines_modified=sum(r.lines_modified for r in file_results),
        total_critical_changes=sum(r.critical_changes for r in file_results),
    )

    response = FolderCompareResponse(
        folder_analysis_id=folder_analysis_id,
        dashboard=dashboard,
        file_results=file_results,
        created_at=datetime.utcnow(),
    )

    # Store for later retrieval (reports, feedback)
    folder_analysis_registry[folder_analysis_id] = {
        "response": response,
        "created_at": datetime.utcnow(),
    }

    return response


@router.get("/{folder_analysis_id}")
async def get_folder_analysis(folder_analysis_id: str):
    """Get a previously computed folder analysis."""
    if folder_analysis_id not in folder_analysis_registry:
        raise HTTPException(status_code=404, detail="Folder analysis not found")

    return folder_analysis_registry[folder_analysis_id]["response"]


@router.post("/{folder_analysis_id}/feedback", response_model=FeedbackResponse)
async def submit_folder_feedback(folder_analysis_id: str, request: FolderFeedbackRequest):
    """Submit feedback for a specific file in a folder comparison."""
    if folder_analysis_id not in folder_analysis_registry:
        raise HTTPException(status_code=404, detail="Folder analysis not found")

    stored = folder_analysis_registry[folder_analysis_id]
    response: FolderCompareResponse = stored["response"]

    # Find the file result
    file_result = next((r for r in response.file_results if r.file_name == request.file_name), None)
    if not file_result:
        raise HTTPException(status_code=404, detail=f"File '{request.file_name}' not found in this analysis")

    if not file_result.analysis_id:
        raise HTTPException(status_code=400, detail="No analysis available for this file (no changes detected)")

    valid_classifications = {"REGRESSION", "PROGRESSION", "NEUTRAL"}
    if request.classification.upper() not in valid_classifications:
        raise HTTPException(status_code=400, detail=f"Invalid classification. Must be one of: {valid_classifications}")

    try:
        from src.api.routes.compare import analysis_registry
        from src.api.routes.analysis_store import load_analysis
        from src.diff_engine.models import ClassificationResult

        stored_analysis = analysis_registry.get(file_result.analysis_id)
        if stored_analysis is None:
            stored_analysis = load_analysis(file_result.analysis_id)
            if stored_analysis is not None:
                analysis_registry[file_result.analysis_id] = stored_analysis

        if stored_analysis is not None:
            analysis = stored_analysis["analysis"]
            qa_classification = ClassificationResult(request.classification.lower())
            feedback_id = feedback_store.add_feedback(
                analysis_result=analysis,
                qa_classification=qa_classification,
                qa_notes=request.notes,
                qa_reviewer=request.reviewer,
            )
        else:
            raise HTTPException(
                status_code=404,
                detail="Analysis for this file is no longer available - re-run the folder comparison and try again.",
            )

        return FeedbackResponse(
            feedback_id=feedback_id,
            analysis_id=file_result.analysis_id,
            accepted=True,
            message=f"Feedback recorded for {request.file_name}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Folder feedback failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Feedback submission failed: {str(e)}")


@router.get("/{folder_analysis_id}/report")
async def get_folder_report(folder_analysis_id: str):
    """Generate an HTML report for the entire folder comparison."""
    if folder_analysis_id not in folder_analysis_registry:
        raise HTTPException(status_code=404, detail="Folder analysis not found")

    stored = folder_analysis_registry[folder_analysis_id]
    response: FolderCompareResponse = stored["response"]
    dashboard = response.dashboard

    # Build per-file detail HTML for files with diffs
    file_details_html = ""
    for fr in response.file_results:
        if fr.status == "no_change":
            continue

        status_color = {
            "regression": "#c62828", "progression": "#2e7d32",
            "neutral": "#1565c0", "missing_in_result": "#e65100",
            "new_in_result": "#6a1b9a",
        }.get(fr.status, "#666")

        status_bg = {
            "regression": "#ffebee", "progression": "#e8f5e9",
            "neutral": "#e3f2fd", "missing_in_result": "#fff3e0",
            "new_in_result": "#f3e5f5",
        }.get(fr.status, "#f5f5f5")

        ops_html = ""
        if fr.operation_diffs:
            for op in fr.operation_diffs:
                ct = op.get("change_type", "modified")
                ops_html += f"""
                <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;margin-bottom:4px;border-radius:4px;border-left:3px solid {'#f59e0b' if ct=='modified' else '#22c55e' if ct=='added' else '#ef4444'};background:{'#fffbeb' if ct=='modified' else '#f0fdf4' if ct=='added' else '#fef2f2'};">
                    <span style="font-weight:600;font-size:13px;">{op.get('operation_name','Unknown')}</span>
                    <span style="font-size:11px;color:#666;">
                        {f'{op.get("lines_modified",0)} mod' if op.get("lines_modified",0) else ''}
                        {f' | {op.get("lines_added",0)} add' if op.get("lines_added",0) else ''}
                        {f' | {op.get("lines_removed",0)} rem' if op.get("lines_removed",0) else ''}
                    </span>
                </div>"""

        findings_html = ""
        if fr.key_findings:
            for f in fr.key_findings:
                findings_html += f'<li style="padding:6px 10px;margin-bottom:4px;background:#f8f9fa;border-left:3px solid #3949ab;border-radius:3px;font-size:13px;">{f}</li>'

        # Build detail HTML using the analysis_id link to single-file report
        detail_link = ""
        if fr.analysis_id:
            detail_link = f'<a href="/api/reports/{fr.analysis_id}?format=html" target="_blank" style="color:#1a237e;font-size:13px;text-decoration:underline;">View Full Detail Report &rarr;</a>'

        file_details_html += f"""
        <div id="file-{fr.file_name.replace('.','_').replace(' ','_')}" class="card" style="border-left:4px solid {status_color};">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
                <h3 style="margin:0;font-size:16px;">{fr.file_name}</h3>
                <span style="padding:4px 12px;border-radius:12px;font-size:12px;font-weight:700;text-transform:uppercase;background:{status_bg};color:{status_color};">{fr.status.replace('_',' ')}</span>
            </div>
            {'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px;"><div style="text-align:center;padding:8px;background:#f0fdf4;border-radius:6px;"><div style="font-size:20px;font-weight:700;color:#15803d;">'+str(fr.lines_added)+'</div><div style="font-size:11px;color:#666;">Added</div></div><div style="text-align:center;padding:8px;background:#fef2f2;border-radius:6px;"><div style="font-size:20px;font-weight:700;color:#dc2626;">'+str(fr.lines_removed)+'</div><div style="font-size:11px;color:#666;">Removed</div></div><div style="text-align:center;padding:8px;background:#fffbeb;border-radius:6px;"><div style="font-size:20px;font-weight:700;color:#b45309;">'+str(fr.lines_modified)+'</div><div style="font-size:11px;color:#666;">Modified</div></div><div style="text-align:center;padding:8px;background:#fef2f2;border-radius:6px;"><div style="font-size:20px;font-weight:700;color:#c62828;">'+str(fr.critical_changes)+'</div><div style="font-size:11px;color:#666;">Critical</div></div></div>' if not fr.files_identical else ''}
            {f'<p style="color:#555;font-size:13px;margin-bottom:8px;">{fr.reasoning}</p>' if fr.reasoning else ''}
            {f'<div style="margin-bottom:8px;"><strong style="font-size:13px;">Key Findings:</strong><ul style="list-style:none;padding:0;margin-top:6px;">{findings_html}</ul></div>' if findings_html else ''}
            {f'<div style="margin-bottom:8px;"><strong style="font-size:13px;">Operations ({fr.operations_with_changes}):</strong>{ops_html}</div>' if ops_html else ''}
            {detail_link}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Folder Comparison Report - {folder_analysis_id[:8]}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #1a237e, #3949ab); color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 24px; margin-bottom: 10px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .card {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .card h2 {{ color: #1a237e; border-bottom: 2px solid #e8eaf6; padding-bottom: 10px; margin-bottom: 15px; }}
        .dash-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }}
        .dash-item {{ background: #f8f9fa; padding: 16px; border-radius: 8px; text-align: center; }}
        .dash-item .value {{ font-size: 28px; font-weight: bold; }}
        .dash-item .label {{ color: #666; font-size: 12px; margin-top: 4px; }}
        .toc {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }}
        .toc a {{ padding: 4px 10px; border-radius: 4px; font-size: 12px; text-decoration: none; color: white; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 14px; }}
        @media print {{ body {{ background: white; }} .card {{ box-shadow: none; border: 1px solid #ddd; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Folder Comparison Report</h1>
            <p>Analysis ID: {folder_analysis_id} | Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        </div>

        <div class="card">
            <h2>Dashboard Summary</h2>
            <div class="dash-grid">
                <div class="dash-item"><div class="value" style="color:#1a237e;">{dashboard.total_files}</div><div class="label">Total Files</div></div>
                <div class="dash-item"><div class="value" style="color:#b45309;">{dashboard.files_with_diffs}</div><div class="label">Files with Diffs</div></div>
                <div class="dash-item"><div class="value" style="color:#15803d;">{dashboard.no_changes}</div><div class="label">No Changes</div></div>
                <div class="dash-item"><div class="value" style="color:#c62828;">{dashboard.regressions}</div><div class="label">Regressions</div></div>
                <div class="dash-item"><div class="value" style="color:#2e7d32;">{dashboard.progressions}</div><div class="label">Progressions</div></div>
                <div class="dash-item"><div class="value" style="color:#1565c0;">{dashboard.neutral}</div><div class="label">Neutral</div></div>
                <div class="dash-item"><div class="value" style="color:#e65100;">{dashboard.result_file_missing}</div><div class="label">Missing in Result</div></div>
                <div class="dash-item"><div class="value" style="color:#6a1b9a;">{dashboard.new_in_result}</div><div class="label">New in Result</div></div>
            </div>
        </div>

        <div class="card">
            <h2>Aggregate Changes</h2>
            <div class="dash-grid">
                <div class="dash-item"><div class="value" style="color:#15803d;">{dashboard.total_lines_added}</div><div class="label">Total Lines Added</div></div>
                <div class="dash-item"><div class="value" style="color:#dc2626;">{dashboard.total_lines_removed}</div><div class="label">Total Lines Removed</div></div>
                <div class="dash-item"><div class="value" style="color:#b45309;">{dashboard.total_lines_modified}</div><div class="label">Total Lines Modified</div></div>
                <div class="dash-item"><div class="value" style="color:#c62828;">{dashboard.total_critical_changes}</div><div class="label">Total Critical Changes</div></div>
            </div>
        </div>

        <div class="card">
            <h2>File Details</h2>
            {file_details_html if file_details_html else '<p style="color:#888;text-align:center;">All files are identical - no changes detected.</p>'}
        </div>

        <div class="footer">
            <p>Generated by NC Code Analyser with AI | HCL Software</p>
        </div>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)

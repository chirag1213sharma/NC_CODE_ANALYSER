"""
NC Code Analyser - Report Generation Routes
"""

import os
import difflib
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.core import get_settings, get_logger
from src.api.schemas import ReportRequest, ReportFormat
from src.api.routes.compare import analysis_registry

router = APIRouter(prefix="/reports", tags=["Reports"])
logger = get_logger(__name__)
settings = get_settings()

# HTML Report Template
REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NC Code Analysis Report - {{ analysis_id }}</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #1a237e, #3949ab); color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px; }
        .header h1 { font-size: 24px; margin-bottom: 10px; }
        .header p { opacity: 0.9; }
        .card { background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .card h2 { color: #1a237e; border-bottom: 2px solid #e8eaf6; padding-bottom: 10px; margin-bottom: 15px; }
        .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
        .summary-item { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }
        .summary-item .value { font-size: 28px; font-weight: bold; color: #1a237e; }
        .summary-item .label { color: #666; font-size: 14px; }
        .classification { display: inline-block; padding: 8px 16px; border-radius: 20px; font-weight: bold; text-transform: uppercase; }
        .classification.regression { background: #ffebee; color: #c62828; }
        .classification.progression { background: #e8f5e9; color: #2e7d32; }
        .classification.neutral { background: #e3f2fd; color: #1565c0; }
        .classification.uncertain { background: #fff3e0; color: #e65100; }
        .confidence-bar { height: 10px; background: #e0e0e0; border-radius: 5px; overflow: hidden; margin-top: 10px; }
        .confidence-fill { height: 100%; background: linear-gradient(90deg, #43a047, #66bb6a); }
        .key-findings { list-style: none; padding: 0; margin-top: 12px; }
        .key-findings li { padding: 8px 12px; margin-bottom: 6px; background: #f8f9fa; border-left: 4px solid #3949ab; border-radius: 4px; font-size: 14px; }
        .diff-table { width: 100%; border-collapse: collapse; }
        .diff-table th, .diff-table td { padding: 10px; text-align: left; border-bottom: 1px solid #eee; }
        .diff-table th { background: #f5f5f5; font-weight: 600; }
        .change-added { background: #e8f5e9; }
        .change-removed { background: #ffebee; }
        .change-modified { background: #fff3e0; }
        .severity-critical { color: #c62828; font-weight: bold; }
        .severity-high { color: #e65100; }
        .severity-medium { color: #f9a825; }
        .severity-low { color: #43a047; }
        .op-section { margin-bottom: 20px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; }
        .op-header { padding: 10px 15px; font-weight: 600; font-size: 14px; display: flex; align-items: center; justify-content: space-between; }
        .op-header.modified { background: #fff3e0; color: #e65100; border-left: 4px solid #f59e0b; }
        .op-header.added { background: #e8f5e9; color: #2e7d32; border-left: 4px solid #22c55e; }
        .op-header.removed { background: #ffebee; color: #c62828; border-left: 4px solid #ef4444; }
        .op-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: bold; text-transform: uppercase; }
        .op-badge.modified { background: #f59e0b; color: white; }
        .op-badge.added { background: #22c55e; color: white; }
        .op-badge.removed { background: #ef4444; color: white; }
        .op-badge.critical { background: #c62828; color: white; }
        .side-by-side { display: grid; grid-template-columns: 1fr 1fr; }
        .side-col { overflow-x: auto; }
        .side-header { padding: 6px 12px; background: #f5f5f5; font-weight: 600; font-size: 12px; color: #666; border-bottom: 1px solid #e0e0e0; }
        .code-line { font-family: 'Consolas', 'Monaco', monospace; font-size: 12px; padding: 1px 12px; white-space: pre; min-height: 20px; line-height: 20px; border-bottom: 1px solid #f5f5f5; }
        .code-line.unchanged { background: white; }
        .code-line.modified { background: #fff8e1; }
        .code-line.added { background: #e8f5e9; }
        .code-line.removed { background: #ffebee; }
        .footer { text-align: center; padding: 20px; color: #666; font-size: 14px; }
        @media print { body { background: white; } .card { box-shadow: none; border: 1px solid #ddd; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>NC Code Analysis Report</h1>
            <p>Analysis ID: {{ analysis_id }} | Generated: {{ generated_at }}</p>
        </div>

        <div class="card">
            <h2>File Comparison</h2>
            <p><strong>Baseline:</strong> {{ baseline_file }}</p>
            <p><strong>New File:</strong> {{ new_file }}</p>
            <p><strong>Status:</strong> {% if files_identical %}Files are identical{% else %}Changes detected{% endif %}</p>
        </div>

        {% if operation_diffs %}
        <div class="card">
            <h2>Operations with Changes</h2>
            {% for op in operation_diffs %}
            <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; margin-bottom: 6px; border-radius: 6px; border-left: 4px solid {% if op.change_type == 'modified' %}#f59e0b{% elif op.change_type == 'added' %}#22c55e{% else %}#ef4444{% endif %}; background: {% if op.change_type == 'modified' %}#fffbeb{% elif op.change_type == 'added' %}#f0fdf4{% else %}#fef2f2{% endif %};">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 11px; font-weight: bold; text-transform: uppercase; padding: 2px 8px; border-radius: 4px; color: white; background: {% if op.change_type == 'modified' %}#f59e0b{% elif op.change_type == 'added' %}#22c55e{% else %}#ef4444{% endif %};">{{ op.change_type }}</span>
                    <strong style="font-size: 14px;">{{ op.name }}</strong>
                    {% if op.has_critical %}<span style="font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; background: #c62828; color: white;">CRITICAL</span>{% endif %}
                </div>
                <div style="font-size: 12px; color: #666; display: flex; gap: 12px;">
                    {% if op.lines_modified > 0 %}<span style="color: #b45309;">{{ op.lines_modified }} modified</span>{% endif %}
                    {% if op.lines_added > 0 %}<span style="color: #15803d;">{{ op.lines_added }} added</span>{% endif %}
                    {% if op.lines_removed > 0 %}<span style="color: #dc2626;">{{ op.lines_removed }} removed</span>{% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        <div class="card">
            <h2>AI Classification</h2>
            <div style="display: flex; align-items: center; gap: 20px; margin-bottom: 15px;">
                <span class="classification {{ classification|lower }}">{{ classification }}</span>
                <div style="flex: 1;">
                    <div>Confidence: {{ (confidence * 100)|round(1) }}%</div>
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: {{ confidence * 100 }}%"></div>
                    </div>
                </div>
            </div>
            {% if key_findings %}
            <ul class="key-findings">
                {% for finding in key_findings %}
                <li>{{ finding }}</li>
                {% endfor %}
            </ul>
            {% endif %}
        </div>

        <div class="card">
            <h2>Change Summary</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="value">{{ lines_added }}</div>
                    <div class="label">Lines Added</div>
                </div>
                <div class="summary-item">
                    <div class="value">{{ lines_removed }}</div>
                    <div class="label">Lines Removed</div>
                </div>
                <div class="summary-item">
                    <div class="value">{{ lines_modified }}</div>
                    <div class="label">Lines Modified</div>
                </div>
                <div class="summary-item">
                    <div class="value severity-critical">{{ critical_changes }}</div>
                    <div class="label">Critical Changes</div>
                </div>
            </div>
        </div>

        {% if operation_diffs %}
        <div class="card">
            <h2>Operation G-Code Comparison</h2>
            {% for op in operation_diffs %}
            <div class="op-section">
                <div class="op-header {{ op.change_type }}">
                    <span>{{ op.name }}</span>
                    <span>
                        {% if op.has_critical %}<span class="op-badge critical">CRITICAL</span> {% endif %}
                        <span class="op-badge {{ op.change_type }}">{{ op.change_type|upper }}</span>
                    </span>
                </div>
                <div class="side-by-side">
                    <div class="side-col">
                        <div class="side-header">Baseline</div>
                        {% for row in op.rows %}
                        <div class="code-line {{ row.status }}">{{ row.old if row.old else '' }}</div>
                        {% endfor %}
                    </div>
                    <div class="side-col">
                        <div class="side-header">Result</div>
                        {% for row in op.rows %}
                        <div class="code-line {{ row.status }}">{{ row.new if row.new else '' }}</div>
                        {% endfor %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if command_diffs %}
        <div class="card">
            <h2>Detailed Changes</h2>
            <table class="diff-table">
                <thead>
                    <tr>
                        <th>Line</th>
                        <th>Type</th>
                        <th>Description</th>
                        <th>Severity</th>
                    </tr>
                </thead>
                <tbody>
                    {% for diff in command_diffs[:50] %}
                    <tr class="change-{{ diff.change_type }}">
                        <td>{{ diff.line_number }}</td>
                        <td>{{ diff.change_type|capitalize }}</td>
                        <td>{{ diff.description }}</td>
                        <td class="severity-{{ diff.severity if diff.is_critical else 'low' }}">
                            {{ 'Critical' if diff.is_critical else 'Normal' }}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% if command_diffs|length > 50 %}
            <p style="margin-top: 10px; color: #666;">Showing 50 of {{ command_diffs|length }} changes</p>
            {% endif %}
        </div>
        {% endif %}

        {% if qa_reviewed %}
        <div class="card">
            <h2>QA Review</h2>
            <p><strong>Reviewed by:</strong> {{ qa_reviewer }}</p>
            <p><strong>QA Classification:</strong> <span class="classification {{ qa_classification|lower }}">{{ qa_classification }}</span></p>
            <p><strong>Notes:</strong> {{ qa_notes }}</p>
        </div>
        {% endif %}

        <div class="footer">
            <p>Generated by NC Code Analyser with AI | HCL Software</p>
        </div>
    </div>
</body>
</html>
"""


def _build_operation_diffs_display(diff_result) -> list:
    """Build operation diff display data with aligned side-by-side rows."""
    operation_diffs_display = []

    for op_diff in diff_result.operation_diffs:
        old_lines = op_diff.raw_lines_old
        new_lines = op_diff.raw_lines_new

        # Compute aligned rows for side-by-side display
        rows = []
        if old_lines or new_lines:
            matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'equal':
                    for idx in range(i2 - i1):
                        rows.append({"old": old_lines[i1 + idx], "new": new_lines[j1 + idx], "status": "unchanged"})
                elif tag == 'replace':
                    max_len = max(i2 - i1, j2 - j1)
                    for idx in range(max_len):
                        old_text = old_lines[i1 + idx] if i1 + idx < i2 else ""
                        new_text = new_lines[j1 + idx] if j1 + idx < j2 else ""
                        rows.append({"old": old_text, "new": new_text, "status": "modified"})
                elif tag == 'delete':
                    for i in range(i1, i2):
                        rows.append({"old": old_lines[i], "new": "", "status": "removed"})
                elif tag == 'insert':
                    for j in range(j1, j2):
                        rows.append({"old": "", "new": new_lines[j], "status": "added"})

        operation_diffs_display.append({
            "name": op_diff.operation_name_old or op_diff.operation_name_new or "Unknown",
            "change_type": op_diff.change_type.value,
            "has_critical": op_diff.critical_changes > 0,
            "lines_modified": op_diff.lines_modified,
            "lines_added": op_diff.lines_added,
            "lines_removed": op_diff.lines_removed,
            "rows": rows,
        })

    return operation_diffs_display


@router.post("/{analysis_id}")
async def generate_report(analysis_id: str, request: Optional[ReportRequest] = None):
    """Generate a report for an analysis."""
    if analysis_id not in analysis_registry:
        raise HTTPException(status_code=404, detail="Analysis not found")

    format_type = ReportFormat.HTML
    if request and request.format:
        format_type = request.format

    stored = analysis_registry[analysis_id]
    analysis = stored["analysis"]
    diff_result = stored["diff_result"]

    # Prepare template data
    command_diffs = []
    for d in diff_result.command_diffs:
        command_diffs.append({
            "line_number": d.line_diff.line_number_old or d.line_diff.line_number_new,
            "change_type": d.line_diff.change_type.value,
            "description": d.change_description,
            "is_critical": d.is_critical,
            "severity": d.line_diff.severity.value if hasattr(d.line_diff, 'severity') else 'low',
        })

    # Build operation diffs for side-by-side display
    operation_diffs_display = _build_operation_diffs_display(diff_result)

    template_data = {
        "analysis_id": analysis_id,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "baseline_file": diff_result.baseline_file,
        "new_file": diff_result.new_file,
        "files_identical": diff_result.files_identical,
        "classification": analysis.classification.value.upper(),
        "confidence": analysis.confidence,
        "key_findings": analysis.key_findings if hasattr(analysis, 'key_findings') else [],
        "lines_added": diff_result.summary.lines_added if diff_result.summary else 0,
        "lines_removed": diff_result.summary.lines_removed if diff_result.summary else 0,
        "lines_modified": diff_result.summary.lines_modified if diff_result.summary else 0,
        "critical_changes": diff_result.summary.critical_changes if diff_result.summary else 0,
        "operation_diffs": operation_diffs_display,
        "command_diffs": command_diffs,
        "qa_reviewed": analysis.qa_reviewed,
        "qa_classification": analysis.qa_classification.value.upper() if analysis.qa_classification else None,
        "qa_notes": analysis.qa_notes,
        "qa_reviewer": analysis.qa_reviewer,
    }

    if format_type == ReportFormat.JSON:
        return template_data

    elif format_type == ReportFormat.HTML:
        from jinja2 import Template
        template = Template(REPORT_TEMPLATE)
        html_content = template.render(**template_data)
        return HTMLResponse(content=html_content)

    elif format_type == ReportFormat.PDF:
        # For PDF, we'd need weasyprint or similar
        # For now, return HTML with a note
        raise HTTPException(
            status_code=501,
            detail="PDF generation requires WeasyPrint. Please install it or use HTML format."
        )


@router.get("/{analysis_id}")
async def get_report(analysis_id: str, format: ReportFormat = ReportFormat.HTML):
    """Get a report in the specified format."""
    request = ReportRequest(analysis_id=analysis_id, format=format)
    return await generate_report(analysis_id, request)

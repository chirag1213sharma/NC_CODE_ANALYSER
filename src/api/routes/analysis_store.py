"""
NC Code Analyser - Disk-backed cache for AnalysisResult objects.

The route modules keep an in-memory `analysis_registry`, but that is wiped
on every uvicorn restart, which made QA feedback fail with
"Analysis not found" whenever the service had been restarted between
running a comparison and submitting feedback.

This helper persists each analysis to `data/analyses/{analysis_id}.json`
so the feedback routes can recover it after a restart.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core import get_logger
from src.diff_engine.models import AnalysisResult, DiffResult

logger = get_logger(__name__)

# data/analyses/ at the repo root.
# src/api/routes/analysis_store.py -> parents[3] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
ANALYSES_DIR = _REPO_ROOT / "data" / "analyses"


def _ensure_dir() -> None:
    ANALYSES_DIR.mkdir(parents=True, exist_ok=True)


def persist_analysis(analysis: AnalysisResult, diff_result: DiffResult) -> None:
    """Write an AnalysisResult (with its diff_result) to disk."""
    try:
        _ensure_dir()
        path = ANALYSES_DIR / f"{analysis.analysis_id}.json"
        payload = {
            "analysis": json.loads(analysis.model_dump_json()),
            "diff_result": json.loads(diff_result.model_dump_json()),
            "saved_at": datetime.utcnow().isoformat(),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as e:  # pragma: no cover - best effort
        logger.warning(
            "Failed to persist analysis to disk",
            analysis_id=analysis.analysis_id,
            error=str(e),
        )


def load_analysis(analysis_id: str) -> Optional[dict]:
    """Load a previously persisted analysis. Returns the same shape
    as the in-memory registry entry: {"analysis", "diff_result", "created_at"}.
    """
    path = ANALYSES_DIR / f"{analysis_id}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        analysis = AnalysisResult.model_validate(raw["analysis"])
        diff_result = DiffResult.model_validate(raw["diff_result"])
        return {
            "analysis": analysis,
            "diff_result": diff_result,
            "created_at": raw.get("saved_at"),
        }
    except Exception as e:
        logger.error(
            "Failed to load persisted analysis",
            analysis_id=analysis_id,
            error=str(e),
        )
        return None

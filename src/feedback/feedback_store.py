"""
NC Code Analyser - Feedback Store (JSON-backed, fine-tune ready)

Stores QA feedback as a JSON file at the repo base directory (feedback.json).
Each record is structured as a chat-style training sample so the file can be
used directly to fine-tune the local LLM (e.g. Mistral via LoRA/QLoRA).

Design notes:
- Raw NC contents are NOT stored. The diff/operation summaries already
  embedded in the user prompt carry the signal the model needs.
- The user message in `training_sample` does NOT repeat the system prompt
  (the live prompt builder prepends SYSTEM_PROMPT; we strip it here so the
  trainer sees system + user as two distinct messages).
- The assistant message does NOT include a confidence field, because QA
  does not provide one and a constant value would collapse the model output.
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.core import get_logger
from src.diff_engine.models import (
    DiffResult, AnalysisResult, ClassificationResult,
)

logger = get_logger(__name__)


# Path to the JSON file at the repository base directory.
# src/feedback/feedback_store.py -> parents[2] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
FEEDBACK_FILE = _REPO_ROOT / "feedback.json"


class FeedbackStore:
    """JSON-backed feedback store. Public API kept stable for the routes."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path: Path = Path(file_path) if file_path else FEEDBACK_FILE
        self._lock = threading.Lock()
        self._ensure_file()
        logger.info(
            "Feedback store initialized",
            path=str(self.file_path),
            count=len(self._read_all()),
        )

    # ---------- public API ----------

    def add_feedback(
        self,
        analysis_result: AnalysisResult,
        qa_classification: ClassificationResult,
        qa_notes: str,
        qa_reviewer: str,
        **_ignored: Any,  # baseline_content / result_content no longer stored
    ) -> str:
        """Append a QA feedback record to feedback.json."""
        feedback_id = str(uuid.uuid4())
        diff_result = analysis_result.diff_result

        ai_pred = {
            "classification": analysis_result.classification.value.upper(),
            "key_findings": list(analysis_result.key_findings or []),
        }

        qa_findings = self._notes_to_findings(qa_notes)
        qa_correction = {
            "classification": qa_classification.value.upper(),
            "key_findings": qa_findings,
        }

        was_correction = (
            analysis_result.classification != qa_classification
        )

        record: Dict[str, Any] = {
            "feedback_id": feedback_id,
            "analysis_id": analysis_result.analysis_id,
            "created_at": datetime.utcnow().isoformat(),
            "qa_reviewer": qa_reviewer,
            "baseline_file": analysis_result.baseline_file,
            "result_file": analysis_result.new_file,
            "ai_prediction": ai_pred,
            "qa_correction": qa_correction,
            "was_correction": was_correction,
            "training_sample": self._build_training_sample(
                diff_result, qa_correction
            ),
        }

        with self._lock:
            data = self._read_all()
            data.append(record)
            self._write_all(data)

        logger.info(
            "Feedback stored",
            feedback_id=feedback_id,
            was_correction=was_correction,
            total=len(data),
        )
        return feedback_id

    def get_feedback_stats(self) -> Dict[str, Any]:
        """Return aggregate stats about stored feedback."""
        data = self._read_all()
        total = len(data)
        if total == 0:
            return {
                "total_feedback": 0,
                "corrections": 0,
                "correction_rate": 0.0,
                "by_classification": {},
            }

        corrections = sum(1 for r in data if r.get("was_correction"))
        by_classification: Dict[str, int] = {}
        for r in data:
            cls = (
                r.get("qa_correction", {}).get("classification")
                or "UNKNOWN"
            ).lower()
            by_classification[cls] = by_classification.get(cls, 0) + 1

        return {
            "total_feedback": total,
            "corrections": corrections,
            "correction_rate": corrections / total,
            "by_classification": by_classification,
        }

    def get_recent_feedback(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return most recent feedback entries (newest first)."""
        data = self._read_all()
        data.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        recent = []
        for r in data[:limit]:
            qa = r.get("qa_correction", {}) or {}
            recent.append({
                "feedback_id": r.get("feedback_id"),
                "analysis_id": r.get("analysis_id"),
                "baseline_file": r.get("baseline_file"),
                "new_file": r.get("result_file"),
                "ai_classification": r.get("ai_prediction", {}).get("classification"),
                "qa_classification": qa.get("classification"),
                "qa_notes": " | ".join(qa.get("key_findings", []) or []),
                "qa_reviewer": r.get("qa_reviewer"),
                "was_correction": r.get("was_correction"),
                "created_at": r.get("created_at"),
            })
        return recent

    def delete_feedback(self, feedback_id: str) -> bool:
        """Delete one feedback entry by id."""
        with self._lock:
            data = self._read_all()
            new_data = [r for r in data if r.get("feedback_id") != feedback_id]
            if len(new_data) == len(data):
                return False
            self._write_all(new_data)
        logger.info("Feedback deleted", feedback_id=feedback_id)
        return True

    def reset_database(self) -> bool:
        """Clear the JSON file. Caller is expected to confirm."""
        with self._lock:
            self._write_all([])
        logger.warning("Feedback store reset", path=str(self.file_path))
        return True

    # ---------- internal helpers ----------

    def _ensure_file(self) -> None:
        if not self.file_path.exists():
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text("[]", encoding="utf-8")

    def _read_all(self) -> List[Dict[str, Any]]:
        try:
            text = self.file_path.read_text(encoding="utf-8").strip()
            if not text:
                return []
            data = json.loads(text)
            if not isinstance(data, list):
                logger.warning("feedback.json is not a list - returning empty view")
                return []
            return data
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as e:
            logger.error("feedback.json is corrupt - returning empty list", error=str(e))
            return []

    def _write_all(self, data: List[Dict[str, Any]]) -> None:
        tmp_path = self.file_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(self.file_path)

    @staticmethod
    def _notes_to_findings(notes: str) -> List[str]:
        """Split free-text QA notes into <=3 short key_findings (~15 words each)."""
        if not notes:
            return []
        # Split on common separators that QA writers actually use.
        text = (
            notes.replace("|", "\n")
                 .replace(";", "\n")
                 .replace(". ", ".\n")
        )
        raw_parts: List[str] = []
        for chunk in text.splitlines():
            chunk = chunk.strip(" -*\t.")
            if chunk:
                raw_parts.append(chunk)
        if not raw_parts:
            raw_parts = [notes.strip()]

        findings: List[str] = []
        for part in raw_parts[:3]:
            words = part.split()
            if len(words) > 18:
                part = " ".join(words[:18])
            findings.append(part)
        return findings

    def _build_training_sample(
        self,
        diff_result: DiffResult,
        qa_correction: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a chat-format SFT sample.

        - system: the classifier's SYSTEM_PROMPT (verbatim).
        - user:   the live analysis prompt, WITH its leading SYSTEM_PROMPT
                  prefix stripped to avoid duplication.
        - assistant: JSON with classification + key_findings (no confidence).
        """
        # Lazy import to avoid circular dependency at module load.
        from src.ai.gemini_classifier import OllamaClassifier

        system_prompt = OllamaClassifier.SYSTEM_PROMPT
        # _build_analysis_prompt does not depend on instance state; bind it
        # against a bare instance to reuse the live prompt template.
        full_user_prompt = OllamaClassifier._build_analysis_prompt(
            OllamaClassifier.__new__(OllamaClassifier),
            diff_result,
            None,
        )

        # The live builder prepends SYSTEM_PROMPT + "\n\n---\n\n". Strip it so
        # the training sample has system + user as two distinct messages.
        user_prompt = full_user_prompt
        if user_prompt.startswith(system_prompt):
            user_prompt = user_prompt[len(system_prompt):].lstrip("\n-").lstrip()

        assistant_payload = {
            "classification": qa_correction["classification"],
            "key_findings": qa_correction.get("key_findings", []),
        }
        assistant_message = json.dumps(assistant_payload, ensure_ascii=False)

        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": assistant_message},
            ],
        }

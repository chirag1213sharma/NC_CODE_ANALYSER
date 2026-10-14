"""
NC Code Analyser - Ollama AI Integration for Change Classification
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core import get_settings, get_logger
from src.diff_engine.models import (
    DiffResult, CommandDiff, OperationDiff, ClassificationResult,
    AnalysisResult, ChangeSeverity, ChangeCategory
)

logger = get_logger(__name__)
settings = get_settings()


class OllamaClassifier:
    """AI classifier using local Ollama model for NC code change analysis."""

    SYSTEM_PROMPT = """You are an expert CNC manufacturing engineer and QA specialist with deep knowledge of:
- G-code and M-code programming
- CNC machining operations (milling, turning, multi-axis)
- CAM software like CAMWorks
- Manufacturing quality assurance and regression testing

Your task is to analyze differences between a baseline NC program and a newly generated NC program.
You must classify changes as one of:

1. **REGRESSION** - An undesired change that could negatively affect:
   - Part quality or dimensions
   - Machine safety
   - Tool life
   - Cycle time (significantly worse)
   - Missing required operations
   
2. **PROGRESSION** - An expected improvement such as:
   - Optimized feed rates or speeds
   - New Operations Added
   - Better toolpath efficiency
   - Improved surface finish
   - Reduced cycle time
   - Bug fixes from previous versions

3. **NEUTRAL** - Changes with no functional impact:
   - Comment modifications
   - Line number changes
   - Whitespace/formatting
   - Equivalent but reformatted code
   - Merging multiple axis moves in one

For each analysis, provide:
1. Classification (REGRESSION, PROGRESSION, or NEUTRAL)
2. Confidence score (0.0 to 1.0)
3. Maximum 3 short key findings (each under 15 words) summarizing what changed and why it matters

Rules for key_findings:
- Maximum 3 points
- Each point must be as short as possible (under 15 words)
- Focus only on what is wrong or notable
- Start each point with the change type (e.g., "Feed rate", "Spindle speed", "Missing operation")

Consider the manufacturing context:
- Coordinate changes are usually CRITICAL - could affect part dimensions
- Feed/speed changes could be optimization (PROGRESSION) or errors (REGRESSION)
- Tool changes are CRITICAL - wrong tool = scrapped part
- Missing operations are always REGRESSION
- Added operations need verification - could be PROGRESSION or REGRESSION
"""

    def __init__(self):
        """Initialize the Ollama classifier."""
        self._available = False
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model
        self._initialize_model()

    def _initialize_model(self) -> None:
        """Check that Ollama is reachable and the model is loaded."""
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            if self._model not in models:
                # Also check without tag suffix (e.g. "qwen2.5-coder:7b" may list as full name)
                base_match = any(m.startswith(self._model.split(":")[0]) for m in models)
                if not base_match:
                    logger.warning(
                        "Ollama model not found locally - pull it with: ollama pull %s",
                        self._model,
                    )
            self._available = True
            logger.info("Ollama model ready", model=self._model, url=self._base_url)
        except Exception as e:
            logger.warning("Ollama not reachable - AI classification disabled", error=str(e))
            self._available = False

    def is_available(self) -> bool:
        """Check if the AI classifier is available."""
        return self._available

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def classify_changes(
        self,
        diff_result: DiffResult,
        similar_cases: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisResult:
        """Classify changes in the diff result using Gemini AI."""
        analysis_id = str(uuid.uuid4())

        if not self.is_available():
            # Return uncertain classification if AI is not available
            return AnalysisResult(
                analysis_id=analysis_id,
                baseline_file=diff_result.baseline_file,
                new_file=diff_result.new_file,
                diff_result=diff_result,
                classification=ClassificationResult.UNCERTAIN,
                confidence=0.0,
                reasoning="AI classification unavailable",
                recommendations=[],
                key_findings=["AI unavailable - manual review required"],
            )

        # Build the analysis prompt
        prompt = self._build_analysis_prompt(diff_result, similar_cases)

        try:
            # Call Ollama API
            response = await self._call_ollama(prompt)

            # Parse the response
            classification, confidence, reasoning, key_findings = self._parse_response(response)

            # Update diff result with classification
            diff_result.classification = classification
            diff_result.classification_confidence = confidence
            diff_result.classification_reasoning = reasoning

            return AnalysisResult(
                analysis_id=analysis_id,
                baseline_file=diff_result.baseline_file,
                new_file=diff_result.new_file,
                diff_result=diff_result,
                classification=classification,
                confidence=confidence,
                reasoning=reasoning,
                recommendations=[],
                key_findings=key_findings,
            )

        except Exception as e:
            logger.error("Failed to classify changes", error=str(e))
            return AnalysisResult(
                analysis_id=analysis_id,
                baseline_file=diff_result.baseline_file,
                new_file=diff_result.new_file,
                diff_result=diff_result,
                classification=ClassificationResult.UNCERTAIN,
                confidence=0.0,
                reasoning="Classification failed",
                recommendations=[],
                key_findings=["Classification failed - manual review required"],
            )

    def _group_diffs_into_hunks(
        self,
        diffs: List[CommandDiff],
        context_lines: int,
    ) -> List[Dict[str, Any]]:
        """Group adjacent critical diffs into git-style hunks.

        Two diffs are merged into one hunk when their context windows touch
        or overlap on EITHER the baseline or new side. Each returned hunk
        contains the inclusive line ranges for both files and the list of
        diffs it covers.
        """
        if not diffs:
            return []

        def _line_pair(d: CommandDiff) -> tuple:
            ln_old = d.line_diff.line_number_old
            ln_new = d.line_diff.line_number_new
            anchor = ln_old if ln_old is not None else ln_new
            return (anchor, ln_old, ln_new)

        ordered = sorted(diffs, key=_line_pair)

        hunks: List[Dict[str, Any]] = []
        for d in ordered:
            ln_old = d.line_diff.line_number_old
            ln_new = d.line_diff.line_number_new
            old_lo = old_hi = ln_old
            new_lo = new_hi = ln_new

            if hunks:
                cur = hunks[-1]
                # Two hunks touch if expanding each by `context_lines` on
                # either side would make their windows overlap on the same
                # file. Check whichever side both diffs have a line for.
                merge = False
                if (
                    cur["old_hi"] is not None
                    and old_lo is not None
                    and old_lo - cur["old_hi"] <= 2 * context_lines + 1
                ):
                    merge = True
                if (
                    cur["new_hi"] is not None
                    and new_lo is not None
                    and new_lo - cur["new_hi"] <= 2 * context_lines + 1
                ):
                    merge = True
                if merge:
                    cur["diffs"].append(d)
                    if old_lo is not None:
                        cur["old_lo"] = min(
                            x for x in (cur["old_lo"], old_lo) if x is not None
                        )
                        cur["old_hi"] = max(
                            x for x in (cur["old_hi"], old_hi) if x is not None
                        )
                    if new_lo is not None:
                        cur["new_lo"] = min(
                            x for x in (cur["new_lo"], new_lo) if x is not None
                        )
                        cur["new_hi"] = max(
                            x for x in (cur["new_hi"], new_hi) if x is not None
                        )
                    continue

            hunks.append({
                "diffs": [d],
                "old_lo": old_lo, "old_hi": old_hi,
                "new_lo": new_lo, "new_hi": new_hi,
            })

        return hunks

    def _format_hunk(
        self,
        index: int,
        hunk: Dict[str, Any],
        diff_result: DiffResult,
        context_lines: int,
    ) -> str:
        """Render one hunk as a markdown block with BASELINE + NEW windows."""
        baseline_map = diff_result.baseline_lines_by_number or {}
        new_map = diff_result.new_lines_by_number or {}

        def _slice(line_map: Dict[int, str], lo, hi) -> List[tuple]:
            if lo is None or hi is None or not line_map:
                return []
            start = max(min(line_map), lo - context_lines)
            end = min(max(line_map), hi + context_lines)
            return [
                (n, line_map[n])
                for n in range(start, end + 1)
                if n in line_map
            ]

        baseline_window = _slice(baseline_map, hunk["old_lo"], hunk["old_hi"])
        new_window = _slice(new_map, hunk["new_lo"], hunk["new_hi"])

        changed_old = {
            d.line_diff.line_number_old
            for d in hunk["diffs"]
            if d.line_diff.line_number_old is not None
        }
        changed_new = {
            d.line_diff.line_number_new
            for d in hunk["diffs"]
            if d.line_diff.line_number_new is not None
        }

        def _render(window: List[tuple], changed: set) -> str:
            if not window:
                return "(no lines)\n"
            width = len(str(window[-1][0]))
            lines = []
            for n, text in window:
                marker = ">" if n in changed else " "
                lines.append(f"{marker} {n:>{width}}: {text.rstrip()}")
            return "\n".join(lines) + "\n"

        parts = [f"#### Hunk {index}\n\n"]
        # One-line summary of what changed in this hunk.
        for d in hunk["diffs"]:
            anchor = (
                d.line_diff.line_number_old
                or d.line_diff.line_number_new
            )
            parts.append(f"- Line {anchor}: {d.change_description}\n")
        parts.append("\nBASELINE:\n```\n")
        parts.append(_render(baseline_window, changed_old))
        parts.append("```\n\nNEW:\n```\n")
        parts.append(_render(new_window, changed_new))
        parts.append("```\n\n")
        return "".join(parts)

    def _build_analysis_prompt(
        self,
        diff_result: DiffResult,
        similar_cases: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build the analysis prompt for Gemini."""
        prompt_parts = [self.SYSTEM_PROMPT, "\n\n---\n\n"]

        # Add similar cases for context if available (RAG)
        if similar_cases:
            prompt_parts.append("## Similar Past Cases for Reference:\n\n")
            for i, case in enumerate(similar_cases[:3], 1):
                prompt_parts.append(f"### Case {i}:\n")
                prompt_parts.append(f"- Change Type: {case.get('change_type', 'Unknown')}\n")
                prompt_parts.append(f"- QA Classification: {case.get('classification', 'Unknown')}\n")
                prompt_parts.append(f"- Reasoning: {case.get('reasoning', 'N/A')}\n\n")
            prompt_parts.append("---\n\n")

        # Add current analysis request
        prompt_parts.append("## Current NC Code Comparison:\n\n")
        prompt_parts.append(f"**Baseline File:** {diff_result.baseline_file}\n")
        prompt_parts.append(f"**New File:** {diff_result.new_file}\n\n")

        # Add summary
        if diff_result.summary:
            summary = diff_result.summary
            prompt_parts.append("### Change Summary:\n")
            prompt_parts.append(f"- Lines Added: {summary.lines_added}\n")
            prompt_parts.append(f"- Lines Removed: {summary.lines_removed}\n")
            prompt_parts.append(f"- Lines Modified: {summary.lines_modified}\n")
            prompt_parts.append(f"- Critical Changes: {summary.critical_changes}\n")
            prompt_parts.append(f"- High Severity: {summary.high_changes}\n")
            prompt_parts.append(f"- Medium Severity: {summary.medium_changes}\n\n")

            if summary.changes_by_category:
                prompt_parts.append("### Changes by Category:\n")
                for cat, count in summary.changes_by_category.items():
                    prompt_parts.append(f"- {cat}: {count}\n")
                prompt_parts.append("\n")

        # Add detailed command diffs (limit to most important)
        critical_diffs = [d for d in diff_result.command_diffs if d.is_critical]
        other_diffs = [d for d in diff_result.command_diffs if not d.is_critical][:10]

        if critical_diffs:
            context_lines = getattr(settings, "prompt_context_lines", 5)
            max_hunks = getattr(settings, "prompt_max_hunks", 12)
            hunks = self._group_diffs_into_hunks(
                critical_diffs[:40],  # cap before grouping to bound cost
                context_lines=context_lines,
            )
            prompt_parts.append(
                "### Critical Changes (with surrounding context):\n\n"
            )
            prompt_parts.append(
                f"Each hunk shows ±{context_lines} unchanged lines of context "
                "from the BASELINE and NEW files so you can judge whether an "
                "added/changed token (e.g. a feed rate) is genuinely new or "
                "was already present nearby. Use the full context, not just "
                "the changed line, when classifying.\n\n"
            )
            for i, hunk in enumerate(hunks[:max_hunks], 1):
                prompt_parts.append(
                    self._format_hunk(i, hunk, diff_result, context_lines)
                )
            if len(hunks) > max_hunks:
                prompt_parts.append(
                    f"_({len(hunks) - max_hunks} additional hunks omitted "
                    "to keep prompt size manageable.)_\n\n"
                )

        if other_diffs:
            prompt_parts.append("### Other Notable Changes:\n\n")
            for diff in other_diffs:
                prompt_parts.append(f"- Line {diff.line_diff.line_number_old or diff.line_diff.line_number_new}: {diff.change_description}\n")
            prompt_parts.append("\n")

        # Add operation-level changes
        if diff_result.operation_diffs:
            prompt_parts.append("### Operation Changes:\n\n")
            for op_diff in diff_result.operation_diffs:
                if op_diff.change_type.value == "added":
                    prompt_parts.append(f"- **ADDED:** {op_diff.operation_name_new} (Tool: T{op_diff.tool_new})\n")
                elif op_diff.change_type.value == "removed":
                    prompt_parts.append(f"- **REMOVED:** {op_diff.operation_name_old} (Tool: T{op_diff.tool_old})\n")
                elif op_diff.change_type.value == "modified":
                    prompt_parts.append(f"- **MODIFIED:** {op_diff.operation_name_old} - {op_diff.lines_modified} lines changed, {op_diff.critical_changes} critical\n")
            prompt_parts.append("\n")

        # Request structured response
        prompt_parts.append("""
---

## Your Analysis:

Respond ONLY with this JSON format:

```json
{
    "classification": "REGRESSION" | "PROGRESSION" | "NEUTRAL",
    "confidence": 0.0 to 1.0,
    "key_findings": [
        "Short finding 1 (max 15 words)",
        "Short finding 2 (max 15 words)",
        "Short finding 3 (max 15 words)"
    ]
}
```

Maximum 3 key_findings. Each must be concise and start on a new line.
""")

        return "".join(prompt_parts)

    async def _call_ollama(self, prompt: str) -> str:
        """Call the local Ollama API with the prompt."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 40,
                "num_predict": 4096,
            },
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    def _parse_response(
        self, response: str
    ) -> tuple[ClassificationResult, float, str, List[str]]:
        """Parse the Gemini response into structured data.
        
        Returns: (classification, confidence, reasoning, key_findings)
        """
        try:
            # Extract JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in response")

            json_str = response[json_start:json_end]
            data = json.loads(json_str)

            # Parse classification
            classification_str = data.get("classification", "UNCERTAIN").upper()
            if classification_str == "REGRESSION":
                classification = ClassificationResult.REGRESSION
            elif classification_str == "PROGRESSION":
                classification = ClassificationResult.PROGRESSION
            elif classification_str == "NEUTRAL":
                classification = ClassificationResult.NEUTRAL
            else:
                classification = ClassificationResult.UNCERTAIN

            # Parse confidence
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]

            # Parse key_findings (replaces old reasoning + recommendations)
            key_findings = data.get("key_findings", [])
            if not isinstance(key_findings, list):
                key_findings = [str(key_findings)]
            key_findings = key_findings[:3]  # Enforce max 3

            # Build reasoning from key_findings for backward compat
            reasoning = " | ".join(key_findings) if key_findings else "No findings"

            return classification, confidence, reasoning, key_findings

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse Ollama response as JSON", error=str(e))
            
            # Fallback: try to extract information from text
            response_lower = response.lower()
            
            if "regression" in response_lower:
                classification = ClassificationResult.REGRESSION
            elif "progression" in response_lower:
                classification = ClassificationResult.PROGRESSION
            elif "neutral" in response_lower:
                classification = ClassificationResult.NEUTRAL
            else:
                classification = ClassificationResult.UNCERTAIN

            return classification, 0.5, response[:200], ["Manual review recommended"]


# Synchronous wrapper for non-async contexts
class OllamaClassifierSync:
    """Synchronous wrapper for OllamaClassifier."""

    def __init__(self):
        self._classifier = OllamaClassifier()

    def is_available(self) -> bool:
        return self._classifier.is_available()

    def classify_changes(
        self,
        diff_result: DiffResult,
        similar_cases: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisResult:
        """Synchronous version of classify_changes."""
        import asyncio
        
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self._classifier.classify_changes(diff_result, similar_cases)
        )

"""
NC Code Analyser - Feedback Routes
"""

from fastapi import APIRouter, HTTPException

from src.core import get_logger
from src.api.schemas import FeedbackRequest, FeedbackResponse, FeedbackStats
from src.api.routes.compare import analysis_registry
from src.api.routes.analysis_store import load_analysis
from src.diff_engine.models import ClassificationResult
from src.feedback import FeedbackStore

router = APIRouter(prefix="/feedback", tags=["Feedback"])
logger = get_logger(__name__)

# Initialize feedback store
feedback_store = FeedbackStore()


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """Submit QA feedback for an analysis."""
    
    # Validate analysis exists (memory first, then on-disk cache)
    stored = analysis_registry.get(request.analysis_id)
    if stored is None:
        stored = load_analysis(request.analysis_id)
        if stored is not None:
            # Re-hydrate the in-memory registry so subsequent calls are fast.
            analysis_registry[request.analysis_id] = stored
    if stored is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Validate classification
    valid_classifications = {"REGRESSION", "PROGRESSION", "NEUTRAL"}
    if request.classification.upper() not in valid_classifications:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid classification. Must be one of: {valid_classifications}"
        )

    try:
        analysis = stored["analysis"]

        # Map string to enum
        qa_classification = ClassificationResult(request.classification.lower())

        # Persist feedback as a fine-tune-ready record in feedback.json
        feedback_id = feedback_store.add_feedback(
            analysis_result=analysis,
            qa_classification=qa_classification,
            qa_notes=request.notes,
            qa_reviewer=request.reviewer,
        )

        # Update analysis with QA review
        analysis.qa_reviewed = True
        analysis.qa_classification = qa_classification
        analysis.qa_notes = request.notes
        analysis.qa_reviewer = request.reviewer

        logger.info(
            "Feedback submitted",
            feedback_id=feedback_id,
            analysis_id=request.analysis_id,
            was_correction=analysis.classification != qa_classification,
        )

        return FeedbackResponse(
            feedback_id=feedback_id,
            analysis_id=request.analysis_id,
            accepted=True,
            message="Feedback recorded successfully. Thank you for helping improve the AI!",
        )

    except Exception as e:
        logger.error("Failed to submit feedback", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {str(e)}")


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats():
    """Get feedback statistics."""
    stats = feedback_store.get_feedback_stats()
    return FeedbackStats(**stats)


@router.get("/recent")
async def get_recent_feedback(limit: int = 20):
    """Get recent feedback entries."""
    feedback_list = feedback_store.get_recent_feedback(limit)
    return {"feedback": feedback_list, "total": len(feedback_list)}


@router.delete("/{feedback_id}")
async def delete_feedback(feedback_id: str):
    """Delete a feedback entry."""
    success = feedback_store.delete_feedback(feedback_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Feedback not found")

    return {"message": "Feedback deleted", "feedback_id": feedback_id}


@router.post("/reset")
async def reset_feedback_database(confirm: bool = False):
    """
    Reset the entire feedback database.
    WARNING: This will delete all learned patterns!
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Please confirm reset by passing confirm=true"
        )

    success = feedback_store.reset_database()

    if not success:
        raise HTTPException(status_code=500, detail="Failed to reset database")

    logger.warning("Feedback database reset by user")
    return {"message": "Feedback database has been reset"}

"""
NC Code Analyser - API Routes Module
"""

from fastapi import APIRouter

from src.api.routes.files import router as files_router
from src.api.routes.compare import router as compare_router
from src.api.routes.feedback import router as feedback_router
from src.api.routes.reports import router as reports_router
from src.api.routes.folder_compare import router as folder_compare_router

# Create main API router
router = APIRouter()

# Include all route modules
router.include_router(files_router)
router.include_router(compare_router)
router.include_router(feedback_router)
router.include_router(reports_router)
router.include_router(folder_compare_router)

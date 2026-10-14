"""
NC Code Analyser - Main Application Entry Point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path

from src.core import get_settings, setup_logging, get_logger
from src.api import router as api_router

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Get settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered NC Code Analysis and Regression Detection System",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")

# Frontend paths
frontend_path = Path(__file__).parent.parent / "frontend"
frontend_dist_path = frontend_path / "dist"


@app.get("/")
async def root():
    """Serve the main dashboard."""
    # Try dist folder first (for built frontend)
    index_path = frontend_dist_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    # Try direct frontend folder (for development)
    index_path = frontend_path / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    # Fallback to API info
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/api/docs",
        "status": "running",
        "message": "Frontend not found. Access API docs at /api/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.app_version}


@app.on_event("startup")
async def startup_event():
    """Application startup tasks."""
    logger.info("Starting NC Code Analyser", version=settings.app_version)
    settings.ensure_directories()


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown tasks."""
    logger.info("Shutting down NC Code Analyser")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

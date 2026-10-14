"""
NC Code Analyser - File Management Routes
"""

import os
import hashlib
import uuid
import aiofiles
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse

from src.core import get_settings, get_logger
from src.api.schemas import FileUploadResponse, ParseResponse, OperationSummary
from src.parser import NCParser

router = APIRouter(prefix="/files", tags=["Files"])
logger = get_logger(__name__)
settings = get_settings()

# In-memory file registry (in production, use database)
file_registry: dict = {}


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    is_baseline: bool = Query(False, description="Mark as baseline file"),
):
    """Upload an NC file for analysis."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Validate file extension
    valid_extensions = {'.nc', '.tap', '.gcode', '.ngc', '.cnc', '.txt'}
    ext = Path(file.filename).suffix.lower()
    if ext not in valid_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(valid_extensions)}"
        )

    # Read file content
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # Generate unique file ID
    file_id = str(uuid.uuid4())

    # Determine storage path
    if is_baseline:
        storage_dir = Path(settings.baseline_dir)
    else:
        storage_dir = Path(settings.upload_dir)

    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / f"{file_id}_{file.filename}"

    # Save file
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)

    # Register file
    file_info = {
        "file_id": file_id,
        "file_name": file.filename,
        "file_path": str(file_path),
        "file_hash": file_hash,
        "uploaded_at": datetime.utcnow(),
        "file_size": len(content),
        "is_baseline": is_baseline,
    }
    file_registry[file_id] = file_info

    logger.info("File uploaded", file_id=file_id, filename=file.filename)

    return FileUploadResponse(**file_info)


@router.get("/list")
async def list_files(
    is_baseline: bool = Query(None, description="Filter by baseline status"),
    limit: int = Query(50, ge=1, le=200),
):
    """List uploaded files."""
    files = list(file_registry.values())

    if is_baseline is not None:
        files = [f for f in files if f.get("is_baseline") == is_baseline]

    # Sort by upload time (newest first)
    files.sort(key=lambda x: x.get("uploaded_at", datetime.min), reverse=True)

    return {"files": files[:limit], "total": len(files)}


@router.get("/{file_id}")
async def get_file_info(file_id: str):
    """Get information about an uploaded file."""
    if file_id not in file_registry:
        raise HTTPException(status_code=404, detail="File not found")

    return file_registry[file_id]


@router.get("/{file_id}/download")
async def download_file(file_id: str):
    """Download an uploaded file."""
    if file_id not in file_registry:
        raise HTTPException(status_code=404, detail="File not found")

    file_info = file_registry[file_id]
    file_path = Path(file_info["file_path"])

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists")

    return FileResponse(
        path=str(file_path),
        filename=file_info["file_name"],
        media_type="text/plain",
    )


@router.get("/{file_id}/parse", response_model=ParseResponse)
async def parse_file(file_id: str):
    """Parse an NC file and return structured information."""
    if file_id not in file_registry:
        raise HTTPException(status_code=404, detail="File not found")

    file_info = file_registry[file_id]
    file_path = file_info["file_path"]

    parser = NCParser()
    result = parser.parse_file(file_path)

    if not result.success or not result.program:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse file: {result.errors}"
        )

    program = result.program

    # Build operation summaries
    operations = [
        OperationSummary(
            operation_id=op.operation_id,
            operation_name=op.operation_name,
            tool_number=op.tool.tool_number if op.tool else None,
            start_line=op.start_line,
            end_line=op.end_line,
            command_count=len(op.commands),
        )
        for op in program.operations
    ]

    # Build tool list
    tools = [
        {
            "tool_number": t.tool_number,
            "tool_name": t.tool_name,
            "diameter": t.diameter,
            "length": t.length,
        }
        for t in program.tools_used
    ]

    return ParseResponse(
        file_name=program.file_name,
        program_number=program.program_number,
        program_name=program.program_name,
        machine_type=program.machine_type.value if program.machine_type else None,
        unit_system=program.unit_system.value if program.unit_system else None,
        total_lines=program.total_lines,
        total_operations=program.total_operations,
        total_tools=program.total_tools,
        operations=operations,
        tools=tools,
        parse_time_ms=result.parse_time_ms,
    )


@router.delete("/{file_id}")
async def delete_file(file_id: str):
    """Delete an uploaded file."""
    if file_id not in file_registry:
        raise HTTPException(status_code=404, detail="File not found")

    file_info = file_registry[file_id]
    file_path = Path(file_info["file_path"])

    # Delete physical file
    if file_path.exists():
        file_path.unlink()

    # Remove from registry
    del file_registry[file_id]

    logger.info("File deleted", file_id=file_id)

    return {"message": "File deleted successfully", "file_id": file_id}


@router.post("/upload-baseline", response_model=FileUploadResponse)
async def upload_baseline(file: UploadFile = File(...)):
    """Upload a baseline NC file."""
    return await upload_file(file, is_baseline=True)

"""Streaming ASR API routes."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from .streaming_asr import get_streaming_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/streaming", tags=["streaming"])


@router.post("/start")
async def start_session(
    language: Optional[str] = None,
    chunk_size_sec: float = 1.0,
):
    """
    Initialize a new streaming ASR session.

    Returns:
        {"session_id": "uuid-string"}
    """
    if chunk_size_sec <= 0 or chunk_size_sec > 10:
        raise HTTPException(status_code=400, detail="chunk_size_sec must be between 0 and 10")

    manager = get_streaming_manager()
    session_id = manager.start_session(
        language=language,
        chunk_size_sec=chunk_size_sec,
    )
    return {"session_id": session_id}


@router.post("/chunk")
async def send_chunk(
    request: Request,
    session_id: str = Query(...),
):
    """
    Send an audio chunk to a streaming session.

    Audio format: 16kHz mono float32 PCM binary body.

    Returns:
        {"text": "current transcription"}
    """
    # Read raw body
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty audio data")

    # Validate audio size (at most 10 seconds of audio per chunk)
    expected_samples = int(16000 * 10)
    max_bytes = expected_samples * 4  # float32 = 4 bytes
    if len(body) > max_bytes:
        raise HTTPException(status_code=400, detail="Chunk too large (max 10s of audio)")

    manager = get_streaming_manager()
    try:
        text = manager.process_chunk(session_id, body)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"text": text}


@router.post("/finish")
async def finish_session(
    session_id: str = Query(...),
):
    """
    Finish a streaming session and get final transcription.

    Returns:
        {"text": "final transcription", "session_id": "uuid"}
    """
    manager = get_streaming_manager()
    try:
        text = manager.finish_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"text": text, "session_id": session_id}


@router.get("/status/{session_id}")
async def get_status(session_id: str):
    """
    Get the status of a streaming session.

    Returns:
        Session info dict or 404.
    """
    manager = get_streaming_manager()
    status = manager.get_status(session_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return status


@router.post("/cancel/{session_id}")
async def cancel_session(session_id: str):
    """
    Cancel a streaming session.

    Returns:
        {"cancelled": true/false}
    """
    manager = get_streaming_manager()
    cancelled = manager.cancel_session(session_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"cancelled": True}

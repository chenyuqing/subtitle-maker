"""Streaming ASR service with session management (transformers backend)."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional

import numpy as np
import torch

from qwen_asr import Qwen3ASRModel

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SESSION_TTL_SECONDS = 600  # 10 minutes


class SessionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class StreamingSession:
    """Streaming ASR session state."""
    session_id: str
    status: SessionStatus
    created_at: float
    language: Optional[str]
    chunk_size_sec: float
    # Transformers model instance
    model: Qwen3ASRModel
    # Buffered audio samples (float32)
    audio_buffer: np.ndarray = field(default_factory=lambda: np.zeros((0,), dtype=np.float32))
    # Accumulated transcription
    full_text: str = ""
    # Chunk index for logging
    chunk_count: int = 0
    last_update: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return time.time() - self.created_at > SESSION_TTL_SECONDS


class StreamingSessionManager:
    """
    Manages streaming ASR sessions with TTL-based cleanup.
    Uses transformers backend (no vLLM required, works on macOS).
    """

    def __init__(self):
        self._sessions: Dict[str, StreamingSession] = {}
        self._lock = Lock()
        self._model = None
        self._model_lock = Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    def _get_model(self) -> Qwen3ASRModel:
        """Lazy load the ASR model (thread-safe)."""
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            logger.info("Loading ASR model for streaming (transformers backend)...")
            self._model = Qwen3ASRModel.from_pretrained(
                "./models/Qwen3-ASR-0.6B",
                dtype=torch.float16,
                device_map="mps",
                forced_aligner="./models/Qwen3-ForcedAligner-0.6B",
                forced_aligner_kwargs=dict(dtype=torch.float16, device_map="mps"),
            )
            logger.info("ASR model loaded.")
            return self._model

    def start_session(
        self,
        language: Optional[str] = None,
        chunk_size_sec: float = 1.0,
    ) -> str:
        """
        Create a new streaming session.

        Args:
            language: Optional forced language (e.g., "Chinese", "English").
            chunk_size_sec: Audio chunk size in seconds (used for buffering).

        Returns:
            session_id: UUID string for the session.
        """
        model = self._get_model()
        session_id = str(uuid.uuid4())

        session = StreamingSession(
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            created_at=time.time(),
            language=language,
            chunk_size_sec=chunk_size_sec,
            model=model,
        )

        with self._lock:
            self._sessions[session_id] = session

        logger.info(f"Started streaming session {session_id} (lang={language}, chunk={chunk_size_sec}s)")
        return session_id

    def process_chunk(self, session_id: str, audio_data: bytes) -> str:
        """
        Process an audio chunk for a session.

        Args:
            session_id: Session UUID.
            audio_data: Binary float32 PCM audio (16kHz mono).

        Returns:
            Current transcription text.

        Raises:
            ValueError: If session not found or expired.
        """
        with self._lock:
            session = self._sessions.get(session_id)

        if session is None:
            raise ValueError(f"Session {session_id} not found")

        if session.status != SessionStatus.ACTIVE:
            raise ValueError(f"Session {session_id} is {session.status.value}, cannot process chunk")

        if session.is_expired():
            session.status = SessionStatus.EXPIRED
            raise ValueError(f"Session {session_id} has expired")

        # Convert bytes to numpy array
        audio_np = np.frombuffer(audio_data, dtype=np.float32)
        session.chunk_count += 1

        # Transcribe this chunk (transformers backend: batched transcription)
        lang_arg = session.language if session.language else None
        with self._model_lock:
            results = session.model.transcribe(
                audio=(audio_np, SAMPLE_RATE),
                language=lang_arg,
                return_time_stamps=False,
            )

        chunk_text = results[0].text if results else ""

        # Append to accumulated text
        if chunk_text:
            if session.full_text:
                session.full_text += " " + chunk_text
            else:
                session.full_text = chunk_text

        session.last_update = time.time()
        return session.full_text

    def finish_session(self, session_id: str) -> str:
        """
        Finish a streaming session and return final transcription.

        Args:
            session_id: Session UUID.

        Returns:
            Final transcription text.

        Raises:
            ValueError: If session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)

        if session is None:
            raise ValueError(f"Session {session_id} not found")

        if session.status == SessionStatus.FINISHED:
            return session.full_text

        if session.status == SessionStatus.CANCELLED:
            raise ValueError(f"Session {session_id} was cancelled")

        session.status = SessionStatus.FINISHED
        session.last_update = time.time()

        logger.info(f"Finished streaming session {session_id}: '{session.full_text[:50]}...' ({session.chunk_count} chunks)")
        return session.full_text

    def cancel_session(self, session_id: str) -> bool:
        """
        Cancel a streaming session.

        Args:
            session_id: Session UUID.

        Returns:
            True if cancelled, False if not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            session.status = SessionStatus.CANCELLED
            return True

    def get_status(self, session_id: str) -> Optional[Dict]:
        """
        Get session status.

        Args:
            session_id: Session UUID.

        Returns:
            Dict with session info or None if not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

        return {
            "session_id": session.session_id,
            "status": session.status.value,
            "language": session.language,
            "full_text": session.full_text,
            "chunk_count": session.chunk_count,
            "created_at": session.created_at,
            "last_update": session.last_update,
            "is_expired": session.is_expired(),
        }

    def cleanup_expired(self) -> int:
        """
        Remove expired sessions.

        Returns:
            Number of sessions removed.
        """
        removed = 0
        with self._lock:
            expired_ids = [
                sid for sid, sess in self._sessions.items()
                if sess.is_expired()
            ]
            for sid in expired_ids:
                del self._sessions[sid]
                removed += 1

        if removed:
            logger.info(f"Cleaned up {removed} expired streaming sessions")

        return removed

    def start_cleanup_task(self):
        """Start background cleanup task (idempotent)."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return

        async def _cleanup_loop():
            while True:
                await asyncio.sleep(60)
                self.cleanup_expired()

        self._cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info("Started session cleanup background task")


# Global singleton
_manager: Optional[StreamingSessionManager] = None
_manager_lock = Lock()


def get_streaming_manager() -> StreamingSessionManager:
    """Get the global StreamingSessionManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = StreamingSessionManager()
                _manager.start_cleanup_task()
    return _manager

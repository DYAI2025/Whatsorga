"""Audio transcription with Groq Whisper (primary) and Ollama (fallback)."""

import base64
import logging
import tempfile
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


async def transcribe_audio(audio_base64: str) -> str | None:
    """Transcribe audio from base64. Try Groq first, then Ollama."""
    audio_bytes = base64.b64decode(audio_base64)

    # Try Groq Whisper first
    if settings.groq_api_key:
        result = await _transcribe_groq(audio_bytes)
        if result:
            return result
        logger.warning("Groq transcription failed, trying Ollama fallback")

    # Fallback to Ollama
    result = await _transcribe_ollama(audio_bytes)
    if result:
        return result

    logger.error("All transcription methods failed")
    return None


async def _transcribe_groq(audio_bytes: bytes) -> str | None:
    """Transcribe via Groq Whisper API."""
    try:
        # Write to temp file (Groq needs file upload)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = Path(f.name)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GROQ_WHISPER_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                files={"file": ("audio.ogg", tmp_path.read_bytes(), "audio/ogg")},
                data={
                    "model": settings.groq_whisper_model,
                    "language": "de",
                    "response_format": "text",
                },
            )

        tmp_path.unlink(missing_ok=True)

        if response.status_code == 200:
            text = response.text.strip()
            if text:
                logger.info(f"Groq transcription: {len(text)} chars")
                return text
        else:
            logger.warning(f"Groq API error: {response.status_code} {response.text[:200]}")

    except Exception as e:
        logger.warning(f"Groq transcription error: {e}")

    return None


async def _transcribe_ollama(audio_bytes: bytes) -> str | None:
    """Transcribe via Ollama (if whisper model available)."""
    try:
        # Ollama doesn't natively support whisper-style transcription via REST.
        # This is a placeholder for when Ollama adds audio model support,
        # or for using a local whisper binary via subprocess.
        logger.info("Ollama audio fallback not yet implemented")
        return None
    except Exception as e:
        logger.warning(f"Ollama transcription error: {e}")
        return None

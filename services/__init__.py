"""Service layer package for the AibaTS desktop tool.

Modules will include configuration loading, logging setup, storage path
utilities, and later pluggable implementations for recording and
transcription backends.
"""

from services.transcribe import (
    ITranscriptionBackend,
    TranscriptionUnavailable,
    get_backend as get_transcription_backend,
)

__all__ = [
    "ITranscriptionBackend",
    "TranscriptionUnavailable",
    "get_transcription_backend",
]



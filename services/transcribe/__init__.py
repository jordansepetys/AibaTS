from typing import Literal

from services.transcribe.base import ITranscriptionBackend, TranscriptionUnavailable
from services.transcribe.openai_backend import OpenAITranscriptionBackend


def get_backend(name: Literal["openai"] = "openai") -> ITranscriptionBackend:
    if name == "openai":
        return OpenAITranscriptionBackend()
    raise ValueError(f"Unknown transcription backend: {name}")

__all__ = [
    "ITranscriptionBackend",
    "TranscriptionUnavailable",
    "get_backend",
]










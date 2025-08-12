"""Base classes and interfaces for transcription backends."""

from abc import ABC, abstractmethod


class TranscriptionUnavailable(Exception):
    """Raised when transcription service is unavailable (e.g., no API key)."""
    pass


class ITranscriptionBackend(ABC):
    """Interface for transcription backends."""
    
    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio file to text.
        
        Args:
            audio_path: Path to the audio file to transcribe
            
        Returns:
            Transcribed text
            
        Raises:
            TranscriptionUnavailable: If the service is unavailable
            Exception: For other transcription errors
        """
        pass

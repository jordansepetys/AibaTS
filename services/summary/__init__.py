"""Summary generation service with multiple backend support."""

from typing import Literal
from loguru import logger

from services.config import load_config
from services.summary.base import ISummaryBackend, SummaryUnavailable, MeetingSummary


def get_backend(name: Literal["claude", "openai"] = "claude") -> ISummaryBackend:
    """Get a summary backend by name."""
    if name == "claude":
        from services.summary.claude_backend import ClaudeSummaryBackend
        return ClaudeSummaryBackend()
    elif name == "openai":
        from services.summary.openai_backend import OpenAISummaryBackend
        return OpenAISummaryBackend()
    raise ValueError(f"Unknown summary backend: {name}")


class SummaryGenerator:
    """Main summary generator with backend fallback support."""
    
    def __init__(self) -> None:
        self._config = load_config()

    def generate(self, transcript_text: str) -> MeetingSummary:
        """Generate a structured summary with fallback support."""
        if not transcript_text.strip():
            return MeetingSummary.empty()

        # Try primary backend first
        primary_backend = self._config.suggestion_backend  # Reuse the same backend preference
        logger.info(f"Attempting summary with {primary_backend} backend")
        
        try:
            backend = get_backend(primary_backend)
            return backend.generate(transcript_text)
        except SummaryUnavailable as e:
            logger.warning(f"{primary_backend} summary backend unavailable: {e}")
        except Exception as e:
            logger.error(f"{primary_backend} summary backend failed: {e}")

        # Fallback logic: try the other backend
        fallback_backend = "openai" if primary_backend == "claude" else "claude"
        logger.info(f"Falling back to {fallback_backend} backend for summary")
        
        try:
            backend = get_backend(fallback_backend)
            return backend.generate(transcript_text)
        except SummaryUnavailable as e:
            logger.warning(f"{fallback_backend} summary backend also unavailable: {e}")
            raise SummaryUnavailable(f"Both {primary_backend} and {fallback_backend} summary backends unavailable")
        except Exception as e:
            logger.error(f"{fallback_backend} summary backend also failed: {e}")
            raise Exception(f"Both {primary_backend} and {fallback_backend} summary backends failed")


__all__ = [
    "ISummaryBackend",
    "SummaryUnavailable", 
    "MeetingSummary",
    "SummaryGenerator",
    "get_backend",
]

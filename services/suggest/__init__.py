from typing import Literal
from loguru import logger

from services.config import load_config
from services.suggest.base import ISuggestionBackend, SuggestionUnavailable, MeetingSuggestions
from services.suggest.claude_backend import ClaudeSuggestionBackend
from services.suggest.openai_backend import OpenAISuggestionBackend


def get_backend(name: Literal["claude", "openai"] = "claude") -> ISuggestionBackend:
    """Get a suggestion backend by name.
    
    Args:
        name: Backend name - "claude" or "openai"
        
    Returns:
        Configured suggestion backend
        
    Raises:
        ValueError: If backend name is unknown
    """
    if name == "claude":
        return ClaudeSuggestionBackend()
    elif name == "openai":
        return OpenAISuggestionBackend()
    raise ValueError(f"Unknown suggestion backend: {name}")


class SuggestionGenerator:
    """Main suggestion generator with backend fallback support."""
    
    def __init__(self) -> None:
        self._config = load_config()

    def generate(self, transcript_text: str) -> MeetingSuggestions:
        if not transcript_text.strip():
            return MeetingSuggestions.empty()

        # Try primary backend first
        primary_backend = self._config.suggestion_backend
        logger.info(f"Attempting suggestions with {primary_backend} backend")
        
        try:
            backend = get_backend(primary_backend)
            return backend.generate(transcript_text)
        except SuggestionUnavailable as e:
            logger.warning(f"{primary_backend} backend unavailable: {e}")
        except Exception as e:
            logger.error(f"{primary_backend} backend failed: {e}")

        # Fallback logic: try the other backend
        fallback_backend = "openai" if primary_backend == "claude" else "claude"
        logger.info(f"Falling back to {fallback_backend} backend")
        
        try:
            backend = get_backend(fallback_backend)
            return backend.generate(transcript_text)
        except SuggestionUnavailable as e:
            logger.warning(f"{fallback_backend} backend also unavailable: {e}")
            raise SuggestionUnavailable(f"Both {primary_backend} and {fallback_backend} backends unavailable")
        except Exception as e:
            logger.error(f"{fallback_backend} backend also failed: {e}")
            raise Exception(f"Both {primary_backend} and {fallback_backend} backends failed")


__all__ = [
    "ISuggestionBackend",
    "SuggestionUnavailable", 
    "MeetingSuggestions",
    "SuggestionGenerator",
    "get_backend",
]

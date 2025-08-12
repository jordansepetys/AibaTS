"""Base classes and interfaces for suggestion backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


class SuggestionUnavailable(Exception):
    """Raised when suggestion service is unavailable (e.g., no API key)."""
    pass


@dataclass
class MeetingSuggestions:
    recap: str
    decisions: List[str]
    actions: List[str]
    risks: List[str]
    open_questions: List[str]

    @staticmethod
    def empty() -> "MeetingSuggestions":
        return MeetingSuggestions(recap="", decisions=[], actions=[], risks=[], open_questions=[])


class ISuggestionBackend(ABC):
    """Interface for suggestion backends."""
    
    @abstractmethod
    def generate(self, transcript_text: str) -> MeetingSuggestions:
        """Generate meeting suggestions from transcript.
        
        Args:
            transcript_text: The meeting transcript text
            
        Returns:
            MeetingSuggestions object with structured meeting insights
            
        Raises:
            SuggestionUnavailable: If the service is unavailable
            Exception: For other suggestion generation errors
        """
        pass

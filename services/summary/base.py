"""Base classes and interfaces for summary backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SummaryUnavailable(Exception):
    """Raised when summary service is unavailable (e.g., no API key)."""
    pass


@dataclass
class MeetingSummary:
    """Structured meeting summary data."""
    overview: str
    decisions: list[str]
    action_items: list[str]
    topics: list[str]
    unresolved: list[str]
    
    def to_markdown(self) -> str:
        """Convert the summary to formatted markdown."""
        sections = []
        
        if self.overview:
            sections.append(f"## Overview\n\n{self.overview}")
        
        if self.decisions:
            sections.append("## Key Decisions\n\n" + "\n".join(f"- {decision}" for decision in self.decisions))
        
        if self.action_items:
            sections.append("## Action Items\n\n" + "\n".join(f"- {item}" for item in self.action_items))
        
        if self.topics:
            sections.append("## Important Topics Discussed\n\n" + "\n".join(f"- {topic}" for topic in self.topics))
        
        if self.unresolved:
            sections.append("## Unresolved Questions/Issues\n\n" + "\n".join(f"- {item}" for item in self.unresolved))
        
        return "\n\n".join(sections)
    
    @staticmethod
    def empty() -> "MeetingSummary":
        """Return an empty summary."""
        return MeetingSummary(
            overview="",
            decisions=[],
            action_items=[],
            topics=[],
            unresolved=[]
        )


class ISummaryBackend(ABC):
    """Interface for summary backends."""
    
    @abstractmethod
    def generate(self, transcript_text: str) -> MeetingSummary:
        """Generate a structured summary from transcript.
        
        Args:
            transcript_text: The meeting transcript text
            
        Returns:
            MeetingSummary object with structured meeting summary
            
        Raises:
            SummaryUnavailable: If the service is unavailable
            Exception: For other summary generation errors
        """
        pass


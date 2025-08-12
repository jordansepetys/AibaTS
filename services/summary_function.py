"""Standalone function for generating structured summaries from transcripts."""

from services.summary import SummaryGenerator, SummaryUnavailable
from loguru import logger


def generate_structured_summary(transcript_text: str) -> str:
    """
    Generate a structured summary from a meeting transcript.
    
    This function takes a transcript and uses the configured AI service 
    (Claude by default, with OpenAI fallback) to process the transcript 
    with the following analysis:
    
    1. A brief 2-3 sentence overview
    2. List of key decisions made (bullet points)
    3. List of action items with assignees if mentioned
    4. Important topics discussed
    5. Any questions or issues that remain unresolved
    
    Args:
        transcript_text (str): The meeting transcript text to analyze
        
    Returns:
        str: Formatted markdown text with the structured summary
        
    Raises:
        ValueError: If transcript is empty or invalid
        Exception: If summary generation fails completely
        
    Example:
        >>> transcript = "We discussed the Q4 budget. John will prepare the report by Friday..."
        >>> summary = generate_structured_summary(transcript)
        >>> print(summary)
        ## Overview
        
        The meeting focused on Q4 budget planning and resource allocation...
        
        ## Key Decisions
        
        - Approved Q4 budget proposal
        
        ## Action Items
        
        - John will prepare the budget report (due Friday)
        ...
    """
    if not transcript_text or not transcript_text.strip():
        raise ValueError("Transcript text cannot be empty")
    
    try:
        # Use the summary generator with fallback support
        generator = SummaryGenerator()
        summary = generator.generate(transcript_text)
        
        # Convert to formatted markdown
        markdown_output = summary.to_markdown()
        
        if not markdown_output.strip():
            logger.warning("Generated summary is empty")
            return "## Summary\n\nNo significant content found in the transcript."
        
        return markdown_output
        
    except SummaryUnavailable as e:
        logger.error(f"Summary service unavailable: {e}")
        raise Exception(f"Summary generation unavailable: {e}")
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        raise Exception(f"Failed to generate summary: {e}")


# Convenience alias for the main function
def generate_meeting_summary(transcript: str) -> str:
    """Alias for generate_structured_summary for convenience."""
    return generate_structured_summary(transcript)

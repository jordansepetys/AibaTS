"""Wiki updater functionality for adding meeting entries to project wikis."""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from services.project_manager import project_manager
from services.summary_function import generate_structured_summary


def updateProjectWiki(
    project_name: str,
    meeting_name: str,
    transcript_text: str,
    duration_minutes: Optional[int] = None,
    transcript_file_path: Optional[str] = None,
    meeting_date: Optional[str] = None
) -> bool:
    """
    Update the project wiki with a new meeting entry.
    
    Args:
        project_name: Name of the project
        meeting_name: Name/title of the meeting
        transcript_text: Full transcript text
        duration_minutes: Meeting duration in minutes (optional)
        transcript_file_path: Path to the JSON transcript file (optional)
        meeting_date: Meeting date in YYYY-MM-DD format (defaults to today)
        
    Returns:
        bool: True if update was successful, False otherwise
        
    Format:
        ### [Date] - [Meeting Name]
        **Duration:** [X] minutes
        **Transcript File:** [Link to JSON file]
        
        #### Summary
        [AI generated summary]
        
        #### Full Transcript
        <details>
        <summary>Click to expand transcript</summary>
        
        [Full transcript text]
        
        </details>
        
        ---
    """
    try:
        # Ensure project structure exists
        project_manager.ensure_project_structure(project_name)
        
        # Get wiki path
        wiki_path = project_manager.get_project_wiki_path(project_name)
        
        # Use provided date or default to today
        if not meeting_date:
            meeting_date = datetime.now().strftime("%Y-%m-%d")
        
        # Generate AI summary
        logger.info(f"Generating summary for meeting: {meeting_name}")
        try:
            ai_summary = generate_structured_summary(transcript_text)
        except Exception as e:
            logger.warning(f"Failed to generate AI summary: {e}")
            ai_summary = "Summary generation failed. Please check the logs."
        
        # Read current wiki content
        if wiki_path.exists():
            content = wiki_path.read_text(encoding="utf-8")
        else:
            # This shouldn't happen since ensure_project_structure creates it
            content = f"# {project_name} Project Wiki\n\n## Meeting History\n\n---\n"
        
        # Create the new meeting entry
        entry_parts = []
        entry_parts.append(f"### {meeting_date} - {meeting_name}")
        
        # Add duration if provided
        if duration_minutes is not None:
            entry_parts.append(f"**Duration:** {duration_minutes} minutes")
        
        # Add transcript file link if provided
        if transcript_file_path:
            # Make path relative if it's absolute and within the project
            rel_path = transcript_file_path
            try:
                if Path(transcript_file_path).is_absolute():
                    rel_path = str(Path(transcript_file_path).relative_to(Path.cwd()))
            except ValueError:
                # Path is not relative to current directory, keep as is
                pass
            entry_parts.append(f"**Transcript File:** [{Path(rel_path).name}]({rel_path})")
        
        entry_parts.append("")  # Empty line
        entry_parts.append("#### Summary")
        entry_parts.append(ai_summary)
        entry_parts.append("")  # Empty line
        entry_parts.append("#### Full Transcript")
        entry_parts.append("<details>")
        entry_parts.append("<summary>Click to expand transcript</summary>")
        entry_parts.append("")
        entry_parts.append(transcript_text)
        entry_parts.append("")
        entry_parts.append("</details>")
        entry_parts.append("")
        entry_parts.append("---")
        entry_parts.append("")  # Empty line after separator
        
        new_entry = "\n".join(entry_parts)
        
        # Find the Meeting History section and prepend the new entry
        updated_content = _prepend_to_meeting_history(content, new_entry)
        
        # Write the updated content back to the wiki
        wiki_path.write_text(updated_content, encoding="utf-8")
        
        logger.info(f"Successfully updated project wiki: {wiki_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update project wiki for {project_name}: {e}")
        return False


def _prepend_to_meeting_history(content: str, new_entry: str) -> str:
    """
    Prepend a new meeting entry to the Meeting History section of the wiki.
    
    Args:
        content: Current wiki content
        new_entry: New meeting entry to prepend
        
    Returns:
        Updated wiki content with new entry at the top of Meeting History
    """
    lines = content.split('\n')
    
    # Find the Meeting History section
    meeting_history_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Meeting History":
            meeting_history_idx = i
            break
    
    if meeting_history_idx is None:
        # Meeting History section not found, add it
        logger.warning("Meeting History section not found, adding it")
        content += "\n\n## Meeting History\n\n---\n"
        lines = content.split('\n')
        meeting_history_idx = len(lines) - 3  # Point to the "## Meeting History" line
    
    # Find where to insert the new entry
    # Look for the first content after "## Meeting History" (skip empty lines and "---")
    insert_idx = meeting_history_idx + 1
    
    # Skip any empty lines or horizontal rules immediately after the header
    while insert_idx < len(lines):
        line = lines[insert_idx].strip()
        if line == "" or line == "---":
            insert_idx += 1
        else:
            break
    
    # If we're at the end or the next line doesn't start with "###", 
    # we need to insert our entry here
    new_lines = lines[:insert_idx] + new_entry.split('\n') + lines[insert_idx:]
    
    return '\n'.join(new_lines)


def get_meeting_duration_minutes(start_time: datetime, end_time: datetime) -> int:
    """Calculate meeting duration in minutes from start and end times."""
    duration = end_time - start_time
    return int(duration.total_seconds() / 60)


def format_transcript_for_wiki(transcript_text: str, max_length: int = 10000) -> str:
    """
    Format transcript text for inclusion in wiki.
    
    Args:
        transcript_text: Raw transcript text
        max_length: Maximum length of transcript to include
        
    Returns:
        Formatted transcript text
    """
    # Clean up the transcript
    cleaned = transcript_text.strip()
    
    # If transcript is too long, truncate with message
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "\n\n[Transcript truncated - see full transcript file for complete content]"
    
    return cleaned

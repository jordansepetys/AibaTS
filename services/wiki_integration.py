"""Integration layer for wiki updates with the main application workflow."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from services.wiki_updater import updateProjectWiki
from services.history import MeetingRecord


def update_project_wiki_from_meeting(
    meeting_record: MeetingRecord,
    transcript_text: str,
    duration_minutes: Optional[int] = None
) -> bool:
    """
    Update project wiki from a meeting record and transcript.
    
    Args:
        meeting_record: Meeting record with metadata
        transcript_text: Full transcript text
        duration_minutes: Meeting duration in minutes
        
    Returns:
        bool: True if update was successful, False otherwise
    """
    try:
        # Extract date from meeting record (format: "YYYY-MM-DD HH:MM")
        meeting_date = meeting_record.date.split(" ")[0] if " " in meeting_record.date else meeting_record.date
        
        # Use JSON notes path if available, otherwise transcript path
        transcript_file_path = meeting_record.json_notes_path or meeting_record.transcript_path
        
        return updateProjectWiki(
            project_name=meeting_record.project_name,
            meeting_name=meeting_record.name,
            transcript_text=transcript_text,
            duration_minutes=duration_minutes,
            transcript_file_path=transcript_file_path,
            meeting_date=meeting_date
        )
        
    except Exception as e:
        logger.error(f"Failed to update project wiki from meeting record: {e}")
        return False


def update_project_wiki_simple(
    project_name: str,
    meeting_name: str,
    transcript_text: str,
    transcript_file_path: Optional[str] = None
) -> bool:
    """
    Simple wiki update for current meeting workflow.
    
    Args:
        project_name: Name of the project
        meeting_name: Name/title of the meeting
        transcript_text: Full transcript text
        transcript_file_path: Path to transcript file (optional)
        
    Returns:
        bool: True if update was successful, False otherwise
    """
    return updateProjectWiki(
        project_name=project_name,
        meeting_name=meeting_name,
        transcript_text=transcript_text,
        transcript_file_path=transcript_file_path
    )




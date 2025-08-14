"""
Meeting Index System for searchable meeting records.

Builds and maintains a searchable index of all meetings in a project,
including metadata, decisions, action items, and full transcript content.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from loguru import logger

from services.project_manager import project_manager


@dataclass
class MeetingIndexEntry:
    """Single meeting entry in the search index."""
    meeting_id: str
    timestamp: int
    date: str  # YYYY-MM-DD format
    meeting_name: str
    duration_minutes: Optional[int]
    project_name: str
    
    # Content for searching
    decisions: List[str]
    action_items: List[str]
    risks: List[str]
    open_questions: List[str]
    full_transcript: str
    
    # File paths
    json_file_path: str
    transcript_file_path: Optional[str]
    
    # Search metadata
    word_count: int
    keywords: List[str]
    
    @classmethod
    def from_meeting_data(cls, meeting_id: str, project_name: str, 
                         json_file_path: str, transcript_file_path: Optional[str] = None) -> "MeetingIndexEntry":
        """Create index entry from meeting files."""
        
        # Extract timestamp from meeting ID
        timestamp_str = meeting_id.replace("meeting_", "").replace("_notes", "")
        timestamp = int(timestamp_str) if timestamp_str.isdigit() else 0
        
        # Convert timestamp to date
        if timestamp > 0:
            date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        else:
            date = "unknown"
        
        # Load and parse JSON data
        decisions, action_items, risks, open_questions = [], [], [], []
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle different JSON formats
            if "error" in data and "raw_output" in data:
                # Parse from raw_output containing JSON in markdown code block
                raw = data["raw_output"]
                json_match = re.search(r'```json\s*\n(.*?)\n```', raw, re.DOTALL)
                if json_match:
                    parsed_data = json.loads(json_match.group(1))
                    decisions = parsed_data.get("decisions", [])
                    action_items = parsed_data.get("action_items", [])
                    risks = parsed_data.get("risks", [])
                    open_questions = parsed_data.get("open_questions", [])
            else:
                # Direct JSON format
                decisions = data.get("decisions", [])
                action_items = data.get("action_items", [])
                risks = data.get("risks", [])
                open_questions = data.get("open_questions", [])
                
        except Exception as e:
            logger.warning(f"Failed to parse meeting JSON {json_file_path}: {e}")
        
        # Load transcript
        full_transcript = ""
        if transcript_file_path and Path(transcript_file_path).exists():
            try:
                with open(transcript_file_path, 'r', encoding='utf-8') as f:
                    full_transcript = f.read().strip()
            except Exception as e:
                logger.warning(f"Failed to read transcript {transcript_file_path}: {e}")
        
        # Generate meeting name from timestamp or use default
        if timestamp > 0:
            meeting_name = f"Meeting {datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')}"
        else:
            meeting_name = f"Meeting {meeting_id}"
        
        # Calculate word count and extract keywords
        all_text = " ".join([
            meeting_name,
            " ".join(decisions),
            " ".join(action_items), 
            " ".join(risks),
            " ".join(open_questions),
            full_transcript
        ])
        
        word_count = len(all_text.split())
        keywords = cls._extract_keywords(all_text)
        
        return cls(
            meeting_id=meeting_id,
            timestamp=timestamp,
            date=date,
            meeting_name=meeting_name,
            duration_minutes=None,  # Will be calculated if possible
            project_name=project_name,
            decisions=decisions,
            action_items=action_items,
            risks=risks,
            open_questions=open_questions,
            full_transcript=full_transcript,
            json_file_path=str(json_file_path),
            transcript_file_path=str(transcript_file_path) if transcript_file_path else None,
            word_count=word_count,
            keywords=keywords
        )
    
    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 20) -> List[str]:
        """Extract important keywords from text."""
        # Simple keyword extraction - can be enhanced with NLP libraries
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # Common stop words to exclude
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one',
            'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old',
            'see', 'two', 'who', 'boy', 'did', 'man', 'way', 'she', 'been', 'call', 'come', 'each',
            'find', 'give', 'hand', 'have', 'here', 'keep', 'last', 'left', 'life', 'live', 'look',
            'made', 'make', 'most', 'move', 'must', 'name', 'need', 'open', 'over', 'part', 'play',
            'put', 'said', 'same', 'seem', 'show', 'side', 'take', 'tell', 'turn', 'want', 'well',
            'went', 'were', 'what', 'when', 'will', 'with', 'word', 'work', 'year', 'think', 'know',
            'time', 'would', 'there', 'could', 'should', 'going', 'like', 'that', 'this', 'they',
            'just', 'about', 'really', 'actually', 'yeah', 'okay', 'right', 'thing', 'things'
        }
        
        # Filter and count words
        word_freq = {}
        for word in words:
            if word not in stop_words and len(word) > 2:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # Return top keywords
        return sorted(word_freq.keys(), key=lambda w: word_freq[w], reverse=True)[:max_keywords]


@dataclass 
class MeetingIndex:
    """Complete searchable index for a project's meetings."""
    project_name: str
    created_at: str
    updated_at: str
    total_meetings: int
    meetings: List[MeetingIndexEntry]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "project_name": self.project_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_meetings": self.total_meetings,
            "meetings": [asdict(meeting) for meeting in self.meetings]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeetingIndex":
        """Create from dictionary loaded from JSON."""
        meetings = [
            MeetingIndexEntry(**meeting_data) 
            for meeting_data in data.get("meetings", [])
        ]
        
        return cls(
            project_name=data.get("project_name", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            total_meetings=data.get("total_meetings", 0),
            meetings=meetings
        )


class MeetingIndexBuilder:
    """Builds and maintains meeting search indexes."""
    
    def __init__(self):
        self.base_meetings_dir = Path("meeting_data_v2")
        self.json_notes_dir = self.base_meetings_dir / "json_notes"
        self.transcripts_dir = self.base_meetings_dir / "transcripts"
    
    def build_project_index(self, project_name: str, force_rebuild: bool = False) -> MeetingIndex:
        """Build complete index for a project.
        
        Args:
            project_name: Name of the project
            force_rebuild: If True, rebuild entire index. If False, update incrementally.
        
        Returns:
            Complete meeting index
        """
        logger.info(f"Building meeting index for project: {project_name}")
        
        # Ensure project structure exists
        project_manager.ensure_project_structure(project_name)
        
        # Check for existing index
        index_path = self._get_index_path(project_name)
        existing_index = None
        
        if not force_rebuild and index_path.exists():
            try:
                existing_index = self._load_index(index_path)
                logger.info(f"Loaded existing index with {len(existing_index.meetings)} meetings")
            except Exception as e:
                logger.warning(f"Failed to load existing index: {e}")
        
        # Scan for all meeting files
        meeting_files = self._scan_meeting_files()
        logger.info(f"Found {len(meeting_files)} meeting files")
        
        # Build new index entries
        new_meetings = []
        existing_meeting_ids = set()
        
        if existing_index:
            existing_meeting_ids = {m.meeting_id for m in existing_index.meetings}
            new_meetings = existing_index.meetings.copy()
        
        # Process new/updated meetings
        added_count = 0
        for meeting_id, json_path in meeting_files.items():
            if meeting_id not in existing_meeting_ids:
                transcript_path = self._find_transcript_path(meeting_id)
                
                try:
                    entry = MeetingIndexEntry.from_meeting_data(
                        meeting_id=meeting_id,
                        project_name=project_name,
                        json_file_path=str(json_path),
                        transcript_file_path=str(transcript_path) if transcript_path else None
                    )
                    new_meetings.append(entry)
                    added_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to process meeting {meeting_id}: {e}")
        
        # Sort meetings by timestamp (newest first)
        new_meetings.sort(key=lambda m: m.timestamp, reverse=True)
        
        # Create updated index
        now = datetime.now().isoformat()
        created_at = existing_index.created_at if existing_index else now
        
        index = MeetingIndex(
            project_name=project_name,
            created_at=created_at,
            updated_at=now,
            total_meetings=len(new_meetings),
            meetings=new_meetings
        )
        
        # Save index
        self._save_index(index, index_path)
        
        logger.info(f"Index updated: {added_count} new meetings, {len(new_meetings)} total")
        return index
    
    def update_index_with_meeting(self, project_name: str, meeting_id: str, 
                                 json_file_path: str, transcript_file_path: Optional[str] = None) -> None:
        """Add or update a single meeting in the index.
        
        Args:
            project_name: Name of the project
            meeting_id: ID of the meeting
            json_file_path: Path to the meeting JSON file
            transcript_file_path: Path to the transcript file (optional)
        """
        logger.info(f"Updating index with meeting: {meeting_id}")
        
        # Load existing index or create new one
        index_path = self._get_index_path(project_name)
        index = None
        
        if index_path.exists():
            try:
                index = self._load_index(index_path)
            except Exception as e:
                logger.warning(f"Failed to load existing index: {e}")
        
        if not index:
            # Create new index
            now = datetime.now().isoformat()
            index = MeetingIndex(
                project_name=project_name,
                created_at=now,
                updated_at=now,
                total_meetings=0,
                meetings=[]
            )
        
        # Remove existing entry if it exists
        index.meetings = [m for m in index.meetings if m.meeting_id != meeting_id]
        
        # Create new entry
        try:
            entry = MeetingIndexEntry.from_meeting_data(
                meeting_id=meeting_id,
                project_name=project_name,
                json_file_path=json_file_path,
                transcript_file_path=transcript_file_path
            )
            
            index.meetings.append(entry)
            index.meetings.sort(key=lambda m: m.timestamp, reverse=True)
            index.total_meetings = len(index.meetings)
            index.updated_at = datetime.now().isoformat()
            
            # Save updated index
            self._save_index(index, index_path)
            
            logger.info(f"Successfully updated index with meeting {meeting_id}")
            
        except Exception as e:
            logger.error(f"Failed to add meeting {meeting_id} to index: {e}")
    
    def search_index(self, project_name: str, query: str, max_results: int = 50) -> List[MeetingIndexEntry]:
        """Search the meeting index for a project.
        
        Args:
            project_name: Name of the project
            query: Search query
            max_results: Maximum number of results to return
        
        Returns:
            List of matching meeting entries, sorted by relevance
        """
        index_path = self._get_index_path(project_name)
        if not index_path.exists():
            logger.warning(f"No index found for project {project_name}")
            return []
        
        try:
            index = self._load_index(index_path)
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return []
        
        # Simple text search across all fields
        query_lower = query.lower()
        query_words = query_lower.split()
        
        results = []
        for meeting in index.meetings:
            score = self._calculate_relevance_score(meeting, query_lower, query_words)
            if score > 0:
                results.append((meeting, score))
        
        # Sort by relevance score (highest first)
        results.sort(key=lambda x: x[1], reverse=True)
        
        return [meeting for meeting, score in results[:max_results]]
    
    def _calculate_relevance_score(self, meeting: MeetingIndexEntry, query_lower: str, query_words: List[str]) -> float:
        """Calculate relevance score for a meeting entry."""
        score = 0.0
        
        # Search in different fields with different weights
        search_fields = [
            (meeting.meeting_name.lower(), 3.0),
            (" ".join(meeting.decisions).lower(), 2.5),
            (" ".join(meeting.action_items).lower(), 2.5),
            (" ".join(meeting.risks).lower(), 2.0),
            (" ".join(meeting.open_questions).lower(), 2.0),
            (" ".join(meeting.keywords).lower(), 1.5),
            (meeting.full_transcript.lower(), 1.0),
        ]
        
        for field_text, weight in search_fields:
            if not field_text:
                continue
                
            # Exact phrase match gets highest score
            if query_lower in field_text:
                score += weight * 10
            
            # Individual word matches
            for word in query_words:
                if word in field_text:
                    score += weight
        
        return score
    
    def _scan_meeting_files(self) -> Dict[str, Path]:
        """Scan for all meeting JSON files."""
        meeting_files = {}
        
        if not self.json_notes_dir.exists():
            logger.warning(f"JSON notes directory not found: {self.json_notes_dir}")
            return meeting_files
        
        for json_file in self.json_notes_dir.glob("meeting_*_notes.json"):
            meeting_id = json_file.stem  # Remove .json extension
            meeting_files[meeting_id] = json_file
        
        return meeting_files
    
    def _find_transcript_path(self, meeting_id: str) -> Optional[Path]:
        """Find corresponding transcript file for a meeting."""
        # Extract base meeting ID (remove _notes suffix)
        base_id = meeting_id.replace("_notes", "")
        transcript_file = self.transcripts_dir / f"{base_id}.txt"
        
        return transcript_file if transcript_file.exists() else None
    
    def _get_index_path(self, project_name: str) -> Path:
        """Get the path for a project's meeting index."""
        project_dir = project_manager.ensure_project_structure(project_name)
        return project_dir / "meetings_index.json"
    
    def _load_index(self, index_path: Path) -> MeetingIndex:
        """Load index from JSON file."""
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return MeetingIndex.from_dict(data)
    
    def _save_index(self, index: MeetingIndex, index_path: Path) -> None:
        """Save index to JSON file."""
        index_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.debug(f"Saved index to: {index_path}")


# Global instance
meeting_index_builder = MeetingIndexBuilder()




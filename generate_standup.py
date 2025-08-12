import argparse
import json
import os
from datetime import datetime, timedelta
import sys
from pathlib import Path

# --- Configuration ---
# Assume this script is run from the same directory as AibaTS.py
# Or adjust the base path as needed
APP_BASE_DIR = Path(__file__).resolve().parent
BASE_FOLDER = APP_BASE_DIR / "meeting_data_v2" # Use v2 data folder
HISTORY_FILE = BASE_FOLDER / "meeting_history.json"
NOTES_FOLDER = BASE_FOLDER / "json_notes"

DEFAULT_HOURS_BACK = 72

# --- MeetingData Class (Copied from AibaTS.py for standalone use) ---
class MeetingData:
    """Represents meeting metadata, matching the structure in AibaTS.py"""
    def __init__(self, meeting_id, name, date, project_name,
                 summary_path, transcript_path, mentor_feedback_path=None,
                 full_audio_path=None, json_notes_path=None):
        self.meeting_id = meeting_id
        self.name = name
        self.date = date
        self.project_name = project_name
        self.summary_path = summary_path
        self.transcript_path = transcript_path
        self.mentor_feedback_path = mentor_feedback_path
        self.full_audio_path = full_audio_path
        self.json_notes_path = json_notes_path

    @classmethod
    def from_dict(cls, data):
        # Ensure date is stored/retrieved consistently if needed elsewhere
        return cls(
            data.get("meeting_id", ""), data.get("name", ""), data.get("date", ""),
            data.get("project_name", "Unknown"),
            data.get("summary_path", ""), data.get("transcript_path", ""),
            data.get("mentor_feedback_path", None),
            data.get("full_audio_path", None),
            data.get("json_notes_path", None)
        )

# --- Helper Functions ---

def load_meeting_history(history_path):
    """Loads meeting history from the JSON file."""
    if not history_path.exists():
        print(f"Error: History file not found at {history_path}", file=sys.stderr)
        return None
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
            # Convert dicts to MeetingData objects
            return [MeetingData.from_dict(m) for m in history_data]
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from history file: {history_path}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error reading history file {history_path}: {e}", file=sys.stderr)
        return None

def format_meeting_notes_md(meeting, notes_data):
    """Formats the notes from a single meeting into a Markdown section."""
    md_string = ""
    if not isinstance(notes_data, dict): # Handle cases where LLM failed JSON format
        md_string += f"  *   **Notes Error:** Could not parse JSON notes for this meeting.\n"
        return md_string

    sections = {
        "Decisions": notes_data.get("decisions", []),
        "Action Items": notes_data.get("action_items", []),
        "Risks": notes_data.get("risks", []),
        "Open Questions": notes_data.get("open_questions", [])
    }

    has_content = False
    meeting_md = ""
    for title, items in sections.items():
        if items and isinstance(items, list) and len(items) > 0:
            has_content = True
            meeting_md += f"  *   **{title}:**\n"
            for item in items:
                # Basic formatting, replace potential newlines in item text
                item_text = str(item).replace('\n', ' ')
                meeting_md += f"      *   {item_text}\n"

    if has_content:
        md_string += f"## Meeting: {meeting.name} ({meeting.date})\n"
        md_string += meeting_md
    else:
        # Optionally mention meetings with no extracted notes
        # md_string += f"## Meeting: {meeting.name} ({meeting.date})\n"
        # md_string += "  *   (No key decisions, actions, risks, or questions extracted)\n"
        pass # Or just skip meetings with no relevant notes

    return md_string

# --- Main Script Logic ---

def main():
    parser = argparse.ArgumentParser(description="Generate a stand-up cheat sheet from recent meeting notes.")
    parser.add_argument("-p", "--project", required=True, help="Project name to filter meetings by (case-insensitive).")
    parser.add_argument("-H", "--hours", type=int, default=DEFAULT_HOURS_BACK,
                        help=f"How many hours back to look for meetings (default: {DEFAULT_HOURS_BACK}).")
    parser.add_argument("--base-folder", default=str(BASE_FOLDER),
                        help="Path to the base meeting data folder (default: ./meeting_data_v2).")

    args = parser.parse_args()

    # Recalculate paths based on CLI argument if provided
    current_base_folder = Path(args.base_folder)
    current_history_file = current_base_folder / "meeting_history.json"
    current_notes_folder = current_base_folder / "json_notes"

    # 1. Load History
    all_meetings = load_meeting_history(current_history_file)
    if all_meetings is None:
        sys.exit(1) # Exit if history cannot be loaded

    # 2. Filter Meetings
    now = datetime.now()
    cutoff_time = now - timedelta(hours=args.hours)
    target_project_lower = args.project.lower() # Case-insensitive comparison

    relevant_meetings = []
    for meeting in all_meetings:
        try:
            # Ensure project name comparison is case-insensitive
            if meeting.project_name and meeting.project_name.lower() == target_project_lower:
                meeting_date = datetime.strptime(meeting.date, "%Y-%m-%d %H:%M")
                if meeting_date >= cutoff_time:
                    if meeting.json_notes_path: # Make sure notes path exists in record
                        relevant_meetings.append(meeting)
                    else:
                         print(f"Info: Skipping meeting '{meeting.name}' ({meeting.date}) - No JSON notes path recorded.", file=sys.stderr)

        except ValueError:
            print(f"Warning: Could not parse date for meeting '{meeting.name}' ({meeting.date}). Skipping.", file=sys.stderr)
        except AttributeError:
             print(f"Warning: Meeting record missing expected attributes (project_name, date, or json_notes_path). Skipping.", file=sys.stderr)


    if not relevant_meetings:
        print(f"# Stand-up Cheat Sheet for Project: {args.project}\n")
        print(f"No relevant meeting notes found in the last {args.hours} hours.")
        sys.exit(0)

    # 3. Sort Meetings (Oldest first)
    relevant_meetings.sort(key=lambda m: datetime.strptime(m.date, "%Y-%m-%d %H:%M"))

    # 4. Process Notes and Format Output
    markdown_output = f"# Stand-up Cheat Sheet: {args.project} (Last {args.hours} Hours)\n\n"
    meetings_processed_count = 0

    for meeting in relevant_meetings:
        notes_file_path = Path(meeting.json_notes_path) # Construct Path object

        # Check if the file exists relative to the *potentially overridden* base folder
        # This assumes json_notes_path stored in history is relative to BASE_FOLDER
        # A safer approach might be to store absolute paths or reconstruct them carefully.
        # For now, let's try reconstructing from the current base folder and the meeting ID.
        expected_notes_filename = f"{meeting.meeting_id}_notes.json"
        absolute_notes_path = current_notes_folder / expected_notes_filename

        if not absolute_notes_path.exists():
            print(f"Warning: Notes file not found for meeting '{meeting.name}' ({meeting.date}) at {absolute_notes_path}. Skipping.", file=sys.stderr)
            continue

        try:
            with open(absolute_notes_path, 'r', encoding='utf-8') as f:
                notes_data = json.load(f)
                meeting_md = format_meeting_notes_md(meeting, notes_data)
                if meeting_md: # Only add if there was content formatted
                    markdown_output += meeting_md + "\n" # Add newline between meetings
                    meetings_processed_count += 1
        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON notes for meeting '{meeting.name}' ({meeting.date}) from {absolute_notes_path}. Skipping.", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Error processing notes file {absolute_notes_path} for meeting '{meeting.name}': {e}. Skipping.", file=sys.stderr)

    if meetings_processed_count == 0:
         markdown_output += "(No extracted decisions, actions, risks, or questions found in relevant meetings)\n"

    # 5. Print Output
    print(markdown_output)

if __name__ == "__main__":
    main()
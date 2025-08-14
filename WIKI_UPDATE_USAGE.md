# Wiki Update Function Usage

## Overview

The `updateProjectWiki()` function adds new meeting entries to project wikis in a structured format. It reads the current wiki, prepends the new meeting at the top of the Meeting History section, and saves the updated file.

## Function Signature

```python
def updateProjectWiki(
    project_name: str,
    meeting_name: str,
    transcript_text: str,
    duration_minutes: Optional[int] = None,
    transcript_file_path: Optional[str] = None,
    meeting_date: Optional[str] = None
) -> bool:
```

## Parameters

- **`project_name`**: Name of the project (creates project structure if needed)
- **`meeting_name`**: Title/name of the meeting
- **`transcript_text`**: Full transcript text
- **`duration_minutes`**: Meeting duration in minutes (optional)
- **`transcript_file_path`**: Path to JSON transcript file (optional) 
- **`meeting_date`**: Meeting date in YYYY-MM-DD format (defaults to today)

## Usage Examples

### Basic Usage

```python
from services.wiki_updater import updateProjectWiki

# Simple meeting entry
success = updateProjectWiki(
    project_name="MyProject",
    meeting_name="Sprint Planning",
    transcript_text="Meeting transcript content here..."
)

if success:
    print("Wiki updated successfully!")
```

### Complete Usage with All Parameters

```python
from services.wiki_updater import updateProjectWiki

success = updateProjectWiki(
    project_name="MyProject",
    meeting_name="Sprint Planning Meeting",
    transcript_text="Full meeting transcript...",
    duration_minutes=45,
    transcript_file_path="meeting_data_v2/json_notes/meeting_123_notes.json",
    meeting_date="2025-08-11"
)
```

### Integration with Meeting Records

```python
from services.wiki_integration import update_project_wiki_from_meeting

# Using existing meeting record
success = update_project_wiki_from_meeting(
    meeting_record=meeting_record,
    transcript_text=transcript,
    duration_minutes=30
)
```

## Output Format

The function creates entries in this exact format:

```markdown
### [Date] - [Meeting Name]
**Duration:** [X] minutes
**Transcript File:** [Link to JSON file]

#### Summary
[AI generated summary with structured sections]

#### Full Transcript
<details>
<summary>Click to expand transcript</summary>

[Full transcript text]

</details>

---
```

## Features

### 🔄 **Automatic Prepending**
- New meetings are added at the top of the Meeting History section
- Maintains chronological order (newest first)

### 🤖 **AI-Generated Summaries**
- Uses the same AI backend as suggestions (Claude/OpenAI)
- Structured summary with Overview, Key Decisions, Action Items, etc.
- Automatic fallback between AI services

### 📁 **Project Structure Management**
- Automatically creates project folders if they don't exist
- Ensures `./projects/{ProjectName}/wiki.md` structure
- Creates `meetings/` subdirectory for future use

### 🔗 **Smart File Linking**
- Links to transcript files with relative paths
- Handles both absolute and relative file paths
- Shows file names in markdown links

### 📝 **Collapsible Transcripts**
- Full transcripts are hidden in collapsible sections
- Saves space while maintaining access to full content
- Uses HTML `<details>` tags for expandable content

## File Structure

After using the function, your project structure will look like:

```
./projects/
└── ProjectName/
    ├── wiki.md          ← Updated with meeting entries
    └── meetings/        ← Available for future use
```

## Error Handling

The function includes comprehensive error handling:

- **AI Summary Failures**: Falls back to error message if summary generation fails
- **File Permissions**: Handles file access issues gracefully
- **Invalid Inputs**: Validates project names and required parameters
- **Path Resolution**: Handles both absolute and relative file paths

## Integration Options

### Option 1: Direct Function Call
```python
from services.wiki_updater import updateProjectWiki
updateProjectWiki(project, meeting, transcript)
```

### Option 2: Integration Layer
```python
from services.wiki_integration import update_project_wiki_simple
update_project_wiki_simple(project, meeting, transcript)
```

### Option 3: Meeting Record Integration
```python
from services.wiki_integration import update_project_wiki_from_meeting
update_project_wiki_from_meeting(meeting_record, transcript, duration)
```

## Return Value

- **`True`**: Wiki was successfully updated
- **`False`**: Update failed (check logs for details)

## Dependencies

- Project Manager service (for folder structure)
- Summary service (for AI-generated summaries) 
- Same API keys as existing suggestion system
- File system write permissions

## Status Updates

When integrated with the main application, the function will:
1. Read the current wiki.md file
2. Generate AI summary (with status indicator)
3. Prepend new meeting entry
4. Save updated wiki.md file
5. Update status to "Saved"




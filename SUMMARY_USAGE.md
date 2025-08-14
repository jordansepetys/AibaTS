# Structured Summary Function Usage

## Overview

The `generate_structured_summary()` function takes a meeting transcript and generates a structured summary using the configured AI service (Claude by default, with OpenAI fallback).

## Function Signature

```python
def generate_structured_summary(transcript_text: str) -> str:
    """
    Generate a structured summary from a meeting transcript.
    
    Args:
        transcript_text (str): The meeting transcript text to analyze
        
    Returns:
        str: Formatted markdown text with the structured summary
        
    Raises:
        ValueError: If transcript is empty or invalid
        Exception: If summary generation fails completely
    """
```

## Usage Examples

### Basic Usage

```python
from services.summary_function import generate_structured_summary

# Sample transcript
transcript = """
Meeting started at 9 AM with John, Sarah, and Mike present.

We discussed the Q4 budget and reviewed last quarter's performance. 
John volunteered to prepare the financial report by Friday. 
Sarah raised concerns about the aggressive timeline and vendor capacity.

Key decisions:
- Approved the marketing budget increase of 15%
- Decided to postpone the office renovation until Q1 next year

Mike will reach out to the vendors to confirm delivery dates.
We still need to resolve the staffing issues in the support team.
The team agreed to meet again next Tuesday to review progress.
"""

# Generate summary
summary = generate_structured_summary(transcript)
print(summary)
```

### Expected Output Format

The function returns markdown-formatted text with these sections:

```markdown
## Overview

Brief 2-3 sentence summary of the meeting content and key outcomes.

## Key Decisions

- Decision 1 with relevant details
- Decision 2 with relevant details

## Action Items

- Action item 1 (assignee if mentioned)
- Action item 2 (assignee if mentioned)

## Important Topics Discussed

- Topic 1
- Topic 2
- Topic 3

## Unresolved Questions/Issues

- Unresolved question 1
- Outstanding issue 2
```

### Error Handling

```python
from services.summary_function import generate_structured_summary

try:
    summary = generate_structured_summary(transcript_text)
    print(summary)
except ValueError as e:
    print(f"Input error: {e}")
except Exception as e:
    print(f"Summary generation failed: {e}")
```

## Backend Configuration

The function uses the same AI backend configuration as the rest of the application:

- **Primary**: Claude (if `ANTHROPIC_API_KEY` is set)
- **Fallback**: OpenAI (if `OPENAI_API_KEY` is set)
- **Model**: Configurable via `CLAUDE_MODEL` and `OPENAI_SUGGEST_MODEL` environment variables

## Features

1. **Structured Analysis**: Automatically categorizes meeting content into distinct sections
2. **Assignee Detection**: Identifies action item assignees when mentioned in the transcript
3. **Fallback Support**: Automatically switches between AI backends if one fails
4. **Error Handling**: Provides clear error messages for debugging
5. **Markdown Output**: Returns properly formatted markdown for easy integration

## Integration with Existing App

The function integrates seamlessly with the existing codebase and can be used:

- As a standalone function for custom workflows
- Integrated into the main UI for additional summary features
- Called from other services for batch processing
- Used in scripts for automated meeting analysis

## Dependencies

- Requires the same API keys as the existing suggestion system
- Uses the existing configuration and logging infrastructure
- Compatible with the current backend fallback mechanism




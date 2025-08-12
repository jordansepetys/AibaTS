# AibaTS Desktop Tool (Local-Only)

This is a Windows desktop application (PyQt5) for recording meetings, transcribing (OpenAI Whisper API by default), generating AI suggestions, and updating your local wikis and journal.

## Quick Start

1) Create/activate a Python 3.10+ virtual environment.
2) Install dependencies:

```
pip install -r requirements.txt
```

3) Create a `.env` file in the project root (same folder as `run_desktop.py`):

```
# API Keys (choose based on your preference)
OPENAI_API_KEY=your-openai-key-here
ANTHROPIC_API_KEY=your-claude-key-here

# Backend Selection (optional)
SUGGESTION_BACKEND=claude  # "claude" (default) or "openai"
TRANSCRIPTION_BACKEND=OPENAI_WHISPER  # Currently only OpenAI Whisper supported

# Optional API overrides
OPENAI_API_BASE=https://api.openai.com
OPENAI_TRANSCRIBE_MODEL=whisper-1
OPENAI_SUGGEST_MODEL=gpt-4o
CLAUDE_MODEL=claude-3-5-sonnet-20241022
```

4) Run the app:

```
python run_desktop.py
```

## Folders

- meeting_data_v2/
  - recordings/: full WAV files per meeting
  - transcripts/: `<meeting_id>.txt`
  - summaries/weekly/: `weekly_YYYY-WW.md`
  - project_wikis/: `<Project>_wiki.md`, `Journal_wiki.md`
  - meeting_history.json

## Packaging (PyInstaller)

Recommended one-file build:

```
pyinstaller --noconfirm --onefile --name AibaTSDesktop \
  --add-data "meeting_data_v2;meeting_data_v2" \
  --add-data "project_wikis;project_wikis" \
  run_desktop.py
```

Notes:
- Place `.env` beside the generated `AibaTSDesktop.exe` for API access.
- If PyAudio fails to open a device, ensure your default input device is enabled and accessible. WASAPI conflicts can require closing other audio apps.
- The app uses Claude 4 by default for suggestions with OpenAI as fallback. You can set either `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (or both for maximum reliability).
- Without any API keys, the app remains usable for recording/journal/wiki, but cloud transcription/suggestions are disabled.






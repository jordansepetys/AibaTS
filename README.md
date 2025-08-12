# AibaTS Desktop Tool

Record meetings, transcribe audio, generate summaries, and auto-update a project wiki/journal. Includes quick-query and a Meetings tab to browse/search transcripts.

## Quick Start
1. python -m venv .venv; .venv\Scripts\activate
2. pip install -r requirements.txt
3. Copy .env.example to .env and set keys
4. python run_desktop.py

## Screenshots
- Place images under docs/screenshots/
- Add links: ![Recording](docs/screenshots/recording.png), ![Wiki](docs/screenshots/wiki.png)

## Environment
- OPENAI_API_KEY (Whisper + optional summaries)
- ANTHROPIC_API_KEY (Claude summaries)
- LLM_API_URL, WHISPER_API_URL
- TRANSCRIPTION_BACKEND=OPENAI_WHISPER
- SUGGESTION_BACKEND=claude|openai

## Safety Checklist
- .env, logs/, and meeting_data_v2/ ignored
- No hard-coded keys (loaded via services/config.py)
- Optional: run a secret scan (gitleaks/detect-secrets)

If you accidentally committed data:
- git rm -r --cached .env logs meeting_data_v2
- git commit -m "chore: remove tracked secrets and generated data"
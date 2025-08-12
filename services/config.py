import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    data_base: Path
    project_wikis_dir: Path
    recordings_dir: Path
    transcripts_dir: Path
    summaries_dir: Path
    weekly_summaries_dir: Path
    json_notes_dir: Path
    logs_dir: Path

    openai_api_key: Optional[str]
    llm_api_url: str
    whisper_api_url: str

    # UI/behavior flags
    use_openai_whisper: bool
    suggestion_backend: str  # "claude" or "openai"


def load_config() -> AppConfig:
    # Determine base directory: if frozen (PyInstaller), use executable directory.
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parents[1]

    # Load .env explicitly from base_dir
    load_dotenv(dotenv_path=base_dir / ".env")

    data_base = base_dir / "meeting_data_v2"
    project_wikis_dir = data_base / "project_wikis"
    recordings_dir = data_base / "recordings"
    transcripts_dir = data_base / "transcripts"
    summaries_dir = data_base / "summaries"
    weekly_summaries_dir = summaries_dir / "weekly"
    json_notes_dir = data_base / "json_notes"
    logs_dir = base_dir / "logs"

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    llm_api_url = os.environ.get("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
    whisper_api_url = os.environ.get("WHISPER_API_URL", "https://api.openai.com/v1/audio/transcriptions")

    use_openai_whisper = os.environ.get("TRANSCRIPTION_BACKEND", "OPENAI_WHISPER").upper() == "OPENAI_WHISPER"
    suggestion_backend = os.environ.get("SUGGESTION_BACKEND", "claude").lower()

    return AppConfig(
        base_dir=base_dir,
        data_base=data_base,
        project_wikis_dir=project_wikis_dir,
        recordings_dir=recordings_dir,
        transcripts_dir=transcripts_dir,
        summaries_dir=summaries_dir,
        weekly_summaries_dir=weekly_summaries_dir,
        json_notes_dir=json_notes_dir,
        logs_dir=logs_dir,
        openai_api_key=openai_api_key,
        llm_api_url=llm_api_url,
        whisper_api_url=whisper_api_url,
        use_openai_whisper=use_openai_whisper,
        suggestion_backend=suggestion_backend,
    )



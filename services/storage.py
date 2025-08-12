from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StoragePaths:
    base_dir: Path
    data_base: Path
    project_wikis_dir: Path
    recordings_dir: Path
    transcripts_dir: Path
    summaries_dir: Path
    weekly_summaries_dir: Path
    json_notes_dir: Path
    logs_dir: Path


def ensure_directories(paths: StoragePaths) -> None:
    # Create all directories we rely on
    for d in [
        paths.data_base,
        paths.project_wikis_dir,
        paths.recordings_dir,
        paths.transcripts_dir,
        paths.summaries_dir,
        paths.weekly_summaries_dir,
        paths.json_notes_dir,
        paths.logs_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def normalize_path(p: Path) -> str:
    # Store paths in JSON using forward slashes for consistency
    return str(p.as_posix())




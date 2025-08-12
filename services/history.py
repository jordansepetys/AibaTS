import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from loguru import logger


@dataclass
class MeetingRecord:
    meeting_id: str
    name: str
    date: str  # YYYY-MM-DD HH:MM
    project_name: str
    transcript_path: str
    summary_path: Optional[str] = None
    full_audio_path: Optional[str] = None
    json_notes_path: Optional[str] = None

    @staticmethod
    def from_dict(d: dict) -> "MeetingRecord":
        """Create a MeetingRecord tolerantly from a dict with possible legacy keys.

        - Keep only known fields
        - Coerce missing optional fields to None
        - Normalize path slashes to forward '/'
        """
        def norm(v: Optional[str]) -> Optional[str]:
            if not v:
                return None
            return str(v).replace("\\", "/")

        return MeetingRecord(
            meeting_id=str(d.get("meeting_id", "")),
            name=str(d.get("name", "")),
            date=str(d.get("date", "")),
            project_name=str(d.get("project_name", d.get("project", ""))),
            transcript_path=str(d.get("transcript_path", "")).replace("\\", "/"),
            summary_path=norm(d.get("summary_path")),
            full_audio_path=norm(d.get("full_audio_path")),
            json_notes_path=norm(d.get("json_notes_path")),
        )


class MeetingHistory:
    def __init__(self, history_path: Path) -> None:
        self.history_path = history_path
        self.records: List[MeetingRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.history_path.exists():
            self.records = []
            return
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            records: List[MeetingRecord] = []
            for item in data:
                try:
                    rec = MeetingRecord.from_dict(item)
                    # Minimal validation
                    if rec.meeting_id and rec.date:
                        records.append(rec)
                    else:
                        logger.warning(f"Skipping malformed history row (missing id/date): {item}")
                except Exception as e:
                    logger.warning(f"Skipping malformed history row: {e} | row={item}")
            self.records = records
        except Exception as e:
            logger.warning(f"Failed to read meeting history; starting fresh: {e}")
            self.records = []

    def add_or_update(self, rec: MeetingRecord) -> None:
        existing = next((r for r in self.records if r.meeting_id == rec.meeting_id), None)
        if existing:
            # Update fields
            existing.name = rec.name
            existing.date = rec.date
            existing.project_name = rec.project_name
            existing.transcript_path = rec.transcript_path
            existing.summary_path = rec.summary_path
            existing.full_audio_path = rec.full_audio_path
        else:
            self.records.append(rec)
        self._save()

    def _save(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        # Serialize only canonical fields, with forward slashes
        def to_jsonable(r: MeetingRecord) -> dict:
            obj = {
                "meeting_id": r.meeting_id,
                "name": r.name,
                "date": r.date,
                "project_name": r.project_name,
                "transcript_path": (r.transcript_path or "").replace("\\", "/"),
            }
            if r.summary_path:
                obj["summary_path"] = r.summary_path.replace("\\", "/")
            if r.full_audio_path:
                obj["full_audio_path"] = r.full_audio_path.replace("\\", "/")
            if r.json_notes_path:
                obj["json_notes_path"] = r.json_notes_path.replace("\\", "/")
            return obj

        payload = [to_jsonable(r) for r in self.records]
        self.history_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(f"Saved meeting history → {self.history_path}")



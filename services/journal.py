from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


JOURNAL_FILE = "Journal_wiki.md"


def ensure_journal_date_section(project_wikis_dir: Path, date_str: str) -> Path:
    """Ensure the journal file and date section exist. Returns path to journal file.

    - File: project_wikis/Journal_wiki.md
    - Date section header: '## YYYY-MM-DD'
    """
    journal_path = project_wikis_dir / JOURNAL_FILE
    if not journal_path.exists():
        journal_path.write_text("# Journal\n\n", encoding="utf-8")
        logger.info(f"Created journal file: {journal_path}")

    content = journal_path.read_text(encoding="utf-8")
    if not content.endswith("\n"):
        content += "\n"
    header = f"## {date_str}\n"
    if header not in content:
        content += header + "\n"
        journal_path.write_text(content, encoding="utf-8")
        logger.info(f"Added journal date section: {date_str}")

    return journal_path


def append_journal_entry(
    project_wikis_dir: Path,
    date_str: str,
    project: str,
    meeting: str,
    recap_one_line: str,
    details_bullets: Optional[list] = None,
) -> None:
    """Append an entry under the date section. Prevent duplicate header and allow repeated entries.

    Format:
    - '- [HH:MM] <Project> — <Meeting>: <1-line recap>'
    - Optional indented bullets for details
    """
    journal_path = ensure_journal_date_section(project_wikis_dir, date_str)
    now_hhmm = datetime.now().strftime("%H:%M")
    lines = journal_path.read_text(encoding="utf-8").splitlines(keepends=True)

    # Find date header index
    header_line = f"## {date_str}\n"
    try:
        idx = lines.index(header_line)
    except ValueError:
        # Should not happen because ensure_journal_date_section already added it
        lines.append(header_line)
        idx = len(lines) - 1

    insertion_idx = idx + 1
    # Insert after header; if there is a blank line after header, skip past
    while insertion_idx < len(lines) and lines[insertion_idx].strip() == "":
        insertion_idx += 1

    entry = f"- [{now_hhmm}] {project} — {meeting}: {recap_one_line.strip()}\n"
    detail_lines = []
    if details_bullets:
        for d in details_bullets:
            d = str(d).strip()
            if d:
                detail_lines.append(f"  - {d}\n")

    lines[insertion_idx:insertion_idx] = [entry] + detail_lines + ["\n"]
    journal_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Appended journal entry to {journal_path}")




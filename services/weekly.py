from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from loguru import logger


DATE_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")


def _parse_journal_sections(journal_path: Path) -> "OrderedDict[str, List[str]]":
    """Parse Journal_wiki.md into an ordered mapping of date -> lines under that section.

    Returns an OrderedDict preserving file order (earliest to latest appearance).
    """
    text = journal_path.read_text(encoding="utf-8") if journal_path.exists() else ""
    lines = text.splitlines(keepends=True)

    sections: "OrderedDict[str, List[str]]" = OrderedDict()
    current_date: str | None = None
    for ln in lines:
        m = DATE_HEADER_RE.match(ln.strip())
        if m:
            current_date = m.group(1)
            if current_date not in sections:
                sections[current_date] = []
            continue
        if current_date:
            sections[current_date].append(ln)
    return sections


def _dates_in_iso_week(target: date) -> List[str]:
    iso_year, iso_week, _ = target.isocalendar()
    # Find Monday of that ISO week
    monday = target - timedelta(days=target.weekday())
    dates = [(monday + timedelta(days=i)) for i in range(7)]
    result = []
    for d in dates:
        y, w, _ = d.isocalendar()
        if y == iso_year and w == iso_week:
            result.append(d.strftime("%Y-%m-%d"))
    return result


def generate_weekly_from_journal(
    project_wikis_dir: Path,
    weekly_dir: Path,
    target_day: date | None = None,
) -> Path:
    """Generate weekly summary markdown from Journal_wiki.md into weekly_YYYY-WW.md.

    - Overwrites file if exists.
    - Includes all date sections from the target ISO week that exist in the journal.
    - If none found, falls back to the most recent up to 7 date sections.
    """
    target_day = target_day or date.today()
    journal_path = project_wikis_dir / "Journal_wiki.md"
    weekly_dir.mkdir(parents=True, exist_ok=True)

    sections = _parse_journal_sections(journal_path)
    if not sections:
        raise FileNotFoundError("No journal entries found.")

    want_dates = set(_dates_in_iso_week(target_day))
    # Preserve order: we'll iterate over sections in order, but we want only dates in the ISO week
    selected: List[Tuple[str, List[str]]] = [
        (d, lines) for d, lines in sections.items() if d in want_dates
    ]

    if not selected:
        # Fallback: take last 7 dates by chronological order
        all_dates = list(sections.keys())
        last7 = all_dates[-7:]
        selected = [(d, sections[d]) for d in last7]

    iso_year, iso_week, _ = target_day.isocalendar()
    out_path = weekly_dir / f"weekly_{iso_year}-{iso_week:02d}.md"

    parts: List[str] = []
    parts.append(f"# Weekly Summary {iso_year}-W{iso_week:02d}\n\n")
    for d, lines in selected:
        parts.append(f"## {d}\n")
        # Include lines as-is
        # Ensure a trailing newline between sections
        content = "".join(lines).rstrip("\n")
        if content:
            parts.append(content + "\n\n")
        else:
            parts.append("\n")

    out_path.write_text("".join(parts), encoding="utf-8")
    logger.info(f"Weekly summary generated → {out_path}")
    return out_path


def build_weekly_structured_summary(
    project_wikis_dir: Path,
    target_day: Optional[date] = None,
) -> Dict[str, object]:
    """Build a structured weekly summary from Journal_wiki.md without writing files.

    Returns dict with keys:
      - dates: List[str]
      - accomplished: List[str]
      - next_week: List[str]
      - topics: List[str]
      - exec_summary: str (3-5 sentences)
    """
    target_day = target_day or date.today()
    journal_path = project_wikis_dir / "Journal_wiki.md"
    sections = _parse_journal_sections(journal_path)
    if not sections:
        raise FileNotFoundError("No journal entries found.")

    want_dates = set(_dates_in_iso_week(target_day))
    selected: List[Tuple[str, List[str]]] = [
        (d, lines) for d, lines in sections.items() if d in want_dates
    ]
    if not selected:
        # Fallback: take last up to 7 dates
        all_dates = list(sections.keys())
        last7 = all_dates[-7:]
        selected = [(d, sections[d]) for d in last7]

    dates = [d for d, _ in selected]
    accomplished: List[str] = []
    next_week: List[str] = []
    topics: List[str] = []

    for _, lines in selected:
        for raw in lines:
            ln = raw.strip()
            # Detail bullets in journal are prefixed with two spaces and a dash, but we normalize by startswith checks
            if ln.startswith("- ") and " — " in ln:
                # Top-level entry line with recap text after colon
                # Example: - [HH:MM] Project — Meeting: recap text
                parts = ln.split(":", 1)
                if len(parts) == 2:
                    recap_text = parts[1].strip()
                    if recap_text:
                        topics.append(recap_text)
            elif ln.startswith("- ") or ln.startswith("• "):
                # Handle any stray bullets
                pass
            elif ln.startswith("Accomplished:") or ln.startswith("- Accomplished:"):
                accomplished.append(ln.split(":", 1)[1].strip())
            elif ln.startswith("To Do:") or ln.startswith("- To Do:"):
                next_week.append(ln.split(":", 1)[1].strip())
            elif ln.startswith("Topic:") or ln.startswith("- Topic:"):
                topics.append(ln.split(":", 1)[1].strip())
            elif ln.startswith("-"):
                # Indented detail bullets in our writer look like "  - X"; strip leading hyphen and see if prefix exists
                text = ln.lstrip("- ")
                if text.lower().startswith("accomplished:"):
                    accomplished.append(text.split(":", 1)[1].strip())
                elif text.lower().startswith("to do:"):
                    next_week.append(text.split(":", 1)[1].strip())
                elif text.lower().startswith("topic:"):
                    topics.append(text.split(":", 1)[1].strip())

    # Deduplicate and trim
    def _unique(seq: List[str]) -> List[str]:
        out, seen = [], set()
        for s in seq:
            s = s.strip()
            if s and s.lower() not in seen:
                out.append(s)
                seen.add(s.lower())
        return out

    topics = _unique(topics)[:10]
    accomplished = _unique(accomplished)[:20]
    next_week = _unique(next_week)[:20]

    # Build a simple 3-5 sentence executive summary
    sentences: List[str] = []
    if dates:
        sentences.append(f"This week covered {len(dates)} day(s): {', '.join(dates)}.")
    if topics:
        top_topics = topics[:3]
        sentences.append("Key topics included " + ", ".join(top_topics) + ("."))
    if accomplished:
        sentences.append(f"We completed {len(accomplished)} item(s), highlighting {', '.join(accomplished[:3])}.")
    if next_week:
        sentences.append("Next week we plan to focus on " + ", ".join(next_week[:3]) + ".")
    if len(sentences) < 3:
        sentences.append("Progress continued across projects with ongoing coordination and planning.")
    exec_summary = " ".join(sentences[:5])

    return {
        "dates": dates,
        "accomplished": accomplished,
        "next_week": next_week,
        "topics": topics,
        "exec_summary": exec_summary,
    }



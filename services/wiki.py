import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from services.suggest import MeetingSuggestions


SECTION_TEMPLATE = "## [{date}] {name}  <!-- id:{meeting_id} -->"
# Customized layout focused on topics, to-dos, and accomplishments
# - Topics Discussed: derived from recap text (split into bullets)
# - To Do: from actions
# - Accomplished: from decisions
SUBSECTIONS = [
    ("Topics Discussed", "recap_topics"),
    ("To Do", "actions"),
    ("Accomplished", "decisions"),
]


def ensure_project_wiki(project_wikis_dir: Path, project_name: str) -> Path:
    project_wikis_dir.mkdir(parents=True, exist_ok=True)
    wiki_path = project_wikis_dir / f"{project_name}_wiki.md"
    if not wiki_path.exists():
        wiki_path.write_text(f"# {project_name} Wiki\n\n", encoding="utf-8")
        logger.info(f"Created project wiki: {wiki_path}")
    return wiki_path


def _find_section_bounds(lines: List[str], header_line: str) -> Tuple[Optional[int], Optional[int]]:
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header_line.strip():
            start_idx = i
            break
    if start_idx is None:
        return None, None
    # Section ends at next '## ' heading or EOF
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    return start_idx, end_idx


def _merge_bullets(existing_lines: List[str], new_items: List[str]) -> List[str]:
    existing_set = set()
    for ln in existing_lines:
        s = ln.strip()
        if s.startswith("- "):
            existing_set.add(s[2:].strip())
    merged = list(existing_lines)
    for item in new_items:
        item_norm = item.strip()
        if item_norm and item_norm not in existing_set:
            merged.append(f"- {item_norm}\n")
            existing_set.add(item_norm)
    return merged


def upsert_meeting_section(
    wiki_path: Path,
    meeting_date_yyyy_mm_dd: str,
    meeting_name: str,
    meeting_id: str,
    suggestions: MeetingSuggestions,
) -> bool:
    """Insert or update a meeting section in the project wiki.

    Returns True if file was modified.
    """
    header_line = SECTION_TEMPLATE.format(date=meeting_date_yyyy_mm_dd, name=meeting_name, meeting_id=meeting_id)

    content = wiki_path.read_text(encoding="utf-8") if wiki_path.exists() else ""
    if content and not content.endswith("\n"):
        content += "\n"
    lines = content.splitlines(keepends=True)

    start_idx, end_idx = _find_section_bounds(lines, header_line)
    modified = False

    def _recap_to_topics(recap_text: str) -> List[str]:
        if not recap_text:
            return []
        # Split on newlines or sentence boundaries to form concise topic bullets
        parts = re.split(r"[\n\r]+|(?<=[\.!?])\s+", recap_text)
        topics = []
        for p in parts:
            t = p.strip(" -•\t")
            if len(t) >= 3:
                topics.append(t)
        # De-duplicate while preserving order
        seen = set()
        unique_topics = []
        for t in topics:
            if t not in seen:
                unique_topics.append(t)
                seen.add(t)
        return unique_topics[:12]  # reasonable cap

    def build_subsection(title: str, items: List[str]) -> List[str]:
        if not items:
            return []
        block = [f"### {title}\n"]
        block.extend([f"- {i.strip()}\n" for i in items if i.strip()])
        block.append("\n")
        return block

    if start_idx is None:
        # Insert new section at the TOP (most recent first), just after the top-level heading
        section_block: List[str] = []
        section_block.append(f"{header_line}\n")
        # Only include non-empty subsections
        for title, attr in SUBSECTIONS:
            if attr == "recap_topics":
                items = _recap_to_topics(getattr(suggestions, "recap", ""))
            else:
                items = getattr(suggestions, attr)
            section_block.extend(build_subsection(title, items))
        if not section_block[-1].endswith("\n"):
            section_block.append("\n")

        # Find insertion point: after the first line if it's a top-level '# ' heading and any following blank lines
        insert_idx = 0
        if lines:
            if lines[0].lstrip().startswith("# "):
                insert_idx = 1
                # Skip any blank lines after the header
                while insert_idx < len(lines) and lines[insert_idx].strip() == "":
                    insert_idx += 1
        # Ensure a blank line separation when inserting
        if insert_idx < len(lines) and lines[insert_idx].strip() != "":
            section_block.insert(0, "\n")
        if insert_idx > 0 and lines[insert_idx-1].strip() != "":
            section_block.insert(0, "\n")

        lines = lines[:insert_idx] + section_block + lines[insert_idx:]
        modified = True
    else:
        # Update existing: merge bullets per subsection
        section_lines = lines[start_idx:end_idx]
        # For each subsection, find its start
        for title, attr in SUBSECTIONS:
            if attr == "recap_topics":
                items = _recap_to_topics(getattr(suggestions, "recap", ""))
            else:
                items = getattr(suggestions, attr)
            if not items:
                continue
            # find '### {title}' within section
            sub_start = None
            sub_end = None
            for i in range(len(section_lines)):
                if section_lines[i].startswith(f"### {title}"):
                    sub_start = i
                    # end at next '### ' or end of section
                    sub_end = len(section_lines)
                    for k in range(i + 1, len(section_lines)):
                        if section_lines[k].startswith("### ") or section_lines[k].startswith("## "):
                            sub_end = k
                            break
                    break
            if sub_start is None:
                # add a new subsection at end of section
                insertion_point = len(section_lines)
                # ensure trailing newline
                if insertion_point > 0 and not section_lines[-1].endswith("\n"):
                    section_lines.append("\n")
                new_block = [f"### {title}\n"] + [f"- {i.strip()}\n" for i in items if i.strip()] + ["\n"]
                section_lines.extend(new_block)
                modified = True
            else:
                # merge bullets within existing subsection
                bullets = section_lines[sub_start + 1:sub_end]
                merged = _merge_bullets(bullets, items)
                if merged != bullets:
                    section_lines = section_lines[:sub_start + 1] + merged + section_lines[sub_end:]
                    modified = True
        # write back merged section
        if modified:
            lines = lines[:start_idx] + section_lines + lines[end_idx:]

    if modified:
        wiki_path.write_text("".join(lines), encoding="utf-8")
        logger.info(f"Updated project wiki: {wiki_path}")

    return modified




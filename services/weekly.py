from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from loguru import logger
from services.meeting_index import meeting_index_builder
from services.suggest import SuggestionGenerator, SuggestionUnavailable


DATE_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")


def _filter_journal_sections_by_project(sections: "OrderedDict[str, List[str]]", project_name: str) -> "OrderedDict[str, List[str]]":
    """Filter journal sections to only include entries for the specified project."""
    filtered_sections: "OrderedDict[str, List[str]]" = OrderedDict()
    
    for date, lines in sections.items():
        filtered_lines = []
        for line in lines:
            # Look for entries like: "- [HH:MM] ProjectName — Meeting: recap text"
            if line.strip().startswith("- [") and " — " in line:
                # Extract project name from the line
                try:
                    # Pattern: "- [HH:MM] ProjectName — Meeting: recap"
                    parts = line.split("] ", 1)
                    if len(parts) >= 2:
                        remaining = parts[1]
                        if " — " in remaining:
                            line_project = remaining.split(" — ")[0].strip()
                            if line_project.lower() == project_name.lower():
                                filtered_lines.append(line)
                except:
                    # If parsing fails, skip this line
                    continue
            elif line.strip().startswith("  - ") and filtered_lines:
                # Include detail bullets if we just added a main entry
                filtered_lines.append(line)
            elif not line.strip():
                # Include blank lines to preserve formatting
                filtered_lines.append(line)
        
        if filtered_lines:
            filtered_sections[date] = filtered_lines
    
    return filtered_sections


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
    project_name: str | None = None,
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
    
    # Filter sections by project if specified
    if project_name:
        sections = _filter_journal_sections_by_project(sections, project_name)

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
    project_suffix = f"_{project_name}" if project_name else ""
    out_path = weekly_dir / f"weekly_{iso_year}-{iso_week:02d}{project_suffix}.md"

    parts: List[str] = []
    title_suffix = f" - {project_name}" if project_name else ""
    parts.append(f"# Weekly Summary {iso_year}-W{iso_week:02d}{title_suffix}\n\n")
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
    return build_weekly_structured_summary_for_project(project_wikis_dir, None, target_day)


def build_weekly_structured_summary_for_project(
    project_wikis_dir: Path,
    project_name: Optional[str] = None,
    target_day: Optional[date] = None,
) -> Dict[str, object]:
    """Build a rich, AI-enhanced weekly summary for a specific project.

    Returns dict with keys:
      - dates: List[str]
      - accomplished: List[str] (detailed accomplishments with context)
      - next_week: List[str] (detailed plans with context)
      - topics: List[str]
      - exec_summary: str (rich narrative executive summary)
      - challenges: List[str] (challenges and issues encountered)
      - metrics: List[str] (key metrics and progress indicators)
    """
    target_day = target_day or date.today()
    
    # Get both journal entries AND meeting data for the week
    journal_data = _get_journal_data_for_week(project_wikis_dir, project_name, target_day)
    meeting_data = _get_meeting_data_for_week(project_wikis_dir, project_name, target_day)
    
    if not journal_data and not meeting_data:
        return _empty_weekly_summary()

    # Generate AI-enhanced summary using both data sources
    return _generate_ai_weekly_summary(journal_data, meeting_data, project_name, target_day)


def _get_journal_data_for_week(project_wikis_dir: Path, project_name: Optional[str], target_day: date) -> Dict[str, List[str]]:
    """Get journal entries for the specified week and project."""
    journal_path = project_wikis_dir / "Journal_wiki.md"
    sections = _parse_journal_sections(journal_path)
    
    if project_name:
        sections = _filter_journal_sections_by_project(sections, project_name)

    want_dates = set(_dates_in_iso_week(target_day))
    selected = {d: lines for d, lines in sections.items() if d in want_dates}
    
    if not selected:
        # Fallback: get recent entries
        all_dates = list(sections.keys())
        last7 = all_dates[-7:]
        selected = {d: sections[d] for d in last7}
    
    return selected


def _get_meeting_data_for_week(project_wikis_dir: Path, project_name: Optional[str], target_day: date) -> List[Dict]:
    """Get meeting data (transcripts, decisions, actions) for the specified week and project."""
    if not project_name:
        return []
    
    try:
        # Get meetings from the week
        index = meeting_index_builder.build_project_index(project_name, force_rebuild=False)
        week_dates = set(_dates_in_iso_week(target_day))
        
        week_meetings = []
        for meeting in index.meetings:
            if meeting.date in week_dates:
                week_meetings.append({
                    'meeting_name': meeting.meeting_name,
                    'date': meeting.date,
                    'decisions': meeting.decisions,
                    'action_items': meeting.action_items,
                    'risks': meeting.risks,
                    'open_questions': meeting.open_questions,
                    'transcript': meeting.full_transcript[:2000] if meeting.full_transcript else "",  # First 2000 chars
                })
        
        return week_meetings
    except Exception as e:
        logger.warning(f"Failed to get meeting data for {project_name}: {e}")
        return []


def _empty_weekly_summary() -> Dict[str, object]:
    """Return an empty weekly summary structure."""
    return {
        "dates": [],
        "accomplished": [],
        "next_week": [],
        "topics": [],
        "exec_summary": "No activity recorded for this week.",
        "challenges": [],
        "metrics": []
    }


def _generate_ai_weekly_summary(journal_data: Dict[str, List[str]], meeting_data: List[Dict], 
                                project_name: Optional[str], target_day: date) -> Dict[str, object]:
    """Generate a rich AI-powered weekly summary from journal and meeting data."""
    
    # Collect all available data
    all_text_content = []
    raw_decisions = []
    raw_actions = []
    raw_risks = []
    raw_questions = []
    
    # Extract from journal entries
    for date_str, lines in journal_data.items():
        content = "".join(lines).strip()
        if content:
            all_text_content.append(f"Journal {date_str}: {content}")
    
    # Extract from meeting data
    for meeting in meeting_data:
        if meeting['transcript']:
            all_text_content.append(f"Meeting '{meeting['meeting_name']}' ({meeting['date']}): {meeting['transcript']}")
        raw_decisions.extend(meeting['decisions'])
        raw_actions.extend(meeting['action_items'])
        raw_risks.extend(meeting['risks'])
        raw_questions.extend(meeting['open_questions'])
    
    if not all_text_content and not raw_decisions and not raw_actions:
        return _empty_weekly_summary()
    
    # Combine all content for AI processing
    combined_content = "\n\n".join(all_text_content)
    iso_year, iso_week, _ = target_day.isocalendar()
    
    # Generate AI-powered executive summary
    try:
        exec_summary = _generate_executive_narrative(
            combined_content, raw_decisions, raw_actions, raw_risks, 
            project_name, f"{iso_year}-W{iso_week:02d}"
        )
    except Exception as e:
        logger.warning(f"Failed to generate AI executive summary: {e}")
        exec_summary = f"Weekly activity for {project_name or 'project'} during week {iso_year}-W{iso_week:02d}. Review meeting notes and journal entries for detailed progress updates."
    
    # Extract enhanced accomplishments and plans
    accomplished = _extract_detailed_accomplishments(raw_decisions, raw_actions, combined_content)
    next_week = _extract_detailed_plans(raw_actions, raw_questions, combined_content)
    challenges = _extract_challenges(raw_risks, raw_questions, combined_content)
    
    # Extract topics and dates
    dates = sorted(journal_data.keys()) if journal_data else [meeting['date'] for meeting in meeting_data]
    topics = _extract_topics(combined_content, raw_decisions, raw_actions)

    return {
        "dates": dates,
        "accomplished": accomplished,
        "next_week": next_week,
        "topics": topics,
        "exec_summary": exec_summary,
        "challenges": challenges,
        "metrics": []  # TODO: Could extract metrics from content
    }


def _generate_executive_narrative(content: str, decisions: List[str], actions: List[str], 
                                 risks: List[str], project_name: Optional[str], week_str: str) -> str:
    """Generate a rich executive narrative summary using AI."""
    try:
        generator = SuggestionGenerator()
        
        # Create a comprehensive prompt for executive summary generation
        prompt = f"""
Based on the following project activity data, generate a professional executive summary paragraph (3-5 sentences) for {project_name or 'the project'} for {week_str}.

The summary should:
- Sound professional and executive-friendly
- Highlight key progress and strategic direction
- Mention specific accomplishments and their business impact
- Note any challenges or strategic pivots
- Include forward-looking statements about next steps
- Use confident, professional tone similar to corporate status updates

Activity Data:
{content[:3000]}

Key Decisions Made:
{chr(10).join(f'- {d}' for d in decisions[:10])}

Action Items:
{chr(10).join(f'- {a}' for a in actions[:10])}

Risks/Issues:
{chr(10).join(f'- {r}' for r in risks[:5])}

Generate a compelling executive summary paragraph:"""

        # Use the suggestion backend to generate narrative text
        suggestions = generator.generate(prompt)
        narrative = suggestions.recap if suggestions.recap else suggestions.decisions[0] if suggestions.decisions else ""
        
        if narrative and len(narrative) > 50:
            return narrative
        else:
            # Fallback to structured summary
            return _create_fallback_executive_summary(decisions, actions, project_name, week_str)
            
    except (SuggestionUnavailable, Exception) as e:
        logger.warning(f"AI narrative generation failed: {e}")
        return _create_fallback_executive_summary(decisions, actions, project_name, week_str)


def _create_fallback_executive_summary(decisions: List[str], actions: List[str], 
                                     project_name: Optional[str], week_str: str) -> str:
    """Create a structured executive summary when AI generation fails."""
    project = project_name or "the project"
    summary_parts = [f"This week, {project} advanced on multiple fronts."]
    
    if decisions:
        summary_parts.append(f"Key decisions included {', '.join(decisions[:2])}")
        if len(decisions) > 2:
            summary_parts[-1] += f" and {len(decisions) - 2} other strategic determinations"
        summary_parts[-1] += "."
    
    if actions:
        summary_parts.append(f"The team is actively pursuing {len(actions)} action items to maintain momentum.")
    
    summary_parts.append("Progress continues toward project objectives with ongoing coordination and planning.")
    
    return " ".join(summary_parts)


def _extract_detailed_accomplishments(decisions: List[str], actions: List[str], content: str) -> List[str]:
    """Extract detailed accomplishments with context."""
    accomplishments = []
    
    # Add decisions as accomplishments (these are things that were resolved/decided)
    for decision in decisions[:8]:
        accomplishments.append(f"Finalized {decision.lower()}")
    
    # Look for completed actions in content
    content_lower = content.lower()
    completed_indicators = ["completed", "finished", "resolved", "implemented", "delivered", "deployed"]
    
    for action in actions:
        for indicator in completed_indicators:
            if indicator in action.lower():
                accomplishments.append(f"Successfully {action.lower()}")
                break
    
    # Extract from content directly
    import re
    accomplishment_patterns = [
        r"completed ([^.]+)",
        r"finished ([^.]+)", 
        r"implemented ([^.]+)",
        r"delivered ([^.]+)",
        r"resolved ([^.]+)",
        r"successfully ([^.]+)"
    ]
    
    for pattern in accomplishment_patterns:
        matches = re.findall(pattern, content_lower)
        for match in matches[:3]:
            if len(match) > 10 and len(match) < 150:
                accomplishments.append(f"Successfully {match.strip()}")
    
    return accomplishments[:10]  # Limit to top 10


def _extract_detailed_plans(actions: List[str], questions: List[str], content: str) -> List[str]:
    """Extract detailed next week plans with context."""
    plans = []
    
    # Add action items as next week plans
    for action in actions[:8]:
        if not any(indicator in action.lower() for indicator in ["completed", "finished", "resolved"]):
            plans.append(action)
    
    # Add open questions as investigation items
    for question in questions[:5]:
        plans.append(f"Investigate and resolve: {question.lower()}")
    
    # Extract future-oriented items from content
    import re
    future_patterns = [
        r"will ([^.]+)",
        r"plan to ([^.]+)",
        r"next week ([^.]+)",
        r"upcoming ([^.]+)",
        r"scheduled ([^.]+)"
    ]
    
    content_lower = content.lower()
    for pattern in future_patterns:
        matches = re.findall(pattern, content_lower)
        for match in matches[:3]:
            if len(match) > 10 and len(match) < 150:
                plans.append(f"Continue to {match.strip()}")
    
    return plans[:10]  # Limit to top 10


def _extract_challenges(risks: List[str], questions: List[str], content: str) -> List[str]:
    """Extract challenges and issues that need attention."""
    challenges = []
    
    # Add risks as challenges
    for risk in risks[:5]:
        challenges.append(f"Mitigate risk: {risk}")
    
    # Add unresolved questions as challenges
    for question in questions[:3]:
        challenges.append(f"Address open question: {question}")
    
    # Extract challenge indicators from content
    import re
    challenge_patterns = [
        r"challenge ([^.]+)",
        r"issue ([^.]+)",
        r"problem ([^.]+)",
        r"concern ([^.]+)",
        r"blocker ([^.]+)"
    ]
    
    content_lower = content.lower()
    for pattern in challenge_patterns:
        matches = re.findall(pattern, content_lower)
        for match in matches[:2]:
            if len(match) > 10 and len(match) < 150:
                challenges.append(f"Address {match.strip()}")
    
    return challenges[:8]  # Limit to top 8


def _extract_topics(content: str, decisions: List[str], actions: List[str]) -> List[str]:
    """Extract key topics discussed."""
    topics = []
    
    # Extract from decisions and actions
    for item in decisions + actions:
        # Simple topic extraction - could be enhanced
        words = item.split()
        if len(words) >= 2:
            topics.append(" ".join(words[:4]))  # First few words as topic
    
    # Extract from content using keyword frequency
    import re
    words = re.findall(r'\b[A-Za-z]{4,}\b', content)
    word_freq = {}
    stop_words = {'this', 'that', 'with', 'from', 'they', 'were', 'been', 'have', 'will', 'would', 'could', 'should'}
    
    for word in words:
        word_lower = word.lower()
        if word_lower not in stop_words and len(word) > 3:
            word_freq[word_lower] = word_freq.get(word_lower, 0) + 1
    
    # Get top keywords as topics
    top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    topics.extend([keyword.title() for keyword, freq in top_keywords if freq > 1])
    
    return list(set(topics))[:12]  # Remove duplicates, limit to 12



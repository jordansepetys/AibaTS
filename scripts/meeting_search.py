#!/usr/bin/env python3
"""
Meeting Search Tool

Command-line interface for searching and managing meeting indexes.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

# Add the parent directory to Python path to import from services
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.meeting_index import meeting_index_builder, MeetingIndexEntry
from services.project_manager import project_manager


def build_index_command(args) -> None:
    """Build or rebuild meeting index for a project."""
    project_name = args.project
    force_rebuild = args.force
    
    print(f"Building meeting index for project: {project_name}")
    
    try:
        index = meeting_index_builder.build_project_index(project_name, force_rebuild=force_rebuild)
        
        print(f"✅ Index built successfully!")
        print(f"   📁 Project: {index.project_name}")
        print(f"   📊 Total meetings: {index.total_meetings}")
        print(f"   📅 Last updated: {index.updated_at}")
        
        if index.meetings:
            print(f"   📝 Latest meeting: {index.meetings[0].meeting_name} ({index.meetings[0].date})")
        
    except Exception as e:
        print(f"❌ Error building index: {e}")
        sys.exit(1)


def search_meetings_command(args) -> None:
    """Search meetings in a project."""
    project_name = args.project
    query = args.query
    max_results = args.limit
    
    print(f"Searching meetings in project '{project_name}' for: '{query}'")
    print("=" * 60)
    
    try:
        results = meeting_index_builder.search_index(project_name, query, max_results)
        
        if not results:
            print("No matches found.")
            return
        
        print(f"Found {len(results)} matching meetings:\n")
        
        for i, meeting in enumerate(results, 1):
            print(f"{i}. {meeting.meeting_name}")
            print(f"   📅 Date: {meeting.date}")
            print(f"   🏷️  Project: {meeting.project_name}")
            print(f"   📝 Words: {meeting.word_count:,}")
            
            # Show matching content highlights
            if meeting.decisions:
                print(f"   ✅ Decisions: {len(meeting.decisions)}")
                for decision in meeting.decisions[:2]:  # Show first 2
                    if query.lower() in decision.lower():
                        print(f"      • {decision[:100]}{'...' if len(decision) > 100 else ''}")
            
            if meeting.action_items:
                print(f"   🎯 Actions: {len(meeting.action_items)}")
                for action in meeting.action_items[:2]:  # Show first 2
                    if query.lower() in action.lower():
                        print(f"      • {action[:100]}{'...' if len(action) > 100 else ''}")
            
            if meeting.risks:
                print(f"   ⚠️  Risks: {len(meeting.risks)}")
                for risk in meeting.risks[:2]:  # Show first 2
                    if query.lower() in risk.lower():
                        print(f"      • {risk[:100]}{'...' if len(risk) > 100 else ''}")
            
            # Show transcript snippet if query matches
            if query.lower() in meeting.full_transcript.lower():
                # Find the first occurrence
                pos = meeting.full_transcript.lower().find(query.lower())
                start = max(0, pos - 50)
                end = min(len(meeting.full_transcript), pos + len(query) + 50)
                snippet = meeting.full_transcript[start:end]
                print(f"   💬 Transcript: ...{snippet}...")
            
            print(f"   📁 Files: {meeting.json_file_path}")
            if meeting.transcript_file_path:
                print(f"             {meeting.transcript_file_path}")
            print()
        
    except Exception as e:
        print(f"❌ Error searching meetings: {e}")
        sys.exit(1)


def list_projects_command(args) -> None:
    """List all projects with indexes."""
    print("Projects with meeting indexes:")
    print("=" * 40)
    
    try:
        projects = project_manager.list_projects()
        
        if not projects:
            print("No projects found.")
            return
        
        for project in projects:
            project_dir = project_manager.get_project_dir(project)
            index_path = project_dir / "meetings_index.json"
            
            if index_path.exists():
                try:
                    with open(index_path, 'r', encoding='utf-8') as f:
                        index_data = json.load(f)
                    
                    meeting_count = index_data.get("total_meetings", 0)
                    last_updated = index_data.get("updated_at", "unknown")
                    
                    print(f"📁 {project}")
                    print(f"   📊 Meetings: {meeting_count}")
                    print(f"   📅 Updated: {last_updated}")
                    print()
                except Exception as e:
                    print(f"📁 {project} (⚠️ index error: {e})")
            else:
                print(f"📁 {project} (no index)")
    
    except Exception as e:
        print(f"❌ Error listing projects: {e}")
        sys.exit(1)


def show_meeting_command(args) -> None:
    """Show detailed information about a specific meeting."""
    project_name = args.project
    meeting_id = args.meeting_id
    
    print(f"Meeting details for {meeting_id} in project '{project_name}':")
    print("=" * 60)
    
    try:
        # Load the index
        index_path = project_manager.get_project_dir(project_name) / "meetings_index.json"
        if not index_path.exists():
            print(f"❌ No index found for project '{project_name}'. Run 'build' command first.")
            sys.exit(1)
        
        with open(index_path, 'r', encoding='utf-8') as f:
            index_data = json.load(f)
        
        # Find the meeting
        meeting = None
        for meeting_data in index_data.get("meetings", []):
            if meeting_data["meeting_id"] == meeting_id:
                meeting = MeetingIndexEntry(**meeting_data)
                break
        
        if not meeting:
            print(f"❌ Meeting '{meeting_id}' not found in project '{project_name}'.")
            sys.exit(1)
        
        # Display detailed information
        print(f"📝 Meeting: {meeting.meeting_name}")
        print(f"📅 Date: {meeting.date}")
        print(f"🏷️  Project: {meeting.project_name}")
        print(f"📊 Word count: {meeting.word_count:,}")
        print(f"🏷️  Keywords: {', '.join(meeting.keywords[:10])}")
        print()
        
        if meeting.decisions:
            print(f"✅ Decisions ({len(meeting.decisions)}):")
            for i, decision in enumerate(meeting.decisions, 1):
                print(f"   {i}. {decision}")
            print()
        
        if meeting.action_items:
            print(f"🎯 Action Items ({len(meeting.action_items)}):")
            for i, action in enumerate(meeting.action_items, 1):
                print(f"   {i}. {action}")
            print()
        
        if meeting.risks:
            print(f"⚠️  Risks ({len(meeting.risks)}):")
            for i, risk in enumerate(meeting.risks, 1):
                print(f"   {i}. {risk}")
            print()
        
        if meeting.open_questions:
            print(f"❓ Open Questions ({len(meeting.open_questions)}):")
            for i, question in enumerate(meeting.open_questions, 1):
                print(f"   {i}. {question}")
            print()
        
        print(f"📁 JSON file: {meeting.json_file_path}")
        if meeting.transcript_file_path:
            print(f"📄 Transcript: {meeting.transcript_file_path}")
        
        if args.show_transcript and meeting.full_transcript:
            print("\n" + "=" * 60)
            print("FULL TRANSCRIPT:")
            print("=" * 60)
            print(meeting.full_transcript)
    
    except Exception as e:
        print(f"❌ Error showing meeting: {e}")
        sys.exit(1)


def main():
    """Main entry point for the meeting search tool."""
    parser = argparse.ArgumentParser(
        description="Meeting Search Tool - Search and manage meeting indexes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build index for a project
  python meeting_search.py build MyProject
  
  # Search meetings
  python meeting_search.py search MyProject "action items"
  python meeting_search.py search MyProject "decision timeline" --limit 5
  
  # List all projects
  python meeting_search.py projects
  
  # Show specific meeting
  python meeting_search.py show MyProject meeting_1754944813_notes
  python meeting_search.py show MyProject meeting_1754944813_notes --transcript
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Build index command
    build_parser = subparsers.add_parser('build', help='Build or rebuild meeting index for a project')
    build_parser.add_argument('project', help='Project name')
    build_parser.add_argument('--force', action='store_true', 
                            help='Force rebuild entire index (default: incremental update)')
    
    # Search meetings command
    search_parser = subparsers.add_parser('search', help='Search meetings in a project')
    search_parser.add_argument('project', help='Project name')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--limit', type=int, default=20, 
                             help='Maximum number of results (default: 20)')
    
    # List projects command
    list_parser = subparsers.add_parser('projects', help='List all projects with indexes')
    
    # Show meeting command
    show_parser = subparsers.add_parser('show', help='Show detailed information about a specific meeting')
    show_parser.add_argument('project', help='Project name')
    show_parser.add_argument('meeting_id', help='Meeting ID (e.g., meeting_1754944813_notes)')
    show_parser.add_argument('--transcript', action='store_true', 
                           help='Show full transcript', dest='show_transcript')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Route to appropriate command handler
    if args.command == 'build':
        build_index_command(args)
    elif args.command == 'search':
        search_meetings_command(args)
    elif args.command == 'projects':
        list_projects_command(args)
    elif args.command == 'show':
        show_meeting_command(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()







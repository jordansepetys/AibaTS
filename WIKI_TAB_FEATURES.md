# Wiki Tab Implementation

## Overview

Added a new "Wiki" tab to the AibaTS Desktop application with full markdown viewing and editing capabilities.

## Features Implemented

### ✅ **Tab Structure**
- **Recording Tab**: Contains the original meeting recording and processing interface
- **Wiki Tab**: New tab for viewing and editing project wikis

### ✅ **Markdown Viewer**
- Uses `QTextBrowser` with HTML rendering
- Converts markdown to HTML using `markdown2` library
- Supports:
  - Headers, lists, links
  - Fenced code blocks
  - Tables
  - External link opening

### ✅ **Edit Mode Toggle**
- **Checkbox**: "Edit Mode" to switch between view and edit
- **View Mode**: Displays rendered markdown as HTML
- **Edit Mode**: Shows raw markdown in a `QTextEdit` textarea

### ✅ **Save & Refresh Controls**
- **Save Changes Button**: Visible only in edit mode
- **Refresh Button**: Reloads content from file
- **Status Updates**: Shows "Saved" status after successful saves

### ✅ **Project Integration**
- **Automatic Loading**: Loads wiki when switching to Wiki tab
- **Project Awareness**: Shows wiki for currently selected project
- **Dual Structure Support**: 
  - New structure: `./projects/{ProjectName}/wiki.md`
  - Legacy structure: `./meeting_data_v2/project_wikis/{ProjectName}_wiki.md`

## User Interface

### Wiki Tab Layout
```
[Edit Mode ☐]                    [Refresh] [Save Changes]
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  Markdown Content (Rendered HTML or Raw Text Editor)   │
│                                                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Controls

1. **Edit Mode Checkbox**
   - Unchecked: Shows rendered HTML view
   - Checked: Shows raw markdown editor + Save button

2. **Refresh Button**
   - Reloads wiki content from disk
   - Shows confirmation message

3. **Save Changes Button**
   - Only visible in edit mode
   - Saves editor content to wiki file
   - Updates status and shows confirmation

## Workflow

### Viewing Wiki
1. Select project in Recording tab
2. Click Wiki tab
3. View rendered markdown content

### Editing Wiki  
1. In Wiki tab, check "Edit Mode"
2. Edit raw markdown in textarea
3. Click "Save Changes"
4. Uncheck "Edit Mode" to view rendered result

### Refreshing Content
1. Click "Refresh" button
2. Content reloads from file (useful if file changed externally)

## Technical Implementation

### Dependencies
- **`markdown2`**: For markdown to HTML conversion
- **`QTextBrowser`**: For HTML rendering with link support
- **`QTextEdit`**: For raw markdown editing
- **`QTabWidget`**: For tab interface

### Key Methods

- **`_setup_wiki_tab()`**: Initializes Wiki tab UI
- **`_load_wiki_content()`**: Loads and renders wiki content
- **`_on_edit_mode_toggled()`**: Handles view/edit mode switching
- **`_on_wiki_save()`**: Saves changes and updates view
- **`_on_wiki_refresh()`**: Reloads content from file
- **`_on_tab_changed()`**: Loads wiki when tab is activated

### File Path Resolution
1. **Try New Structure**: `./projects/{ProjectName}/wiki.md`
2. **Fallback to Legacy**: `./meeting_data_v2/project_wikis/{ProjectName}_wiki.md`
3. **Auto-Create**: Creates new project structure if saving to non-existent project

## Integration with Existing Features

### Project Management
- Uses existing project dropdown from Recording tab
- Integrates with `project_manager` for new project structure
- Maintains compatibility with legacy wiki files

### Status System
- Uses existing `AppStatus` enum for status updates
- Shows "Saved" status after successful wiki saves
- Shows "Error" status if save fails

### Error Handling
- Graceful handling of missing wiki files
- Clear error messages for file access issues
- Fallback content for empty states

## File Structure Impact

The Wiki tab works with both project structures:

### New Structure (Preferred)
```
./projects/
└── ProjectName/
    ├── wiki.md          ← Editable via Wiki tab
    └── meetings/
```

### Legacy Structure (Fallback)
```
./meeting_data_v2/
└── project_wikis/
    └── ProjectName_wiki.md    ← Editable via Wiki tab
```

## Benefits

1. **Integrated Editing**: Edit wikis without leaving the application
2. **Live Preview**: Switch between markdown source and rendered view
3. **Project Awareness**: Always shows the right wiki for selected project
4. **Backward Compatible**: Works with existing wiki files
5. **Rich Rendering**: Supports all markdown features including tables and code
6. **Auto-Refresh**: Easy to reload if files change externally

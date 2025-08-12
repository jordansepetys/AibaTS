# Wiki Search Functionality

## Overview

Added comprehensive search functionality to the Wiki tab with real-time search, highlighting, and navigation between matches.

## Features Implemented

### ✅ **Search Bar at Top of Wiki Tab**
- **Location**: Positioned at the very top of the Wiki tab
- **Input Field**: Text input with placeholder "Search wiki content..."
- **Live Search**: Searches as you type with 300ms debouncing

### ✅ **Match Count Display**
- **Format**: Shows "current/total" (e.g., "3/7")
- **Updates**: Real-time as you type
- **Position**: Next to the search input

### ✅ **Navigation Controls**
- **Previous Button**: Navigate to previous match
- **Next Button**: Navigate to next match
- **Circular Navigation**: Wraps from last to first match
- **Enable/Disable**: Buttons are disabled when no matches or only one match

### ✅ **Text Highlighting**
- **View Mode**: Uses HTML `<mark>` tags with yellow background
- **Edit Mode**: Uses text cursor selection with yellow background
- **Case Insensitive**: Finds matches regardless of case
- **Real-time**: Updates highlighting as you type

### ✅ **Debounced Search**
- **Delay**: 300ms debounce to avoid excessive searching
- **Performance**: Efficient for large wiki files
- **Clear**: Immediately clears search when input is empty

## User Interface

### Search Bar Layout
```
┌─────────────────────────────────────────────────────────────────┐
│ Search: [search input field..................] 3/7 [Prev] [Next] │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ [Edit Mode ☐]                    [Refresh] [Save Changes]        │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Wiki Content (with highlighted search matches)                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

### 1. **Search Input**
- Type in the search field
- 300ms delay before search executes
- Case-insensitive matching
- Regex-based pattern matching with escaping

### 2. **Match Finding**
- Uses `re.finditer()` to find all matches
- Stores start and end positions of each match
- Updates count display immediately

### 3. **Highlighting**
- **View Mode**: Injects `<mark>` tags into HTML content
- **Edit Mode**: Uses `QTextCursor` selection with background color
- **Auto-scroll**: Scrolls to show current match

### 4. **Navigation**
- **Previous/Next**: Cycles through matches
- **Current Index**: Tracks which match is active
- **Visual Update**: Re-highlights and scrolls to current match

## Technical Implementation

### Core Components

1. **Search Timer** (`QTimer`):
   ```python
   self.search_timer = QTimer()
   self.search_timer.setSingleShot(True)
   self.search_timer.timeout.connect(self._perform_search)
   ```

2. **Search State Variables**:
   ```python
   self.search_matches = []          # List of (start, end) positions
   self.current_match_index = -1     # Current match index
   self.current_search_term = ""     # Current search term
   ```

3. **Key Methods**:
   - `_on_search_text_changed()`: Handles input changes with debouncing
   - `_perform_search()`: Executes the actual search
   - `_highlight_matches()`: Applies highlighting to matches
   - `_go_to_current_match()`: Scrolls to current match
   - `_on_previous_match()` / `_on_next_match()`: Navigation

### Highlighting Strategies

#### In View Mode (QTextBrowser):
```python
pattern = re.compile(f'({re.escape(search_term)})', re.IGNORECASE)
highlighted_html = pattern.sub(r'<mark style="background-color: yellow;">\1</mark>', html_content)
self.wiki_viewer.setHtml(highlighted_html)
```

#### In Edit Mode (QTextEdit):
```python
format = QTextCharFormat()
format.setBackground(QColor(255, 255, 0, 128))  # Yellow background
cursor.setPosition(start)
cursor.setPosition(end, QTextDocument.FindFlag.KeepAnchor)
cursor.mergeCharFormat(format)
```

## Integration with Existing Features

### Edit Mode Toggle
- **Clears Search**: When switching between view/edit modes
- **Maintains State**: Search term is preserved in input field
- **Re-search**: Can search again after mode switch

### Content Loading
- **Auto-clear**: Search is cleared when loading new wiki content
- **Refresh**: Search is cleared when refreshing content
- **Project Change**: Search is cleared when switching projects

### Error Handling
- **Empty Content**: Gracefully handles empty wikis
- **Invalid Regex**: Escapes special characters in search terms
- **Performance**: Efficient for large documents with many matches

## Benefits

1. **Enhanced Usability**: Quickly find specific content in long wikis
2. **Visual Feedback**: Clear highlighting shows all matches
3. **Efficient Navigation**: Easy to jump between multiple matches
4. **Real-time Search**: Immediate feedback as you type
5. **Mode Compatibility**: Works in both view and edit modes
6. **Performance Optimized**: Debounced search prevents excessive processing

## Usage Examples

### Finding Meeting Dates
1. Type "2025-08-11" in search
2. See count: "1/3" (found 3 matches)
3. Use Previous/Next to navigate between dates

### Finding Action Items
1. Type "action" in search
2. All instances highlighted in yellow
3. Navigate through each occurrence

### Searching Code or Technical Terms
1. Type specific technical terms
2. Case-insensitive matching finds all variations
3. Clear visual indication of match locations

The search functionality provides a powerful way to navigate and explore wiki content efficiently, making the Wiki tab much more useful for finding specific information quickly.

# Quick Query Feature

## Overview

The Quick Query feature allows users to ask natural language questions about their meetings and get intelligent, contextual results. Instead of remembering exact keywords, users can ask questions like "When did we decide to use SQL?" or "What did Sarah discuss about authentication?" and get relevant meeting excerpts with links.

## User Interface

### Location
The Quick Query section is located in the **Wiki tab**, positioned between the search bar and the main wiki content area.

### Components
```
┌─────────────────────────────────────────────────────────────────┐
│ Quick Query - Ask natural language questions about meetings:    │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ e.g. "When did we decide to use SQL?" or "What did Sarah...│ │[Ask]
│ └─────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │                   Results Area                              │ │
│ │  (appears when queries are made)                            │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Natural Language Processing

### Intent Recognition
The system automatically detects what users are looking for:

- **Decisions**: "When did we decide...", "What was agreed..."
- **Discussions**: "What did we discuss...", "Was X mentioned..."
- **Actions**: "Show me action items...", "Who was assigned..."
- **Risks**: "What risks were identified...", "Are there blockers..."
- **Questions**: "What questions came up...", "What was unclear..."
- **Status**: "What's the status of...", "How is X progressing..."

### Keyword Extraction
Automatically extracts meaningful terms while filtering out:
- Stop words (the, and, or, etc.)
- Question words (what, when, where, etc.)
- Common meeting terms (discuss, talk, mention, etc.)

### People Recognition
Identifies names in queries:
- "What did **Sarah** discuss about authentication?"
- "Show me **Mike's** action items"
- "Who assigned the task to **John**?"

### Temporal Context
Understands time references:
- "last week", "recently", "yesterday"
- "this month", "latest", "recent"

## Query Examples

### Decision Queries
```
✅ "When did we decide to use SQL?"
✅ "What decisions were made about the timeline?"
✅ "Did we agree on the API approach?"
✅ "What was decided about the database?"
```

### Discussion Queries
```
💬 "What did we discuss about authentication?"
💬 "Was security mentioned in any meetings?"
💬 "What was talked about regarding performance?"
💬 "Did anyone mention the new framework?"
```

### Action Item Queries
```
🎯 "Show me Sarah's action items"
🎯 "What tasks were assigned to the backend team?"
🎯 "Who is responsible for testing?"
🎯 "What do I need to do before Friday?"
```

### Risk & Issue Queries
```
⚠️ "What risks were identified?"
⚠️ "Are there any blockers mentioned?"
⚠️ "What concerns came up about the timeline?"
⚠️ "Were any issues discussed?"
```

### People-Specific Queries
```
👤 "What did Mike work on last week?"
👤 "Show me all mentions of Jennifer"
👤 "What tasks are assigned to the QA team?"
👤 "Who was responsible for the database migration?"
```

## Result Format

### Result Structure
Each result shows:
- **Meeting name and date**
- **Project and word count**
- **Relevant excerpts** based on query intent
- **Links to full meeting** in wiki

### Example Result
```html
📋 Meeting 2025-08-11 16:40
📅 2025-08-11 | 🏷️ AIPlatform | 📝 3,865 words

Decision: QA is wrapping up by the end of the week, specifically by 8-15.
Action Item: Reopen the chat and inform that this is the last week in QA.

📁 View in Wiki | 📄 meeting_data_v2/json_notes/meeting_1754944813_notes.json
```

## Technical Implementation

### Query Processing Pipeline
1. **Parse Query** → Extract intent, keywords, people, temporal context
2. **Build Search** → Convert to search terms for the meeting index
3. **Search Index** → Find matching meetings using relevance scoring
4. **Filter Results** → Apply context-based filtering (intent, people, etc.)
5. **Extract Excerpts** → Pull relevant snippets from decisions, actions, risks, etc.
6. **Format Display** → Create HTML with excerpts and links

### Relevance Scoring
Results are ranked by:
- **Intent matching**: 10x boost for matching content type
- **People mentions**: 5x boost for mentioned names
- **Keyword density**: Based on frequency and field importance
- **Field weighting**: Decisions 2.5x, Actions 2.5x, Risks 2.0x, etc.

### Performance Features
- **Fast response**: Pre-built indexes for instant results
- **Smart excerpts**: Contextual text snippets around keywords
- **Result limiting**: Top 10 results with overflow indication
- **Error handling**: Graceful fallbacks for edge cases

## Integration

### With Meeting Index
- Leverages the existing meeting index system
- Supports all indexed projects automatically
- Works with both old and new file structures

### With Wiki Tab
- Seamlessly integrated into existing Wiki interface
- Doesn't interfere with regular search functionality
- Results area appears/disappears as needed

### With Search
- Complements existing text search
- Uses same underlying meeting data
- Provides different interaction model

## Usage Patterns

### Exploratory Queries
Users can explore meeting history without knowing exact terms:
```
"What have we been working on lately?"
"Are there any outstanding issues?"
"What decisions are pending?"
```

### Specific Information Retrieval
Target specific information quickly:
```
"When did we decide on the deployment schedule?"
"What testing strategy did we agree on?"
"Who is handling the database migration?"
```

### Follow-up and Context
Build on previous discussions:
```
"What was the outcome of the security review?"
"Did we resolve the performance issues?"
"What next steps were identified?"
```

### Assignment and Responsibility Tracking
Track who's doing what:
```
"What is John responsible for?"
"What tasks are assigned to the frontend team?"
"Who owns the API documentation?"
```

## Error Handling

### No Results
```
"No meetings found for 'your query'. Try different keywords 
or check if the project has meetings indexed."
```

### Invalid Queries
```
"No searchable terms found in your query. Try asking about 
specific topics, people, or decisions."
```

### System Errors
```
"Error processing query: [specific error message]"
```

## Future Enhancements

### Potential Improvements
- **AI-powered parsing**: Use LLMs for better intent understanding
- **Semantic search**: Vector-based similarity matching
- **Query suggestions**: Auto-complete and suggested queries
- **Export results**: Save query results to files
- **Query history**: Remember and reuse previous queries

### Advanced Features
- **Cross-project search**: Search across multiple projects
- **Date filtering**: "Show me decisions from last month"
- **Follow-up questions**: "Tell me more about that decision"
- **Smart notifications**: "Alert me when X is discussed"

## Benefits

### For Users
- **Natural interaction**: Ask questions in plain English
- **Fast discovery**: Find information without manual searching
- **Context awareness**: Get relevant excerpts, not just matches
- **Easy access**: Direct links to full meeting content

### For Teams
- **Knowledge retention**: Never lose track of important decisions
- **Accountability**: Easy to find who was assigned what
- **History tracking**: Understand how decisions evolved
- **Onboarding**: New team members can quickly understand context

### For Projects
- **Decision audit**: Track all project decisions over time
- **Risk monitoring**: Keep tabs on identified risks and issues
- **Action tracking**: Monitor task assignments and progress
- **Meeting ROI**: Make meeting content more accessible and useful

The Quick Query feature transforms static meeting archives into an intelligent, searchable knowledge base that teams can interact with naturally and efficiently.

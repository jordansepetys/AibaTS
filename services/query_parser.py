"""
Natural Language Query Parser for Meeting Searches

Parses natural language queries and converts them to search parameters
for finding relevant meeting information.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from loguru import logger


@dataclass
class QueryContext:
    """Parsed query context with extracted information."""
    keywords: List[str]
    dates: List[str]  # Date strings found in query
    people: List[str]  # Names found in query
    intent: str  # What the user is looking for (decision, discussion, action, etc.)
    temporal: Optional[str]  # Time-related context (recent, last week, etc.)
    original_query: str


class NaturalLanguageQueryParser:
    """Parses natural language queries for meeting search."""
    
    def __init__(self):
        # Common intent patterns
        self.intent_patterns = {
            'decision': [
                r'\b(decide|decided|decision|chose|choice|agreed|agreement)\b',
                r'\bwhen did we (decide|choose|agree)\b',
                r'\bwhat did we (decide|choose|agree)\b'
            ],
            'discussion': [
                r'\b(discuss|discussed|discussion|talk|talked|mention|mentioned)\b',
                r'\bwhat did we (discuss|talk about|mention)\b',
                r'\bwhat was (discussed|mentioned|talked about)\b'
            ],
            'action': [
                r'\b(action|task|todo|assigned|assignment|responsibility)\b',
                r'\bwho (is|was) (assigned|responsible)\b',
                r'\b(action items?|tasks?|todos?)\b'
            ],
            'risk': [
                r'\b(risk|issue|problem|concern|blocker|challenge)\b',
                r'\bwhat (risks?|issues?|problems?|concerns?)\b'
            ],
            'question': [
                r'\b(question|asked|unclear|unknown)\b',
                r'\bwhat (questions?|was asked)\b'
            ],
            'status': [
                r'\b(status|progress|update|state|complete|done)\b',
                r'\bwhat.{0,20}(status|progress|state)\b'
            ]
        }
        
        # Common people name patterns (these could be expanded based on your team)
        self.name_patterns = [
            r'\b[A-Z][a-z]+\b',  # Capitalized words (potential names)
        ]
        
        # Date/time patterns
        self.temporal_patterns = {
            'recent': [r'\b(recent|recently|latest|last)\b'],
            'week': [r'\b(last week|this week|week)\b'],
            'month': [r'\b(last month|this month|month)\b'],
            'today': [r'\b(today|earlier)\b'],
            'yesterday': [r'\byesterday\b']
        }
        
        # Common stop words to exclude from keywords
        self.stop_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'a', 'an', 'is', 'was', 'are', 'were', 'be', 'been', 'have', 'has',
            'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
            'can', 'what', 'when', 'where', 'why', 'how', 'who', 'which', 'that',
            'this', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'our', 'their',
            'about', 'up', 'out', 'if', 'so', 'than', 'now', 'just', 'only',
            'also', 'back', 'then', 'here', 'there', 'get', 'go', 'see', 'know',
            'think', 'want', 'need', 'like', 'use', 'work', 'make', 'take', 'come'
        }
    
    def parse(self, query: str) -> QueryContext:
        """Parse a natural language query into structured context."""
        query_lower = query.lower().strip()
        
        logger.debug(f"Parsing query: {query}")
        
        # Extract intent
        intent = self._extract_intent(query_lower)
        
        # Extract temporal context
        temporal = self._extract_temporal(query_lower)
        
        # Extract dates
        dates = self._extract_dates(query)
        
        # Extract people names
        people = self._extract_people(query)
        
        # Extract keywords (after removing intent and temporal words)
        keywords = self._extract_keywords(query_lower, intent, temporal)
        
        context = QueryContext(
            keywords=keywords,
            dates=dates,
            people=people,
            intent=intent,
            temporal=temporal,
            original_query=query
        )
        
        logger.debug(f"Parsed context: intent={intent}, keywords={keywords}, people={people}, temporal={temporal}")
        
        return context
    
    def _extract_intent(self, query: str) -> str:
        """Extract the primary intent from the query."""
        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return intent
        return 'general'
    
    def _extract_temporal(self, query: str) -> Optional[str]:
        """Extract temporal context from the query."""
        for temporal, patterns in self.temporal_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    return temporal
        return None
    
    def _extract_dates(self, query: str) -> List[str]:
        """Extract explicit dates from the query."""
        dates = []
        
        # Common date patterns
        date_patterns = [
            r'\b\d{4}-\d{2}-\d{2}\b',  # YYYY-MM-DD
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',  # MM/DD/YYYY
            r'\b\d{1,2}/\d{1,2}/\d{2}\b',  # MM/DD/YY
            r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b'
        ]
        
        for pattern in date_patterns:
            matches = re.findall(pattern, query, re.IGNORECASE)
            dates.extend(matches)
        
        return dates
    
    def _extract_people(self, query: str) -> List[str]:
        """Extract potential people names from the query."""
        people = []
        
        # Look for capitalized words that might be names
        words = query.split()
        for i, word in enumerate(words):
            # Remove punctuation
            clean_word = re.sub(r'[^\w]', '', word)
            
            # Check if it looks like a name (capitalized, not first word, not common words)
            if (clean_word and 
                clean_word[0].isupper() and 
                len(clean_word) > 1 and 
                clean_word.lower() not in self.stop_words and
                not clean_word.lower() in ['meeting', 'project', 'team', 'group']):
                
                # Additional context clues
                if i > 0:  # Not the first word
                    prev_word = words[i-1].lower()
                    if prev_word in ['said', 'mentioned', 'discussed', 'asked', 'suggested', 'told']:
                        people.append(clean_word)
                    elif "'s" in word:  # Possessive form
                        people.append(clean_word.replace("'s", ""))
        
        return list(set(people))  # Remove duplicates
    
    def _extract_keywords(self, query: str, intent: str, temporal: Optional[str]) -> List[str]:
        """Extract meaningful keywords from the query."""
        # Remove intent and temporal phrases first
        cleaned_query = query
        
        # Remove intent-related words
        for patterns in self.intent_patterns.values():
            for pattern in patterns:
                cleaned_query = re.sub(pattern, ' ', cleaned_query, flags=re.IGNORECASE)
        
        # Remove temporal words
        if temporal:
            for patterns in self.temporal_patterns.values():
                for pattern in patterns:
                    cleaned_query = re.sub(pattern, ' ', cleaned_query, flags=re.IGNORECASE)
        
        # Remove question words and common phrases
        question_patterns = [
            r'\bwhen did\b', r'\bwhat did\b', r'\bwho did\b', r'\bwhere did\b',
            r'\bhow did\b', r'\bwhy did\b', r'\bwhich\b', r'\bshow me\b',
            r'\btell me\b', r'\bfind\b', r'\bsearch\b', r'\blook for\b'
        ]
        
        for pattern in question_patterns:
            cleaned_query = re.sub(pattern, ' ', cleaned_query, flags=re.IGNORECASE)
        
        # Extract words
        words = re.findall(r'\b[a-zA-Z]{2,}\b', cleaned_query)
        
        # Filter out stop words and common meeting terms
        keywords = []
        for word in words:
            word_lower = word.lower()
            if (word_lower not in self.stop_words and 
                word_lower not in ['meeting', 'discuss', 'talk', 'mention'] and
                len(word) > 2):
                keywords.append(word_lower)
        
        return list(set(keywords))  # Remove duplicates


def build_search_query(context: QueryContext) -> str:
    """Build a search query string from parsed context."""
    query_parts = []
    
    # Add keywords
    if context.keywords:
        query_parts.extend(context.keywords)
    
    # Add people names (these are often very relevant)
    if context.people:
        query_parts.extend([name.lower() for name in context.people])
    
    # Combine into search string
    search_query = ' '.join(query_parts)
    
    logger.debug(f"Built search query: '{search_query}' from context")
    
    return search_query


def filter_results_by_context(results: List, context: QueryContext) -> List:
    """Filter search results based on the parsed context."""
    if not results:
        return results
    
    filtered = []
    
    for result in results:
        relevance_score = 0
        
        # Check intent matching
        if context.intent == 'decision' and result.decisions:
            relevance_score += 10
        elif context.intent == 'action' and result.action_items:
            relevance_score += 10
        elif context.intent == 'risk' and result.risks:
            relevance_score += 10
        elif context.intent == 'question' and result.open_questions:
            relevance_score += 10
        
        # Check for people mentions
        for person in context.people:
            if any(person.lower() in text.lower() for text in 
                   result.decisions + result.action_items + result.risks + result.open_questions + [result.full_transcript]):
                relevance_score += 5
        
        # Add to filtered results if relevant
        if relevance_score > 0 or context.intent == 'general':
            filtered.append((result, relevance_score))
    
    # Sort by relevance score (highest first)
    filtered.sort(key=lambda x: x[1], reverse=True)
    
    return [result for result, score in filtered]


# Global instance
query_parser = NaturalLanguageQueryParser()







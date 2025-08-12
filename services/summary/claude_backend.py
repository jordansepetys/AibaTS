"""Claude backend for structured summary generation."""

import json
import time
from typing import Optional
import os

import requests
from loguru import logger

from services.config import load_config
from services.summary.base import ISummaryBackend, MeetingSummary, SummaryUnavailable


class ClaudeSummaryBackend(ISummaryBackend):
    """Claude backend for generating structured meeting summaries."""
    
    def __init__(self) -> None:
        self._config = load_config()
        # Look for ANTHROPIC_API_KEY first, fall back to OPENAI_API_KEY for backward compatibility
        self._api_key = os.environ.get("ANTHROPIC_API_KEY") or self._config.openai_api_key
        self._endpoint = "https://api.anthropic.com/v1/messages"
        self._model = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

        if not self._api_key:
            logger.warning("ANTHROPIC_API_KEY not found; Claude summaries unavailable.")

    def generate(self, transcript_text: str) -> MeetingSummary:
        if not self._api_key:
            raise SummaryUnavailable("No API key; Claude summaries disabled.")
        if not transcript_text.strip():
            return MeetingSummary.empty()

        prompt = (
            "Analyze this meeting transcript and create a structured summary. "
            "You must respond with ONLY valid JSON in this exact format:\n\n"
            "{\n"
            '  "overview": "A brief 2-3 sentence overview of the meeting",\n'
            '  "decisions": ["decision 1", "decision 2"],\n'
            '  "action_items": ["action item 1 (assignee if mentioned)", "action item 2"],\n'
            '  "topics": ["important topic 1", "important topic 2"],\n'
            '  "unresolved": ["unresolved question 1", "unresolved issue 2"]\n'
            "}\n\n"
            "Do not include any other text, explanations, or markdown. "
            "Return only the JSON object. If no items exist for a category, use an empty array. "
            "For action items, include assignee names in parentheses if mentioned in the transcript."
        )

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }

        data = {
            "model": self._model,
            "max_tokens": 3000,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "user", 
                    "content": f"{prompt}\n\nTranscript:\n{transcript_text}"
                }
            ]
        }

        backoffs = [0.5, 1.0, 2.0]
        last_err: Optional[Exception] = None

        for attempt, backoff in enumerate([0.0] + backoffs, start=1):
            if backoff:
                time.sleep(backoff)
            try:
                start = time.time()
                resp = requests.post(self._endpoint, headers=headers, json=data, timeout=(15, 180))
                dur = time.time() - start
                logger.info(f"Claude summary HTTP {resp.status_code} in {dur:.2f}s (attempt {attempt})")
                
                if resp.status_code != 200:
                    if 500 <= resp.status_code < 600:
                        last_err = Exception(f"Claude server error {resp.status_code}")
                        continue
                    raise Exception(f"Claude request failed ({resp.status_code}): {resp.text}")

                response_data = resp.json()
                content = response_data["content"][0]["text"].strip()
                
                # Debug logging
                logger.debug(f"Claude raw summary response: {content[:200]}...")
                
                if not content:
                    logger.warning("Claude returned empty content for summary")
                    raise Exception("Claude returned empty response")
                
                # Try to parse JSON directly; if it's fenced markdown, strip fences
                if content.startswith("```"):
                    content = content.strip("`\n ")
                    # After stripping backticks, it might begin with json
                    if content.lower().startswith("json"):
                        content = content[4:].lstrip("\n")

                # Additional debug logging
                logger.debug(f"Claude cleaned summary content: {content[:200]}...")
                
                obj = json.loads(content)
                overview = str(obj.get("overview", "")).strip()
                decisions = [str(x).strip() for x in obj.get("decisions", []) if str(x).strip()]
                action_items = [str(x).strip() for x in obj.get("action_items", []) if str(x).strip()]
                topics = [str(x).strip() for x in obj.get("topics", []) if str(x).strip()]
                unresolved = [str(x).strip() for x in obj.get("unresolved", []) if str(x).strip()]
                
                logger.info(f"Claude generated summary: {len(decisions)} decisions, {len(action_items)} actions, {len(topics)} topics, {len(unresolved)} unresolved")
                
                return MeetingSummary(
                    overview=overview,
                    decisions=decisions,
                    action_items=action_items,
                    topics=topics,
                    unresolved=unresolved,
                )
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(f"Network error during Claude summary (attempt {attempt}): {e}")
                continue
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last_err = e
                logger.error(f"Failed to parse Claude summary JSON: {e}")
                break
            except Exception as e:
                last_err = e
                logger.error(f"Claude summary generation error: {e}")
                break

        raise Exception(f"Claude summary generation failed after {len(backoffs)+1} attempts: {last_err}")

import json
import time
from typing import Optional
import os

import requests
from loguru import logger

from services.config import load_config
from services.suggest.base import ISuggestionBackend, SuggestionUnavailable, MeetingSuggestions


class ClaudeSuggestionBackend(ISuggestionBackend):
    def __init__(self) -> None:
        self._config = load_config()
        # Look for ANTHROPIC_API_KEY first, fall back to OPENAI_API_KEY for backward compatibility
        self._api_key = os.environ.get("ANTHROPIC_API_KEY") or self._config.openai_api_key
        self._endpoint = "https://api.anthropic.com/v1/messages"
        self._model = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

        if not self._api_key:
            logger.warning("ANTHROPIC_API_KEY not found; Claude suggestions unavailable.")

    def generate(self, transcript_text: str) -> MeetingSuggestions:
        if not self._api_key:
            raise SuggestionUnavailable("No API key; Claude suggestions disabled.")
        if not transcript_text.strip():
            return MeetingSuggestions.empty()

        prompt = (
            "Analyze this meeting transcript and extract detailed structured information. "
            "You must respond with ONLY valid JSON in this exact format:\n\n"
            "{\n"
            '  "recap": "one-line summary of the meeting",\n'
            '  "decisions": ["decision 1", "decision 2"],\n'
            '  "actions": ["action item 1", "action item 2"],\n'
            '  "risks": ["risk 1", "risk 2"],\n'
            '  "open_questions": ["question 1", "question 2"]\n'
            "}\n\n"
            "Guidelines for item content:\n"
            "- Recap: 1–2 sentences capturing overall scope and key themes.\n"
            "- Decisions: what/why, owners if stated, and any constraints or metrics mentioned.\n"
            "- Actions: imperative phrasing, include assignee and dates if available.\n"
            "- Risks: describe impact, likelihood if hinted, and any mitigation discussed.\n"
            "- Open questions: phrase clearly so they are actionable to follow up.\n"
            "- Split multi-part ideas into separate bullets; avoid merging unrelated points.\n"
            "- Prefer completeness over brevity; include all significant items, even minor ones.\n"
            "- Keep each string under ~250 characters; do not include markdown, headers, or commentary.\n\n"
            "Do not include any other text besides the JSON. If no items exist for a category, use an empty array."
        )

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }

        data = {
            "model": self._model,
            "max_tokens": 2000,
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
                resp = requests.post(self._endpoint, headers=headers, json=data, timeout=(15, 120))
                dur = time.time() - start
                logger.info(f"Claude suggestions HTTP {resp.status_code} in {dur:.2f}s (attempt {attempt})")
                
                if resp.status_code != 200:
                    if 500 <= resp.status_code < 600:
                        last_err = Exception(f"Claude server error {resp.status_code}")
                        continue
                    raise Exception(f"Claude request failed ({resp.status_code}): {resp.text}")

                response_data = resp.json()
                content = response_data["content"][0]["text"].strip()
                
                # Debug logging
                logger.debug(f"Claude raw response: {content[:200]}...")
                
                if not content:
                    logger.warning("Claude returned empty content")
                    raise Exception("Claude returned empty response")
                
                # Try to parse JSON directly; if it's fenced markdown, strip fences
                if content.startswith("```"):
                    content = content.strip("`\n ")
                    # After stripping backticks, it might begin with json
                    if content.lower().startswith("json"):
                        content = content[4:].lstrip("\n")

                # Additional debug logging
                logger.debug(f"Claude cleaned content: {content[:200]}...")
                
                obj = json.loads(content)
                recap = str(obj.get("recap", "")).strip()
                decisions = [str(x).strip() for x in obj.get("decisions", []) if str(x).strip()]
                actions = [str(x).strip() for x in obj.get("actions", []) if str(x).strip()]
                risks = [str(x).strip() for x in obj.get("risks", []) if str(x).strip()]
                open_questions = [str(x).strip() for x in obj.get("open_questions", []) if str(x).strip()]
                
                logger.info(f"Claude generated {len(decisions)} decisions, {len(actions)} actions, {len(risks)} risks, {len(open_questions)} questions")
                
                return MeetingSuggestions(
                    recap=recap,
                    decisions=decisions,
                    actions=actions,
                    risks=risks,
                    open_questions=open_questions,
                )
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(f"Network error during Claude suggestions (attempt {attempt}): {e}")
                continue
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last_err = e
                logger.error(f"Failed to parse Claude suggestions JSON: {e}")
                break
            except Exception as e:
                last_err = e
                logger.error(f"Claude suggestion generation error: {e}")
                break

        friendly = str(last_err) if last_err else "Unknown Claude suggestions error"
        raise Exception(friendly)

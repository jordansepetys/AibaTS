"""OpenAI backend for structured summary generation."""

import json
import time
from typing import Optional
import os

import requests
from loguru import logger

from services.config import load_config
from services.summary.base import ISummaryBackend, MeetingSummary, SummaryUnavailable


class OpenAISummaryBackend(ISummaryBackend):
    """OpenAI backend for generating structured meeting summaries."""
    
    def __init__(self) -> None:
        self._config = load_config()
        self._api_key = self._config.openai_api_key
        self._api_url = self._config.llm_api_url
        # Optional model override
        self._model = os.environ.get("OPENAI_SUGGEST_MODEL", "gpt-4o")

        if not self._api_key:
            logger.warning("OPENAI_API_KEY not found; OpenAI summaries unavailable.")

    def generate(self, transcript_text: str) -> MeetingSummary:
        if not self._api_key:
            raise SummaryUnavailable("No API key; OpenAI summaries disabled.")
        if not transcript_text.strip():
            return MeetingSummary.empty()

        prompt = (
            "Analyze this meeting transcript and create a structured summary. "
            "Return strict JSON with keys: overview (string), decisions (array of strings), "
            "action_items (array of strings), topics (array of strings), unresolved (array of strings). "
            "For overview, provide a brief 2-3 sentence summary. "
            "For action items, include assignee names in parentheses if mentioned. "
            "For topics, list the important subjects discussed. "
            "For unresolved, list questions or issues that remain open."
        )

        data = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "You generate structured meeting summaries in JSON format."},
                {"role": "user", "content": f"{prompt}\n\nTranscript:\n{transcript_text}"},
            ],
            "temperature": 0.2,
        }

        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        backoffs = [0.5, 1.0, 2.0]
        last_err: Optional[Exception] = None

        for attempt, backoff in enumerate([0.0] + backoffs, start=1):
            if backoff:
                time.sleep(backoff)
            try:
                start = time.time()
                resp = requests.post(self._api_url, headers=headers, json=data, timeout=(15, 120))
                dur = time.time() - start
                logger.info(f"OpenAI summary HTTP {resp.status_code} in {dur:.2f}s (attempt {attempt})")
                if resp.status_code != 200:
                    if 500 <= resp.status_code < 600:
                        last_err = Exception(f"OpenAI server error {resp.status_code}")
                        continue
                    raise Exception(f"OpenAI summary request failed ({resp.status_code}): {resp.text}")

                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Try to parse JSON directly; if it's fenced markdown, strip fences
                content = content.strip()
                if content.startswith("```"):
                    content = content.strip("`\n ")
                    # After stripping backticks, it might begin with json
                    if content.lower().startswith("json"):
                        content = content[4:].lstrip("\n")

                obj = json.loads(content)
                overview = str(obj.get("overview", "")).strip()
                decisions = [str(x).strip() for x in obj.get("decisions", []) if str(x).strip()]
                action_items = [str(x).strip() for x in obj.get("action_items", []) if str(x).strip()]
                topics = [str(x).strip() for x in obj.get("topics", []) if str(x).strip()]
                unresolved = [str(x).strip() for x in obj.get("unresolved", []) if str(x).strip()]
                
                logger.info(f"OpenAI generated summary: {len(decisions)} decisions, {len(action_items)} actions, {len(topics)} topics, {len(unresolved)} unresolved")
                
                return MeetingSummary(
                    overview=overview,
                    decisions=decisions,
                    action_items=action_items,
                    topics=topics,
                    unresolved=unresolved,
                )
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(f"Network error during OpenAI summary (attempt {attempt}): {e}")
                continue
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last_err = e
                logger.error(f"Failed to parse OpenAI summary JSON: {e}")
                break
            except Exception as e:
                last_err = e
                logger.error(f"OpenAI summary generation error: {e}")
                break

        raise Exception(f"OpenAI summary generation failed after {len(backoffs)+1} attempts: {last_err}")

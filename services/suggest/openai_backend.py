import json
import time
from typing import Optional
import os

import requests
from loguru import logger

from services.config import load_config
from services.suggest.base import ISuggestionBackend, SuggestionUnavailable, MeetingSuggestions


class OpenAISuggestionBackend(ISuggestionBackend):
    def __init__(self) -> None:
        self._config = load_config()
        self._api_key = self._config.openai_api_key
        self._api_url = self._config.llm_api_url
        # Optional model override
        self._model = os.environ.get("OPENAI_SUGGEST_MODEL", "gpt-4o")

        if not self._api_key:
            logger.warning("OPENAI_API_KEY not found; OpenAI suggestions unavailable.")

    def generate(self, transcript_text: str) -> MeetingSuggestions:
        if not self._api_key:
            raise SuggestionUnavailable("No API key; OpenAI suggestions disabled.")
        if not transcript_text.strip():
            return MeetingSuggestions.empty()

        prompt = (
            "Extract a one-line recap and detailed structured lists from the meeting transcript. "
            "Return strict JSON with keys: recap (string), decisions (array of strings), "
            "actions (array of strings), risks (array of strings), open_questions (array of strings). "
            "Guidelines: "
            "- Recap: 1–2 sentences capturing overall scope and key themes. "
            "- For every list item, be specific and include available context: what/why, who/owner, dates or deadlines, key numbers. "
            "- Split multi-part ideas into separate bullets; avoid merging unrelated points. "
            "- Prefer completeness over brevity; include all significant items, even minor ones. "
            "- Keep each string under ~250 characters; do not include markdown or extra commentary."
        )

        data = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "You extract structured meeting notes with detailed, specific bullets and comprehensive coverage while preserving a strict JSON output."},
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
                logger.info(f"OpenAI suggestions HTTP {resp.status_code} in {dur:.2f}s (attempt {attempt})")
                if resp.status_code != 200:
                    if 500 <= resp.status_code < 600:
                        last_err = Exception(f"OpenAI server error {resp.status_code}")
                        continue
                    raise Exception(f"OpenAI suggestion request failed ({resp.status_code}): {resp.text}")

                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Try to parse JSON directly; if it's fenced markdown, strip fences
                content = content.strip()
                if content.startswith("```"):
                    content = content.strip("`\n ")
                    # After stripping backticks, it might begin with json
                    if content.lower().startswith("json"):
                        content = content[4:].lstrip("\n")

                obj = json.loads(content)
                recap = str(obj.get("recap", "")).strip()
                decisions = [str(x).strip() for x in obj.get("decisions", []) if str(x).strip()]
                actions = [str(x).strip() for x in obj.get("actions", []) if str(x).strip()]
                risks = [str(x).strip() for x in obj.get("risks", []) if str(x).strip()]
                open_questions = [str(x).strip() for x in obj.get("open_questions", []) if str(x).strip()]
                
                logger.info(f"OpenAI generated {len(decisions)} decisions, {len(actions)} actions, {len(risks)} risks, {len(open_questions)} questions")
                
                return MeetingSuggestions(
                    recap=recap,
                    decisions=decisions,
                    actions=actions,
                    risks=risks,
                    open_questions=open_questions,
                )
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(f"Network error during OpenAI suggestions (attempt {attempt}): {e}")
                continue
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last_err = e
                logger.error(f"Failed to parse OpenAI suggestions JSON: {e}")
                break
            except Exception as e:
                last_err = e
                logger.error(f"OpenAI suggestion generation error: {e}")
                break

        friendly = str(last_err) if last_err else "Unknown OpenAI suggestions error"
        raise Exception(friendly)


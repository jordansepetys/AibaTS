import time
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from services.config import load_config
from services.transcribe.base import ITranscriptionBackend, TranscriptionUnavailable


class OpenAITranscriptionBackend(ITranscriptionBackend):
    def __init__(self) -> None:
        self._config = load_config()
        self._api_key = self._config.openai_api_key
        # Allow OPENAI_API_BASE override, default to https://api.openai.com
        # If user supplied LLM_API_URL previously, prefer OPENAI_API_BASE for clarity here.
        import os

        api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com")
        self._endpoint = f"{api_base.rstrip('/')}/v1/audio/transcriptions"
        self._model = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")

        if not self._api_key:
            logger.warning("OPENAI_API_KEY missing; transcription unavailable.")

    def transcribe(self, audio_path: str) -> str:
        if not self._api_key:
            raise TranscriptionUnavailable("No API key; transcription disabled.")

        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        file_size = audio_file.stat().st_size
        logger.info(f"Transcription request: file={audio_file.name} size={file_size} bytes model={self._model}")

        headers = {"Authorization": f"Bearer {self._api_key}"}
        backoffs = [0.5, 1.0, 2.0]
        last_err: Optional[Exception] = None

        for attempt, backoff in enumerate([0.0] + backoffs, start=1):
            if backoff:
                time.sleep(backoff)
            try:
                with audio_file.open("rb") as f:
                    files = {"file": (audio_file.name, f, "audio/wav")}
                    data = {"model": self._model, "response_format": "text"}
                    start_time = time.time()
                    resp = requests.post(self._endpoint, headers=headers, files=files, data=data, timeout=(15, 120))
                    duration = time.time() - start_time
                    logger.info(f"Transcription HTTP {resp.status_code} in {duration:.2f}s (attempt {attempt})")

                if resp.status_code == 200:
                    return resp.text.strip()
                elif resp.status_code == 413:
                    # Payload too large
                    raise Exception("Audio too large (413). Record a shorter clip or enable chunked transcription.")
                elif 400 <= resp.status_code < 500:
                    # Client error
                    msg = resp.text
                    raise Exception(f"Transcription failed (client error {resp.status_code}): {msg}")
                else:
                    # Server error → retry
                    last_err = Exception(f"Server error {resp.status_code}: {resp.text}")
                    continue
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(f"Network error during transcription (attempt {attempt}): {e}")
                continue
            except Exception as e:
                # Non-retryable or immediate failure
                last_err = e
                break

        # Exhausted retries
        friendly = str(last_err) if last_err else "Unknown transcription error"
        logger.error(f"Transcription failed after retries: {friendly}")
        raise Exception(friendly)




import io
import math
import time
import wave
from pathlib import Path
from typing import Optional, List

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

        # Chunking controls
        self._enable_chunking: bool = os.environ.get("OPENAI_TRANSCRIBE_ENABLE_CHUNKING", "1").strip() not in ("0", "false", "False")
        # Default 10 minutes per chunk at 16kHz mono 16-bit ≈ ~19 MB
        self._chunk_seconds: int = int(os.environ.get("OPENAI_TRANSCRIBE_CHUNK_SECONDS", "600"))
        # If file exceeds this threshold, prefer chunked path (default ~24 MB)
        self._max_unchunked_bytes: int = int(os.environ.get("OPENAI_TRANSCRIBE_MAX_BYTES", str(24 * 1024 * 1024)))

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

        # Preemptive chunking for large files
        if self._enable_chunking and file_size > self._max_unchunked_bytes:
            logger.info(
                f"File exceeds unchunked threshold ({file_size} > {self._max_unchunked_bytes}); using chunked transcription"
            )
            return self._transcribe_chunked(audio_file, headers)

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
                    if self._enable_chunking:
                        logger.warning("Received 413 (Payload Too Large); falling back to chunked transcription")
                        return self._transcribe_chunked(audio_file, headers)
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

    # --- Internal helpers ---
    def _split_wav_into_chunks(self, audio_file: Path) -> List[bytes]:
        """Split a WAV file into chunked WAV byte blobs based on self._chunk_seconds.

        Preserves WAV headers for each chunk.
        """
        chunks: List[bytes] = []
        with wave.open(str(audio_file), "rb") as wf:
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frame_rate = wf.getframerate()
            total_frames = wf.getnframes()

            frames_per_chunk = max(1, int(self._chunk_seconds * frame_rate))
            total_chunks = int(math.ceil(total_frames / frames_per_chunk))
            logger.info(
                f"Splitting WAV into {total_chunks} chunk(s) | rate={frame_rate}Hz channels={num_channels} width={sample_width}B"
            )

            current_frame = 0
            idx = 0
            while current_frame < total_frames:
                frames_to_read = min(frames_per_chunk, total_frames - current_frame)
                wf.setpos(current_frame)
                frames = wf.readframes(frames_to_read)

                bio = io.BytesIO()
                with wave.open(bio, "wb") as out:
                    out.setnchannels(num_channels)
                    out.setsampwidth(sample_width)
                    out.setframerate(frame_rate)
                    out.writeframes(frames)

                chunk_bytes = bio.getvalue()
                idx += 1
                logger.info(f"Prepared chunk {idx}/{total_chunks} with {len(chunk_bytes)} bytes")
                chunks.append(chunk_bytes)

                current_frame += frames_to_read
        return chunks

    def _post_whisper(self, headers: dict, file_name: str, content_bytes: bytes) -> str:
        """Post a single audio blob to Whisper and return text."""
        backoffs = [0.5, 1.0, 2.0]
        last_err: Optional[Exception] = None
        for attempt, backoff in enumerate([0.0] + backoffs, start=1):
            if backoff:
                time.sleep(backoff)
            try:
                files = {"file": (file_name, io.BytesIO(content_bytes), "audio/wav")}
                data = {"model": self._model, "response_format": "text"}
                start_time = time.time()
                resp = requests.post(self._endpoint, headers=headers, files=files, data=data, timeout=(15, 120))
                duration = time.time() - start_time
                logger.info(f"Chunk transcription HTTP {resp.status_code} in {duration:.2f}s (attempt {attempt})")
                if resp.status_code == 200:
                    return resp.text.strip()
                elif 400 <= resp.status_code < 500:
                    raise Exception(f"Chunk transcription failed (client error {resp.status_code}): {resp.text}")
                else:
                    last_err = Exception(f"Chunk server error {resp.status_code}: {resp.text}")
                    continue
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(f"Network error during chunk transcription (attempt {attempt}): {e}")
                continue
            except Exception as e:
                last_err = e
                break
        friendly = str(last_err) if last_err else "Unknown chunk transcription error"
        raise Exception(friendly)

    def _transcribe_chunked(self, audio_file: Path, headers: dict) -> str:
        """Transcribe a large WAV by splitting into chunks and concatenating outputs."""
        pieces: List[str] = []
        chunk_bytes_list = self._split_wav_into_chunks(audio_file)
        for i, chunk_bytes in enumerate(chunk_bytes_list, start=1):
            file_name = f"{audio_file.stem}_part_{i}.wav"
            logger.info(f"Transcribing chunk {i}/{len(chunk_bytes_list)} → {file_name}")
            text = self._post_whisper(headers, file_name, chunk_bytes)
            pieces.append(text)
        combined = "\n".join(pieces).strip()
        logger.info("Chunked transcription complete; assembling final transcript")
        return combined





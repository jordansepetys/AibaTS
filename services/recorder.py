import threading
import wave
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


class IRecorder(ABC):
    @abstractmethod
    def start(self, output_path: Path) -> bool:
        """Start recording audio to the given output_path. Returns True if started."""

    @abstractmethod
    def stop(self) -> bool:
        """Stop recording. Returns True if stopped cleanly."""

    @property
    @abstractmethod
    def is_recording(self) -> bool:
        """Whether recording is active."""

    @property
    @abstractmethod
    def output_path(self) -> Optional[Path]:
        """The output file path for the current/last recording."""


class PyAudioRecorder(IRecorder):
    """Simple recorder that writes a single full WAV file using PyAudio."""

    def __init__(
        self,
        rate: int = 16000,
        channels: int = 1,
        chunk: int = 1024,
    ) -> None:
        self._rate = rate
        self._channels = channels
        self._chunk = chunk
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._output_path: Optional[Path] = None

        self._p = None
        self._stream = None
        self._wf = None

    def start(self, output_path: Path) -> bool:
        if self._running:
            logger.warning("Recorder already running; ignoring start()")
            return False

        try:
            import pyaudio  # Local import to avoid import errors when packaging without audio

            self._output_path = Path(output_path)
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

            self._p = pyaudio.PyAudio()
            sample_format = pyaudio.paInt16

            self._wf = wave.open(str(self._output_path), "wb")
            self._wf.setnchannels(self._channels)
            self._wf.setsampwidth(self._p.get_sample_size(sample_format))
            self._wf.setframerate(self._rate)

            try:
                self._stream = self._p.open(
                    format=sample_format,
                    channels=self._channels,
                    rate=self._rate,
                    input=True,
                    frames_per_buffer=self._chunk,
                )
            except Exception as e:
                logger.error(f"Failed to open audio input device: {e}")
                self._cleanup()
                return False

            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info(f"Recording started → {self._output_path}")
            return True

        except ImportError:
            logger.error("PyAudio is not installed. Cannot start recording.")
            self._cleanup()
            return False
        except Exception as e:
            logger.exception(f"Unexpected error starting recorder: {e}")
            self._cleanup()
            return False

    def _run_loop(self) -> None:
        try:
            while self._running:
                try:
                    data = self._stream.read(self._chunk, exception_on_overflow=False)
                    self._wf.writeframes(data)
                except OSError as e:
                    logger.warning(f"Audio read warning: {e}; retrying")
                    time.sleep(0.05)
                except Exception as e:
                    logger.error(f"Audio read error: {e}; stopping")
                    break
        finally:
            self._cleanup()
            logger.info("Recording loop finished")

    def stop(self) -> bool:
        if not self._running and not self._thread:
            logger.info("Recorder not running; stop() noop")
            return True

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("Recorder thread did not stop cleanly within timeout")
                return False
        logger.info(f"Recording stopped → {self._output_path}")
        return True

    def _cleanup(self) -> None:
        try:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
        finally:
            self._stream = None

        try:
            if self._p is not None:
                self._p.terminate()
        finally:
            self._p = None

        try:
            if self._wf is not None:
                self._wf.close()
        finally:
            self._wf = None

    @property
    def is_recording(self) -> bool:
        return self._running

    @property
    def output_path(self) -> Optional[Path]:
        return self._output_path




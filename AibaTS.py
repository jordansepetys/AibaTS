import os
import sys
import time
import json
import glob
import wave
import requests
import markdown2
import pyaudio
import math
import functools
from dotenv import load_dotenv
from datetime import datetime, timedelta # Keep timedelta if used elsewhere
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                             QHBoxLayout, QWidget, QLabel, QTextEdit, QListWidget,
                             QListWidgetItem, QSplitter, QMessageBox, QLineEdit, QComboBox)
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QObject, QRunnable, QThreadPool)

# --- Configuration ---
load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"

# Audio settings
CHUNK_READ_SIZE = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK_DURATION_MINUTES = 10

# Folders
BASE_FOLDER = "meeting_data_v2"
WAVE_OUTPUT_FOLDER = os.path.join(BASE_FOLDER, "recordings")
TRANSCRIPTS_FOLDER = os.path.join(BASE_FOLDER, "transcripts")
SUMMARIES_FOLDER = os.path.join(BASE_FOLDER, "summaries")
# MENTOR_FOLDER = os.path.join(BASE_FOLDER, "mentor_feedback") # <<< REMOVED
NOTES_FOLDER = os.path.join(BASE_FOLDER, "json_notes")
PROJECT_WIKIS_FOLDER = os.path.join(BASE_FOLDER, "project_wikis")
HISTORY_FILE = os.path.join(BASE_FOLDER, "meeting_history.json")

# Create all needed folders
for folder in [WAVE_OUTPUT_FOLDER, TRANSCRIPTS_FOLDER, SUMMARIES_FOLDER, NOTES_FOLDER, # <<< MENTOR_FOLDER REMOVED
               PROJECT_WIKIS_FOLDER]:
    os.makedirs(folder, exist_ok=True)

API_TIMEOUTS = (15, 180)
MAX_TRANSCRIPTION_RETRIES = 2
RETRY_DELAY_SECONDS = 3


# --- Worker Signals ---
class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)
    transcription_result = pyqtSignal(str, str)
    summarization_result = pyqtSignal(str)
    # mentor_feedback_result = pyqtSignal(str) # <<< REMOVED
    json_notes_result = pyqtSignal(str)
    wiki_suggestion_result = pyqtSignal(str, str)
    recap_result = pyqtSignal(str)


# --- API Classes ---
class WhisperTranscriber:
    """Handles transcription using OpenAI's Whisper API with retry logic"""

    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = WHISPER_API_URL

    def transcribe(self, audio_file_path):
        if not self.api_key: print("Error: Whisper API key is missing."); return None
        headers = {"Authorization": f"Bearer {self.api_key}"};
        data = {"model": "whisper-1"}
        last_exception = None
        for attempt in range(MAX_TRANSCRIPTION_RETRIES + 1):
            print(
                f"Attempting to transcribe (Attempt {attempt + 1}/{MAX_TRANSCRIPTION_RETRIES + 1}): {os.path.basename(audio_file_path)}")
            response = None
            try:
                with open(audio_file_path, "rb") as audio_file:
                    files = {"file": (os.path.basename(audio_file_path), audio_file)}
                    response = requests.post(self.api_url, headers=headers, files=files, data=data,
                                             timeout=API_TIMEOUTS)
                    print(f"Transcription response status (Attempt {attempt + 1}): {response.status_code}")
                    if response.status_code in [500, 502, 503, 504, 429]: print(
                        f"Retryable error {response.status_code} encountered."); response.raise_for_status()
                    if 400 <= response.status_code < 500 and response.status_code != 429: print(
                        f"Client error {response.status_code}, not retrying. Response: {response.text}"); return None
                    response.raise_for_status()
                    result = response.json()["text"]
                    print(f"Transcription success (Attempt {attempt + 1}) for {os.path.basename(audio_file_path)}");
                    return result
            except requests.exceptions.Timeout as e:
                print(f"Error: Transcription request timed out (Attempt {attempt + 1})."); last_exception = e
            except requests.exceptions.RequestException as e:
                print(f"Error during transcription request (Attempt {attempt + 1}): {e}");
                last_exception = e
                is_retryable_http = False
                status_code = -1
                if response is not None: status_code = response.status_code
                if isinstance(e, requests.exceptions.HTTPError) and status_code != -1:
                    if status_code in [429, 500, 502, 503, 504]:
                        is_retryable_http = True
                    else:
                        print(f"Non-retryable HTTP error {status_code}. Giving up."); return None
                is_connection_error = isinstance(e, (
                requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError))
                if not is_retryable_http and not is_connection_error: print(
                    f"Non-retryable request error encountered. Giving up."); return None
            except FileNotFoundError as e:
                print(f"Error: Audio file not found: {audio_file_path}"); return None
            except KeyError as e:
                resp_text = "N/A"
                try:
                    if response is not None and hasattr(response, 'text'): resp_text = response.text
                except Exception:
                    pass
                print(
                    f"Error: Unexpected response format from Whisper API (Attempt {attempt + 1}). Response: {resp_text}");
                return None
            except Exception as e:
                print(
                    f"An unexpected error occurred during transcription attempt {attempt + 1}: {e}"); last_exception = e; print(
                    "Unexpected error, giving up."); return None
            if attempt < MAX_TRANSCRIPTION_RETRIES:
                print(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                print(
                    f"Max retries ({MAX_TRANSCRIPTION_RETRIES}) reached for {os.path.basename(audio_file_path)}. Giving up.")
                if last_exception:
                    print(f"Last error: {last_exception}")
                return None
        print("Fell through retry loop without success or explicit failure.");
        return None


class LLMSummarizer:
    """Handles summarization using OpenAI's GPT API (Summary ONLY)"""

    def __init__(self, api_key):
        self.api_key = api_key; self.api_url = LLM_API_URL

    def summarize(self, text):
        if not self.api_key: print("Error: LLM API key is missing for summarization."); return None
        if not text or text.isspace(): print("Warning: Attempted to summarize empty text."); return ""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        prompt = (
            f"Analyze the following meeting transcript and provide a concise summary in bullet points, highlighting key topics, decisions, and action items.\n\nTranscript:\n{text}")
        data = {"model": "gpt-4o", "messages": [{"role": "system",
                                                 "content": "You are a helpful assistant skilled at analyzing meeting transcripts and creating concise bullet-point summaries."},
                                                {"role": "user", "content": prompt}], "temperature": 0.5}
        response = None;
        response_data = None
        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUTS);
            response.raise_for_status()
            response_data = response.json();
            return response_data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.Timeout:
            print("Error: Summarization request timed out."); return None
        except requests.exceptions.RequestException as e:
            print(f"Error during summarization request: {e}")
            try:
                if response is not None and hasattr(response, 'text'): print(f"Response content: {response.text}")
            except Exception:
                pass
            return None
        except (KeyError, IndexError) as e:
            response_info = "N/A"
            try:
                if response_data is not None:
                    response_info = str(response_data)
                elif response is not None and hasattr(response, 'text'):
                    response_info = response.text
            except Exception:
                pass
            print(f"Error: Unexpected response format from LLM API ({e}). Response: {response_info}");
            return None
        except Exception as e:
            print(f"An unexpected error occurred during summarization: {e}"); return None


class LLMJsonExtractor:
    """Uses an LLM to extract structured notes from a transcript into JSON."""

    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = LLM_API_URL

    def extract_notes(self, transcript_text):
        if not self.api_key: print("Error: LLM API key is missing for JSON extraction."); return None
        if not transcript_text or transcript_text.isspace():
            print("Warning: Attempted JSON extraction from empty transcript.")
            return json.dumps({"decisions": [], "action_items": [], "risks": [], "open_questions": []}, indent=2)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        prompt = (
            f"Analyze the following meeting transcript. Extract key information and format it ONLY as a JSON object.\n"
            f"The JSON object must have these exact keys: 'decisions', 'action_items', 'risks', 'open_questions'.\n"
            f"Each key should map to a list of strings.\n"
            f"*   'decisions': List key decisions made.\n"
            f"*   'action_items': List specific tasks or actions agreed upon.\n"
            f"*   'risks': List potential risks or blockers mentioned.\n"
            f"*   'open_questions': List questions raised that were left unanswered or need follow-up.\n"
            f"If no items are found for a category, use an empty list [].\n"
            f"Do NOT include any text before or after the JSON object. Output only the valid JSON.\n\n"
            f"Transcript:\n```\n{transcript_text}\n```\n\n"
            f"JSON Output:"
        )
        data = {"model": "gpt-4o", "messages": [{"role": "system",
                                                 "content": "You are an AI assistant that extracts specific information from meeting transcripts and outputs ONLY valid JSON."},
                                                {"role": "user", "content": prompt}], "temperature": 0.2}
        response = None;
        response_data = None
        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUTS);
            response.raise_for_status()
            response_data = response.json()
            response_content = response_data["choices"][0]["message"]["content"].strip()
            if not (response_content.startswith('{') and response_content.endswith('}')):
                print(f"Warning: LLM output for JSON notes doesn't look like JSON: {response_content}")
                error_json = json.dumps(
                    {"error": "LLM did not return valid JSON format.", "raw_output": response_content}, indent=2);
                return error_json
            try:
                parsed_json = json.loads(response_content);
                return response_content
            except json.JSONDecodeError as json_e:
                print(f"Error: Could not decode LLM JSON output: {json_e}");
                print(f"LLM Raw Output: {response_content}")
                error_json = json.dumps(
                    {"error": f"LLM output failed JSON parsing: {json_e}", "raw_output": response_content}, indent=2);
                return error_json
        except requests.exceptions.Timeout:
            print("Error: JSON extraction request timed out."); return None
        except requests.exceptions.RequestException as e:
            print(f"Error during JSON extraction request: {e}")
            try:
                if response is not None and hasattr(response, 'text'): print(f"Response content: {response.text}")
            except Exception:
                pass
            return None
        except (KeyError, IndexError) as e:
            response_info = "N/A"
            try:
                if response_data is not None:
                    response_info = str(response_data)
                elif response is not None and hasattr(response, 'text'):
                    response_info = response.text
            except Exception:
                pass
            print(f"Error: Unexpected LLM API response format ({e}). Response: {response_info}");
            return None
        except Exception as e:
            print(f"An unexpected error occurred during JSON extraction: {e}"); return None


# --- Worker Runnables ---
class TranscriptionWorker(QRunnable):
    """Worker thread for running transcription on a single audio chunk file"""

    def __init__(self, audio_file_path, api_key):
        super().__init__()
        self.audio_file_path = audio_file_path
        self.api_key = api_key
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not self.api_key:
                self.signals.error.emit(
                    f"Transcription failed for {os.path.basename(self.audio_file_path)}: API key missing in worker.")
            else:
                transcriber = WhisperTranscriber(self.api_key)
                transcript = transcriber.transcribe(self.audio_file_path)
                if transcript is not None:
                    self.signals.transcription_result.emit(transcript, self.audio_file_path)
                else:
                    self.signals.error.emit(f"Transcription failed for {os.path.basename(self.audio_file_path)}")
        except Exception as e:
            self.signals.error.emit(
                f"Unexpected error in TranscriptionWorker for {os.path.basename(self.audio_file_path)}: {e}")
        finally:
            self.signals.finished.emit()


class LLMRecapWorker(QRunnable):
    """Worker thread for generating an executive-friendly weekly recap using an LLM."""

    def __init__(self, aggregated_bullets_text, project_name, week_str, api_key):
        super().__init__()
        self.aggregated_bullets_text = aggregated_bullets_text
        self.project_name = project_name
        self.week_str = week_str
        self.api_key = api_key
        self.signals = WorkerSignals()
        self.api_url = LLM_API_URL

    def run(self):
        print("DEBUG: LLMRecapWorker started.")
        try:
            if not self.api_key:
                self.signals.error.emit("LLM Recap failed: API key missing in worker.")
                return

            if not self.aggregated_bullets_text or self.aggregated_bullets_text.isspace():
                print("DEBUG: LLMRecapWorker: Input text is empty, returning empty recap.")
                self.signals.recap_result.emit("(No specific items were provided for narrative summarization.)")
                return

            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            prompt = (
                f"You are an assistant summarizing weekly project activity for an executive audience. "
                f"Review the following aggregated bullet points for project '{self.project_name}' during the week '{self.week_str}'.\n"
                f"Rewrite these points into a concise, professional, executive-friendly narrative summary (1-3 short paragraphs).\n"
                f"Focus on key accomplishments, decisions, and any critical risks or open questions that need visibility.\n"
                f"Avoid jargon where possible. Maintain a positive but realistic tone.\n\n"
                f"--- Aggregated Notes ---\n"
                f"{self.aggregated_bullets_text}\n\n"
                f"--- Executive Narrative Summary ---"
            )
            data = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system",
                     "content": "You generate concise, executive-friendly narrative summaries of weekly project activities based on provided bullet points."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.6,
                "max_tokens": 400
            }
            response = None
            response_data = None
            print("DEBUG: LLMRecapWorker: Sending request to LLM...")
            response = requests.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUTS)
            response.raise_for_status()
            response_data = response.json()
            print("DEBUG: LLMRecapWorker: Received response from LLM.")
            recap_text = response_data["choices"][0]["message"]["content"].strip()
            self.signals.recap_result.emit(recap_text)
            print("DEBUG: LLMRecapWorker: Emitted recap result.")
        except requests.exceptions.Timeout:
            err_msg = "LLM Recap failed: Request timed out."
            print(f"ERROR: {err_msg}")
            self.signals.error.emit(err_msg)
        except requests.exceptions.RequestException as e:
            error_detail = f"LLM Recap failed: Network/API error: {e}"
            try:
                if response is not None and hasattr(response, 'text'):
                    error_detail += f" - Response Status: {response.status_code}, Body: {response.text[:500]}..."
            except Exception as detail_e:
                print(f"DEBUG: Error getting exception details: {detail_e}")
            print(f"ERROR: {error_detail}")
            self.signals.error.emit(error_detail)
        except (KeyError, IndexError) as e:
            error_detail = f"LLM Recap failed: Unexpected API response format ({e})."
            response_info = "N/A"
            try:
                if response_data is not None:
                    response_info = str(response_data)[:500]
                elif response is not None and hasattr(response, 'text'):
                    response_info = response.text[:500]
            except Exception as detail_e:
                print(f"DEBUG: Error getting exception details: {detail_e}")
            error_detail += f" Response: {response_info}..."
            print(f"ERROR: {error_detail}")
            self.signals.error.emit(error_detail)
        except Exception as e:
            err_msg = f"LLM Recap failed: An unexpected error occurred in worker: {type(e).__name__} - {e}"
            print(f"ERROR: {err_msg}")
            self.signals.error.emit(err_msg)
        finally:
            print("DEBUG: LLMRecapWorker finished.")
            self.signals.finished.emit()


class SummarizationWorker(QRunnable):
    """Worker thread for running final summarization"""

    def __init__(self, text_to_summarize, api_key):
        super().__init__();
        self.text_to_summarize = text_to_summarize;
        self.api_key = api_key;
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not self.api_key:
                self.signals.error.emit("Summarization failed: API key missing in worker.")
            else:
                summarizer = LLMSummarizer(self.api_key);
                summary = summarizer.summarize(self.text_to_summarize)
                if summary is not None:
                    self.signals.summarization_result.emit(summary)
                else:
                    self.signals.error.emit("Summarization failed.")
        except Exception as e:
            self.signals.error.emit(f"Error in summarization worker: {e}")
        finally:
            self.signals.finished.emit()


# class MentorFeedbackWorker(QRunnable): # <<< REMOVED ENTIRE CLASS
#     """Worker thread for generating CONCISE mentor feedback ('Aldis')"""
#
#     def __init__(self, transcript_text, summary_text, project_wiki_content, project_name, api_key):
#         super().__init__()
#         self.transcript_text = transcript_text
#         self.summary_text = summary_text
#         self.project_wiki_content = project_wiki_content
#         self.project_name = project_name
#         self.api_key = api_key
#         self.signals = WorkerSignals()
#         self.api_url = LLM_API_URL
#
#     def run(self):
#         try:
#             if not self.api_key:
#                 self.signals.error.emit("Mentor feedback failed: API key missing.")
#                 return
#             if not self.transcript_text or self.transcript_text.isspace():
#                 self.signals.error.emit("Mentor feedback failed: Transcript is empty.")
#                 return
#
#             headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
#
#             wiki_context_prompt_part = ""
#             if self.project_wiki_content and self.project_wiki_content.strip():
#                 wiki_context_prompt_part = (
#                     f"\n\nFor additional context, here is the current Project Wiki for '{self.project_name}':\n"
#                     f"--- PROJECT WIKI ---\n"
#                     f"{self.project_wiki_content}\n"
#                     f"--- END PROJECT WIKI ---"
#                 )
#             else:
#                 wiki_context_prompt_part = f"\n\n(No existing project wiki content was provided for project '{self.project_name}'.)"
#
#             prompt = (
#                 f"You are Aldis, an AI mentor reviewing a meeting for an AI BA/PM. Provide **brief and actionable** feedback based on the transcript, summary, and the broader project wiki context (if provided).\n\n"
#                 f"Instructions:\n"
#                 f"*   **Be Concise:** Focus on the 1-3 most important takeaways or suggestions. Use bullet points.\n"
#                 f"*   **Be Direct:** Avoid fluff. Get straight to the point.\n"
#                 f"*   **Actionable Advice:** Suggestions should be practical.\n"
#                 f"*   **Integrate Context:** If project wiki content is available, consider how the meeting's outcomes align with overall project goals, previously identified risks, or existing components. Does this meeting change anything fundamental in the wiki? Should it?\n"
#                 f"*   **Structure:** 1-2 bullets on strengths, 2-3 on key improvements/suggestions, possibly relating to wiki alignment.\n\n"
#                 f"**Analyze these areas, commenting on the most critical points, considering the wiki context:**\n"
#                 f"- Meeting effectiveness\n"
#                 f"- Key outcomes/decisions & their impact on project goals (from wiki)\n"
#                 f"- Action item quality\n"
#                 f"- Risks/Opportunities (are new risks/opportunities aligned with existing ones in the wiki?)\n"
#                 f"- BA/PM facilitation\n\n"
#                 f"--- MEETING TRANSCRIPT ---\n{self.transcript_text}\n\n"
#                 f"--- MEETING SUMMARY ---\n{self.summary_text if self.summary_text else 'Summary not available.'}\n"
#                 f"{wiki_context_prompt_part}\n\n"
#                 f"--- ALDIS' BRIEF, CONTEXT-AWARE FEEDBACK ---\n"
#             )
#             data = {"model": "gpt-4o",
#                     "messages": [{"role": "system",
#                                   "content": "You are Aldis, an AI mentor providing brief, direct, and actionable post-meeting feedback. If project wiki context is provided, integrate it into your analysis and suggestions."},
#                                  {"role": "user", "content": prompt}],
#                     "temperature": 0.6}
#
#             response = None
#             response_data = None
#             try:
#                 response = requests.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUTS)
#                 response.raise_for_status()
#                 response_data = response.json()
#                 feedback = response_data["choices"][0]["message"]["content"].strip()
#                 self.signals.mentor_feedback_result.emit(feedback)
#
#             except requests.exceptions.Timeout:
#                 self.signals.error.emit("Mentor feedback failed: Request timed out.")
#             except requests.exceptions.RequestException as e:
#                 error_detail = f"Mentor feedback failed: Network/API error: {e}"
#                 try:
#                     if response is not None and hasattr(response, 'text'):
#                         error_detail += f" - Response: {response.text}"
#                 except Exception:
#                     pass
#                 self.signals.error.emit(error_detail)
#             except (KeyError, IndexError) as e:
#                 error_detail = f"Mentor feedback failed: Unexpected API response format ({e})."
#                 response_info = "N/A"
#                 try:
#                     if 'response_data' in locals() and response_data is not None:
#                         response_info = str(response_data)
#                     elif 'response' in locals() and response is not None and hasattr(response, 'text'):
#                         response_info = response.text
#                 except Exception:
#                     pass
#                 error_detail += f" Response: {response_info}"
#                 self.signals.error.emit(error_detail)
#
#         except Exception as e:
#             self.signals.error.emit(f"Mentor feedback failed: An unexpected error in worker setup: {e}")
#         finally:
#             self.signals.finished.emit()


class JsonExtractionWorker(QRunnable):
    """Worker thread for running JSON note extraction"""

    def __init__(self, transcript_text, api_key):
        super().__init__()
        self.transcript_text = transcript_text
        self.api_key = api_key
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not self.api_key:
                self.signals.error.emit("JSON extraction failed: API key missing in worker.")
            else:
                extractor = LLMJsonExtractor(self.api_key)
                json_string = extractor.extract_notes(self.transcript_text)
                if json_string is not None:
                    self.signals.json_notes_result.emit(json_string)
                else:
                    self.signals.error.emit("JSON extraction failed.")
        except Exception as e:
            self.signals.error.emit(f"Error in JSON extraction worker: {e}")
        finally:
            self.signals.finished.emit()


class WikiUpdateSuggestionWorker(QRunnable):
    """
    Worker thread to get AI suggestions for updating a wiki section
    based on meeting content.
    """

    def __init__(self, current_section_content, meeting_info_text,
                 target_section_title, project_name, api_key):
        super().__init__()
        self.current_section_content = current_section_content
        self.meeting_info_text = meeting_info_text
        self.target_section_title = target_section_title
        self.project_name = project_name
        self.api_key = api_key
        self.signals = WorkerSignals()
        self.api_url = LLM_API_URL

    def run(self):
        try:
            if not self.api_key:
                self.signals.error.emit("Wiki Suggestion failed: API key missing.");
                return
            if not self.meeting_info_text:
                self.signals.error.emit("Wiki Suggestion failed: Meeting information is empty.");
                return
            if not self.target_section_title:
                self.signals.error.emit("Wiki Suggestion failed: Target section title is missing.");
                return

            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            specific_instructions = ""
            output_instructions = (
                f"Output ONLY the complete, revised text for the '{self.target_section_title}' section. "
                f"Do not add any conversational preamble, explanation, or the markdown section header itself (like '## {self.target_section_title}'). "
                f"Just provide the content that should go *under* that header."
            )
            if self.target_section_title.lower() == "daily log":
                specific_instructions = (
                    f"Based ONLY on the new information from the recent meeting (details below), "
                    f"generate a CONCISE new entry for the 'Daily Log' for project '{self.project_name}'. "
                    f"The entry should summarize key activities, decisions, and next steps from this specific meeting. "
                    f"Format the entry as a few bullet points. "
                    f"If the meeting has no new log-worthy updates, output ONLY the exact phrase 'No new log entries from this meeting.'"
                )
                output_instructions = (
                    f"Output ONLY the bullet points for the new log entry. "
                    f"If no new log entries, output ONLY the exact phrase 'No new log entries from this meeting.'"
                )
            else:
                specific_instructions = (
                    f"You are updating the '{self.target_section_title}' section of the project wiki for '{self.project_name}'.\n"
                    f"Based ONLY on the new information from the recent meeting (details below), suggest a revised version of the ENTIRE '{self.target_section_title}' section.\n"
                    f"If the meeting introduced new relevant points, add them. "
                    f"If the meeting clarified or changed existing points, reflect those changes. "
                    f"If the meeting made some existing points obsolete or less relevant, remove or update them accordingly. "
                    f"The goal is to have an up-to-date section based on the latest meeting.\n"
                    f"If no changes to the '{self.target_section_title}' section are warranted based on this meeting, output the original 'Current Section Content' unchanged."
                )
            prompt = (
                f"You are an AI assistant helping to maintain a project wiki.\n"
                f"Project: {self.project_name}\n"
                f"Target Section to Update: {self.target_section_title}\n\n"
                f"Current '{self.target_section_title}' Section Content (if any - for 'Daily Log' this is less relevant, focus on new entry):\n"
                f"```\n{self.current_section_content if self.current_section_content else 'This section is currently empty or new.'}\n```\n\n"
                f"Information from Recent Meeting:\n"
                f"```\n{self.meeting_info_text}\n```\n\n"
                f"Instructions:\n{specific_instructions}\n\n"
                f"{output_instructions}"
            )
            data = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system",
                     "content": "You are an AI assistant that helps update project wiki sections based on meeting notes. You output only the revised section content or new log entry as instructed, without any extra text or markdown headers."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            }
            response = None
            response_data = None
            try:
                response = requests.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUTS)
                response.raise_for_status()
                response_data = response.json()
                suggested_text = response_data["choices"][0]["message"]["content"].strip()
                self.signals.wiki_suggestion_result.emit(suggested_text, self.target_section_title)
            except requests.exceptions.Timeout:
                self.signals.error.emit("Wiki Suggestion: LLM request timed out.")
            except requests.exceptions.RequestException as e:
                error_detail = f"Wiki Suggestion: LLM request error: {e}"
                try:
                    if response is not None and hasattr(response, 'text'):
                        error_detail += f" - Response: {response.text}"
                except Exception:
                    pass
                self.signals.error.emit(error_detail)
            except (KeyError, IndexError) as e:
                error_detail = f"Wiki Suggestion: LLM response format error ({e})."
                response_info = "N/A"
                try:
                    if response_data is not None:
                        response_info = str(response_data)
                    elif response is not None and hasattr(response, 'text'):
                        response_info = response.text
                except Exception:
                    pass
                error_detail += f" Response: {response_info}"
                self.signals.error.emit(error_detail)
        except Exception as e:
            self.signals.error.emit(f"Wiki Suggestion worker unexpected error: {e}")
        finally:
            self.signals.finished.emit()


# --- Recorder Thread ---
class RecorderThread(QThread):
    update_signal = pyqtSignal(str)
    recording_finished_signal = pyqtSignal(bytes, int)

    def __init__(self):
        super().__init__()
        self.is_recording = False
        self.frames = []
        self.sample_width = 0
        print("DEBUG: RecorderThread __init__ called")

    def run(self):
        print("DEBUG: RecorderThread: run() method STARTED.")
        self.is_recording = True
        self.frames = []
        p = None
        stream = None
        try:
            self.update_signal.emit("RecorderThread: Initializing PyAudio...")
            print("DEBUG: RecorderThread: Attempting: p = pyaudio.PyAudio()")
            p = pyaudio.PyAudio()
            print("DEBUG: RecorderThread: SUCCESS: p = pyaudio.PyAudio()")
            self.update_signal.emit("RecorderThread: PyAudio initialized. Getting sample width...")
            print(f"DEBUG: RecorderThread: Attempting: self.sample_width = p.get_sample_size(FORMAT={FORMAT})")
            self.sample_width = p.get_sample_size(FORMAT)
            print(f"DEBUG: RecorderThread: SUCCESS: self.sample_width = {self.sample_width}")
            self.update_signal.emit(f"RecorderThread: Sample width: {self.sample_width}. Opening stream...")
            print(
                f"DEBUG: RecorderThread: Attempting: stream = p.open(format={FORMAT}, channels={CHANNELS}, rate={RATE}, input=True, frames_per_buffer={CHUNK_READ_SIZE})")
            stream = p.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            input=True,
                            frames_per_buffer=CHUNK_READ_SIZE)
            print("DEBUG: RecorderThread: SUCCESS: stream opened.")
            self.update_signal.emit("Recording started...")
        except Exception as e:
            error_msg = f"Error initializing audio: {type(e).__name__} - {e}"
            print(f"ERROR: RecorderThread: {error_msg}")
            self.update_signal.emit(error_msg)
            self.is_recording = False
            if stream:
                try:
                    stream.close()
                except Exception as close_e:
                    print(f"DEBUG: RecorderThread: Error closing stream during init error: {close_e}")
            if p:
                try:
                    p.terminate()
                except Exception as term_e:
                    print(f"DEBUG: RecorderThread: Error terminating PyAudio during init error: {term_e}")
            self.recording_finished_signal.emit(b"", 0)
            print("DEBUG: RecorderThread: run() method ending due to initialization error.")
            return

        print("DEBUG: RecorderThread: Entering recording loop...")
        loop_count = 0
        while self.is_recording:
            try:
                data = stream.read(CHUNK_READ_SIZE, exception_on_overflow=False)
                self.frames.append(data)
            except IOError as e:
                error_msg = f"Audio stream error in loop: {e}. Stopping recording."
                print(f"ERROR: RecorderThread: {error_msg}")
                self.update_signal.emit(error_msg)
                self.is_recording = False
            except Exception as e:
                error_msg = f"Unexpected error in recording loop: {e}. Stopping recording."
                print(f"ERROR: RecorderThread: {error_msg}")
                self.is_recording = False

        print("DEBUG: RecorderThread: Exited recording loop.")
        self.update_signal.emit("Recording stopped. Finalizing audio...")
        print("DEBUG: RecorderThread: Attempting post-loop cleanup...")
        if stream:
            try:
                print("DEBUG: RecorderThread: Stopping stream...")
                stream.stop_stream()
                print("DEBUG: RecorderThread: Closing stream...")
                stream.close()
                print("DEBUG: RecorderThread: Stream closed.")
            except Exception as close_e:
                print(f"ERROR: RecorderThread: Error closing stream post-loop: {close_e}")
        if p:
            try:
                print("DEBUG: RecorderThread: Terminating PyAudio instance...")
                p.terminate()
                print("DEBUG: RecorderThread: PyAudio instance terminated.")
            except Exception as term_e:
                print(f"ERROR: RecorderThread: Error terminating PyAudio post-loop: {term_e}")
        print("DEBUG: RecorderThread: PyAudio resources cleanup attempted.")
        full_audio_data = b''.join(self.frames)
        self.update_signal.emit(f"Total audio data size: {len(full_audio_data)} bytes")
        self.recording_finished_signal.emit(full_audio_data, self.sample_width)
        print("DEBUG: RecorderThread: recording_finished_signal emitted. Run method ending.")

    def stop(self):
        print("DEBUG: RecorderThread stop() called")
        self.is_recording = False


# --- Meeting Data & History ---
class MeetingData:
    def __init__(self, meeting_id, name, date, project_name, summary_path, transcript_path, # mentor_feedback_path=None, # <<< REMOVED
                 full_audio_path=None, json_notes_path=None):
        self.meeting_id = meeting_id;
        self.name = name;
        self.date = date;
        self.project_name = project_name;
        self.summary_path = summary_path;
        self.transcript_path = transcript_path;
        # self.mentor_feedback_path = mentor_feedback_path; # <<< REMOVED
        self.full_audio_path = full_audio_path;
        self.json_notes_path = json_notes_path

    def to_dict(self):
        return {"meeting_id": self.meeting_id, "name": self.name, "date": self.date, "project_name": self.project_name,
                "summary_path": self.summary_path, "transcript_path": self.transcript_path,
                # "mentor_feedback_path": self.mentor_feedback_path, # <<< REMOVED
                "full_audio_path": self.full_audio_path,
                "json_notes_path": self.json_notes_path}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get("meeting_id", ""), data.get("name", ""), data.get("date", ""),
                   data.get("project_name", "Unknown"), data.get("summary_path", ""), data.get("transcript_path", ""),
                   # data.get("mentor_feedback_path", None), # <<< REMOVED
                   data.get("full_audio_path", None),
                   data.get("json_notes_path", None))


class MeetingHistory:
    def __init__(self, history_file=HISTORY_FILE):
        self.history_file = history_file;
        self.meetings = [];
        self.load_history()

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.meetings = [MeetingData.from_dict(m) for m in json.load(f)]
            except Exception as e:
                print(f"Error loading history {self.history_file}: {e}"); self.meetings = []

    def add_meeting(self, meeting):
        self.meetings.append(meeting); self.save_history()

    def delete_meeting(self, meeting_id):
        meeting = next((m for m in self.meetings if m.meeting_id == meeting_id), None)
        if not meeting: return False
        # files_to_delete = [meeting.transcript_path, meeting.summary_path, meeting.mentor_feedback_path, # <<< MENTOR PATH REMOVED
        #                    meeting.full_audio_path, meeting.json_notes_path,
        #                    *glob.glob(f"{WAVE_OUTPUT_FOLDER}/{meeting.meeting_id}_chunk_*.wav")]
        files_to_delete = [meeting.transcript_path, meeting.summary_path,
                           meeting.full_audio_path, meeting.json_notes_path,
                           *glob.glob(f"{WAVE_OUTPUT_FOLDER}/{meeting.meeting_id}_chunk_*.wav")]
        # Check for mentor_feedback_path attribute before trying to access it, for backward compatibility if old data exists
        if hasattr(meeting, 'mentor_feedback_path') and meeting.mentor_feedback_path:
             files_to_delete.append(meeting.mentor_feedback_path)

        for file_path in files_to_delete:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path); print(f"Deleted file: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")
        self.meetings = [m for m in self.meetings if m.meeting_id != meeting_id];
        self.save_history();
        return True

    def save_history(self):
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump([m.to_dict() for m in self.meetings], f, indent=2)
        except IOError as e:
            print(f"Error saving history file {self.history_file}: {e}")


# --- Main Application Window ---
class MeetingTranscriberApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Meeting Summarizer & Coach v2");
        self.setGeometry(100, 100, 800, 600) # Adjusted height a bit as mentor feedback is gone
        self.api_key = OPENAI_API_KEY;
        self.api_key_valid = bool(self.api_key)
        self.history = MeetingHistory();
        self.recorder_thread = None;
        self.current_meeting_id = None
        self.is_recording = False;
        self.current_selected_meeting_id = None;
        self.processing_active = False
        self.threadpool = QThreadPool();
        self.threadpool.setMaxThreadCount(3)
        print(f"Multithreading with maximum {self.threadpool.maxThreadCount()} threads")
        # State variables
        self.current_meeting_name = "";
        self.current_project_name = "";
        self.full_audio_file_path = ""
        self.pending_chunk_files = [];
        self.chunk_transcripts = {};
        self.transcriptions_done = 0;
        self.total_chunks = 0
        self.full_meeting_transcript = "";
        self.final_summary = "";
        self.final_notes_json_string = ""
        # Paths to saved final artifacts
        self.final_transcript_path = "";
        self.final_summary_path = "";
        # self.final_mentor_path = ""; # <<< REMOVED
        self.final_notes_path = ""

        self.current_wiki_suggestion_target_section = None

        self.init_ui()
        if not self.api_key_valid: QMessageBox.warning(self, "API Key Missing",
                                                       "OPENAI_API_KEY not found. Please set it and restart.")

    def start_post_processing(self, full_audio_data, sample_width):
        self.update_status("Post-processing started...")
        QApplication.processEvents()

        if not self.current_meeting_id:
            self.display_error("Critical: current_meeting_id not set before post-processing.")
            self.finalize_meeting_processing(success=False)
            return

        if not self.full_audio_file_path:
            self.full_audio_file_path = os.path.join(WAVE_OUTPUT_FOLDER, f"{self.current_meeting_id}_full.wav")
            self.update_status(f"Saving full audio to: {self.full_audio_file_path}")
            try:
                with wave.open(self.full_audio_file_path, 'wb') as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(sample_width)
                    wf.setframerate(RATE)
                    wf.writeframes(full_audio_data)
                self.update_status("Full audio saved.")
            except Exception as e:
                self.display_error(f"Error saving full audio: {e}")
                self.full_audio_file_path = ""
                self.finalize_meeting_processing(success=False)
                return
        else:
            self.update_status(f"Using existing full audio: {self.full_audio_file_path}")

        if not full_audio_data:
            self.update_status("No audio data to process. Finalizing.")
            self.aggregate_and_start_notes()
            return

        bytes_per_sample = sample_width * CHANNELS
        if bytes_per_sample == 0:
            self.display_error("Audio sample width is zero. Cannot process.")
            self.finalize_meeting_processing(success=False)
            return

        frames_per_chunk_duration = RATE * CHUNK_DURATION_MINUTES * 60
        bytes_per_chunk_duration = frames_per_chunk_duration * bytes_per_sample

        if bytes_per_chunk_duration == 0:
            self.display_error(
                "Calculated bytes per chunk is zero (check RATE/CHUNK_DURATION_MINUTES). Cannot process.")
            self.finalize_meeting_processing(success=False)
            return

        total_bytes = len(full_audio_data)
        if total_bytes == 0:
            self.total_chunks = 0
        else:
            self.total_chunks = math.ceil(total_bytes / bytes_per_chunk_duration)
            self.total_chunks = int(self.total_chunks)
            if self.total_chunks == 0 and total_bytes > 0:
                self.total_chunks = 1

        if self.total_chunks == 0:
            self.update_status("No audio data sufficient to create chunks. Finalizing.")
            self.aggregate_and_start_notes()
            return

        self.update_status(f"Splitting audio into {self.total_chunks} chunks...")
        QApplication.processEvents()

        for i in range(self.total_chunks):
            start_byte = i * bytes_per_chunk_duration
            end_byte = start_byte + bytes_per_chunk_duration
            chunk_data = full_audio_data[start_byte:end_byte]
            if not chunk_data:
                continue
            chunk_filename = f"{self.current_meeting_id}_chunk_{i + 1}.wav"
            chunk_file_path = os.path.join(WAVE_OUTPUT_FOLDER, chunk_filename)
            self.pending_chunk_files.append(chunk_file_path)
            try:
                with wave.open(chunk_file_path, 'wb') as wf_chunk:
                    wf_chunk.setnchannels(CHANNELS)
                    wf_chunk.setsampwidth(sample_width)
                    wf_chunk.setframerate(RATE)
                    wf_chunk.writeframes(chunk_data)
            except Exception as e:
                self.display_error(f"Error saving chunk {chunk_filename}: {e}")

        if not self.pending_chunk_files:
            self.update_status("No audio chunks were successfully prepared. Finalizing.")
            self.aggregate_and_start_notes()
            return

        self.total_chunks = len(self.pending_chunk_files)
        if self.total_chunks == 0:
            self.update_status("No valid audio chunks to process after attempting to split. Finalizing.")
            self.aggregate_and_start_notes()
            return

        self.update_status(f"Starting transcription for {self.total_chunks} chunks...")
        QApplication.processEvents()
        actual_chunks_being_transcribed = 0
        for chunk_path in self.pending_chunk_files:
            if not os.path.exists(chunk_path):
                self.update_status(f"Skipping transcription for missing chunk: {os.path.basename(chunk_path)}")
                self.handle_chunk_transcription_error(f"Audio chunk file not found before starting worker.", chunk_path)
                continue
            actual_chunks_being_transcribed += 1
            worker = TranscriptionWorker(chunk_path, self.api_key)
            worker.signals.transcription_result.connect(self.handle_chunk_transcription_result)
            error_slot = functools.partial(self.handle_chunk_transcription_error, chunk_path=chunk_path)
            worker.signals.error.connect(error_slot)
            self.threadpool.start(worker)

        if actual_chunks_being_transcribed == 0 and self.pending_chunk_files:
            self.update_status("All prepared audio chunks were missing. Finalizing processing.")
        elif actual_chunks_being_transcribed < len(self.pending_chunk_files):
            self.update_status(
                f"Started transcription for {actual_chunks_being_transcribed} (out of {len(self.pending_chunk_files)} prepared) chunks due to some missing files.")
        elif actual_chunks_being_transcribed == 0:
            self.update_status("No chunks to transcribe.")
            self.aggregate_and_start_notes()

    def generate_weekly_recap(self):
        print("\nDEBUG: ============================================")
        print("DEBUG: Entered generate_weekly_recap")
        target_project = self.report_project_edit.text().strip()
        if not target_project:
            self.display_error(
                "Please enter a project name in the 'Report Project' field.")
            print("DEBUG: Exiting generate_weekly_recap (no target project entered)")
            return
        if self.processing_active or self.is_recording:
            self.display_error("Cannot generate recap while recording or processing is active.")
            print("DEBUG: Exiting generate_weekly_recap (processing or recording active)")
            return
        self.update_status(f"Generating weekly recap for project: {target_project}...")
        print("DEBUG: Recap: Disabling buttons and clearing text...")
        self.generate_recap_button.setEnabled(False)
        self.generate_report_button.setEnabled(False)
        self.report_output_text.clear()
        print("DEBUG: Recap: Calling QApplication.processEvents()...")
        QApplication.processEvents()
        print("DEBUG: Recap: QApplication.processEvents() finished.")
        print("DEBUG: Recap: Calculating date range...")
        try:
            today = datetime.now().date()
            print(f"DEBUG: Recap:   today = {today}")
            days_past_friday = (today.weekday() - 4) % 7
            print(f"DEBUG: Recap:   days_past_friday = {days_past_friday}")
            most_recent_friday = today - timedelta(days=days_past_friday)
            print(f"DEBUG: Recap:   most_recent_friday = {most_recent_friday}")
            start_of_recap_week_monday = most_recent_friday - timedelta(days=4)
            print(f"DEBUG: Recap:   start_of_recap_week_monday = {start_of_recap_week_monday}")
            start_datetime = datetime.combine(start_of_recap_week_monday, datetime.min.time())
            end_datetime = datetime.combine(most_recent_friday, datetime.max.time())
            print(f"DEBUG: Recap:   start_datetime = {start_datetime}")
            print(f"DEBUG: Recap:   end_datetime = {end_datetime}")
        except Exception as date_e:
            print(f"ERROR: Recap: Failed during date calculation: {date_e}")
            self.display_error(f"Error calculating date range: {date_e}")
            self.generate_recap_button.setEnabled(True)
            self.generate_report_button.setEnabled(True)
            return
        print("DEBUG: Recap: Date calculation complete.")
        print(f"DEBUG: Recap Target Project (lower): {target_project.lower()}")
        print(
            f"DEBUG: Recap Date Range: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')} to {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        relevant_meetings = []
        history_list_length = -1
        try:
            history_list_length = len(self.history.meetings)
            print(f"DEBUG: Recap: Accessing meeting history (Length = {history_list_length}). Preparing to iterate...")
        except Exception as hist_e:
            print(f"ERROR: Recap: Failed to access self.history.meetings: {hist_e}")
            self.display_error(f"Error accessing meeting history: {hist_e}")
            self.generate_recap_button.setEnabled(True)
            self.generate_report_button.setEnabled(True)
            return
        print(f"DEBUG: Recap: Starting iteration through {history_list_length} meetings...")
        for i, meeting in enumerate(self.history.meetings):
            print(f"DEBUG: Recap: --- Iteration {i} ---")
            meeting_id = getattr(meeting, 'meeting_id', 'N/A')
            meeting_name = getattr(meeting, 'name', 'N/A')
            print(f"DEBUG: Recap: Processing meeting index {i}, ID: {meeting_id}, Name: {meeting_name}")
            try:
                meeting_project_name = getattr(meeting, 'project_name', None)
                meeting_date_str = getattr(meeting, 'date', None)
                meeting_notes_path = getattr(meeting, 'json_notes_path', None)
                if not all([meeting_project_name, meeting_date_str, meeting_notes_path]):
                    continue
                if meeting_project_name.lower() == target_project.lower():
                    try:
                        meeting_date = datetime.strptime(meeting_date_str, "%Y-%m-%d %H:%M")
                        if start_datetime <= meeting_date <= end_datetime:
                            print(f"DEBUG: Recap:   Date is within range for {meeting_name}.")
                            full_notes_path = os.path.abspath(meeting_notes_path)
                            if os.path.exists(full_notes_path):
                                print(f"DEBUG: Recap:   Notes file exists. Adding meeting.")
                                relevant_meetings.append(meeting)
                    except ValueError as ve:
                        print(
                            f"ERROR: Recap: Could not parse date '{meeting_date_str}' for meeting '{meeting_name}': {ve}")
                        continue
                    except Exception as date_check_e:
                        print(
                            f"ERROR: Recap: Error during date parsing/checking for meeting '{meeting_name}': {date_check_e}")
                        continue
            except Exception as e:
                print(
                    f"ERROR: Recap: Unexpected error processing meeting {i} ('{meeting_name}') for recap: {type(e).__name__} - {e}")
        print(f"DEBUG: Recap: Finished filtering loop. Found {len(relevant_meetings)} relevant meetings.")
        if not relevant_meetings:
            report_md = f"## Weekly Recap: {target_project}\n"
            report_md += f"({start_datetime.strftime('%Y-%m-%d')} to {end_datetime.strftime('%Y-%m-%d')})\n\n"
            report_md += f"(No meetings with valid notes found for this project in the specified week)"
            self.report_output_text.setMarkdown(report_md)
            self.update_status(f"Recap generated: No relevant meetings found for {target_project}.")
            self.generate_recap_button.setEnabled(True)
            self.generate_report_button.setEnabled(True)
            print("DEBUG: Exiting generate_weekly_recap (no relevant meetings).")
            print("DEBUG: ============================================\n")
            return
        all_decisions = []
        all_action_items = []
        all_risks = []
        all_open_questions = []
        processed_meeting_names = set()
        print(f"DEBUG: Recap: Aggregating data from {len(relevant_meetings)} meetings...")
        try:
            print("DEBUG: Recap: Sorting relevant meetings before aggregation...")
            relevant_meetings.sort(key=lambda m: datetime.strptime(m.date, "%Y-%m-%d %H:%M"))
            print("DEBUG: Recap: Sorting complete.")
        except Exception as sort_e:
            print(f"ERROR: Recap: Failed to sort relevant meetings: {sort_e}")
        for meeting in relevant_meetings:
            meeting_name = getattr(meeting, 'name', 'Unknown Meeting')
            notes_path = getattr(meeting, 'json_notes_path', None)
            meeting_date_str = getattr(meeting, 'date', 'N/A')
            processed_meeting_names.add(f"{meeting_name} ({meeting_date_str})")
            if not notes_path: continue
            try:
                full_notes_path = os.path.abspath(notes_path)
                print(f"DEBUG: Recap:   Aggregating notes file: {full_notes_path}")
                with open(full_notes_path, 'r', encoding='utf-8') as f:
                    notes_content = f.read()
                if not notes_content.strip():
                    print(f"WARNING: Recap: Notes file is empty: {full_notes_path}")
                    continue
                notes_data = None
                try:
                    initial_data = json.loads(notes_content)
                    if isinstance(initial_data, dict) and \
                            initial_data.get("error") == "LLM did not return valid JSON format." and \
                            "raw_output" in initial_data:
                        raw_output_str = initial_data.get("raw_output", "")
                        cleaned_str = raw_output_str.strip()
                        if cleaned_str.startswith("```json"):
                            cleaned_str = cleaned_str[len("```json"):].strip()
                        elif cleaned_str.startswith("```"):
                            cleaned_str = cleaned_str[len("```"):].strip()
                        if cleaned_str.endswith("```"): cleaned_str = cleaned_str[:-len("```")].strip()
                        if cleaned_str:
                            try:
                                notes_data = json.loads(cleaned_str)
                            except json.JSONDecodeError as inner_jde:
                                print(f"ERROR: Recap:     Could not parse cleaned raw_output as JSON: {inner_jde}")
                                notes_data = {"error_parsing_raw": f"Failed: {inner_jde}"}
                        else:
                            print("ERROR: Recap:     Cleaned raw_output string is empty.")
                            notes_data = {"error_parsing_raw": "Empty raw output"}
                    else:
                        notes_data = initial_data
                except json.JSONDecodeError as outer_jde:
                    print(
                        f"ERROR: Recap: Could not decode initial JSON from file: {full_notes_path}. Error: {outer_jde}")
                    continue
                if isinstance(notes_data, dict) and "error_parsing_raw" not in notes_data:
                    decisions = notes_data.get("decisions", [])
                    actions = notes_data.get("action_items", [])
                    risks = notes_data.get("risks", [])
                    questions = notes_data.get("open_questions", [])
                    if isinstance(decisions, list): all_decisions.extend(decisions)
                    if isinstance(actions, list): all_action_items.extend(actions)
                    if isinstance(risks, list): all_risks.extend(risks)
                    if isinstance(questions, list): all_open_questions.extend(questions)
                elif isinstance(notes_data, dict) and "error_parsing_raw" in notes_data:
                    print(
                        f"WARNING: Recap: Skipping aggregation for {full_notes_path} due to raw_output parsing error.")
                else:
                    print(
                        f"WARNING: Recap: Skipping aggregation for {full_notes_path} because notes_data is not a valid dictionary.")
            except FileNotFoundError:
                print(f"ERROR: Recap: Notes file not found during aggregation: {full_notes_path}")
            except IOError as ioe:
                print(f"ERROR: Recap: Could not read notes file during aggregation: {full_notes_path}. Error: {ioe}")
            except Exception as agg_e:
                print(f"ERROR: Recap: Unexpected error aggregating {full_notes_path}: {type(agg_e).__name__} - {agg_e}")
        print(f"DEBUG: Recap: Aggregation complete.")
        print(
            f"DEBUG: Recap: Total Decisions: {len(all_decisions)}, Actions: {len(all_action_items)}, Risks: {len(all_risks)}, Questions: {len(all_open_questions)}")
        llm_input_text = ""
        report_sections = {
            "Decisions Made": all_decisions,
            "Action Items Assigned": all_action_items,
            "Risks or Blockers Identified": all_risks,
            "Open Questions Raised": all_open_questions
        }
        has_content_for_llm = False
        for title, items in report_sections.items():
            unique_items = []
            seen_items = set()
            if isinstance(items, list):
                for item in items:
                    try:
                        item_str = str(item).strip()
                        if item_str and item_str not in seen_items:
                            unique_items.append(item)
                            seen_items.add(item_str)
                    except Exception as str_e:
                        print(f"WARNING: Could not convert item to string during deduplication: {str_e}")
            if unique_items:
                has_content_for_llm = True
                llm_input_text += f"#### {title}:\n"
                for item in unique_items:
                    try:
                        item_text = str(item).replace('\n', ' ').strip()
                        if item_text:
                            llm_input_text += f"*   {item_text}\n"
                    except Exception as format_e:
                        llm_input_text += f"*   [Error formatting item: {format_e}]\n"
                llm_input_text += "\n"
        week_title_str = f"Week: {start_datetime.strftime('%B %d, %Y')} - {end_datetime.strftime('%B %d, %Y')}"
        if not has_content_for_llm:
            print("DEBUG: Recap: No unique content found to send to LLM. Displaying basic message.")
            report_md = f"## Weekly Recap: {target_project}\n"
            report_md += f"### {week_title_str}\n\n"
            if processed_meeting_names:
                report_md += "*(Data aggregated from meetings: " + ", ".join(
                    sorted(list(processed_meeting_names))) + ")*\n\n"
            report_md += "(No unique Decisions, Action Items, Risks, or Questions found in the notes processed for this week.)\n"
            self.report_output_text.setMarkdown(report_md)
            self.update_status(f"Weekly recap generated: No items found for {target_project}.")
            self.generate_recap_button.setEnabled(True)
            self.generate_report_button.setEnabled(True)
            print("DEBUG: Exiting generate_weekly_recap (no content for LLM).")
            print("DEBUG: ============================================\n")
            return
        print("DEBUG: Recap: Found content. Launching LLMRecapWorker...")
        self.update_status(f"Generating narrative summary for {target_project}...")
        QApplication.processEvents()
        worker = LLMRecapWorker(
            aggregated_bullets_text=llm_input_text,
            project_name=target_project,
            week_str=week_title_str,
            api_key=self.api_key
        )
        worker.signals.recap_result.connect(self.handle_recap_result)
        worker.signals.error.connect(self.handle_recap_error)
        self.threadpool.start(worker)
        print("DEBUG: Recap: LLMRecapWorker submitted to threadpool.")

    def handle_recap_result(self, narrative_summary):
        print("DEBUG: handle_recap_result received.")
        target_project = self.report_project_edit.text().strip()
        try:
            today = datetime.now().date()
            days_past_friday = (today.weekday() - 4) % 7
            most_recent_friday = today - timedelta(days=days_past_friday)
            start_of_recap_week_monday = most_recent_friday - timedelta(days=4)
            week_title_str = f"Week: {start_of_recap_week_monday.strftime('%B %d, %Y')} - {most_recent_friday.strftime('%B %d, %Y')}"
        except Exception:
            week_title_str = "Last Week"
        report_md = f"## Weekly Recap: {target_project}\n"
        report_md += f"### {week_title_str}\n\n"
        report_md += "#### Executive Summary:\n"
        report_md += narrative_summary
        report_md += "\n\n---\n"
        self.report_output_text.setMarkdown(report_md)
        self.update_status(f"Weekly recap generated for {target_project}.")
        self.generate_recap_button.setEnabled(True)
        self.generate_report_button.setEnabled(True)
        print("DEBUG: handle_recap_result finished.")
        print("DEBUG: ============================================\n")

    def handle_recap_error(self, error_message):
        print(f"ERROR: handle_recap_error received: {error_message}")
        self.display_error(f"Failed to generate LLM narrative summary: {error_message}")
        self.update_status("Error generating weekly recap summary.")
        self.generate_recap_button.setEnabled(True)
        self.generate_report_button.setEnabled(True)
        print("DEBUG: handle_recap_error finished.")
        print("DEBUG: ============================================\n")

    def init_ui(self):
        main_widget = QWidget();
        main_layout = QVBoxLayout(main_widget)
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Meeting Name:"))
        self.meeting_name_edit = QLineEdit();
        self.meeting_name_edit.setPlaceholderText("Meeting name (required)")
        controls_layout.addWidget(self.meeting_name_edit)
        controls_layout.addWidget(QLabel("Project:"))
        self.project_name_edit = QLineEdit();
        self.project_name_edit.setPlaceholderText("Project name (optional)")
        controls_layout.addWidget(self.project_name_edit)
        self.start_button = QPushButton("Start Meeting");
        self.start_button.clicked.connect(self.start_meeting)
        self.stop_button = QPushButton("End Meeting & Process");
        self.stop_button.clicked.connect(self.stop_meeting);
        self.stop_button.setEnabled(False)
        if not self.api_key_valid: self.start_button.setEnabled(False); self.meeting_name_edit.setEnabled(
            False); self.project_name_edit.setEnabled(False)
        controls_layout.addWidget(self.start_button);
        controls_layout.addWidget(self.stop_button);
        main_layout.addLayout(controls_layout)

        content_splitter = QSplitter(Qt.Horizontal)
        history_pane_widget = QWidget()
        history_pane_layout = QVBoxLayout(history_pane_widget)
        history_pane_layout.setContentsMargins(0, 0, 0, 0)
        history_pane_layout.addWidget(QLabel("Meeting History:"))
        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.load_meeting_from_history)
        history_pane_layout.addWidget(self.history_list, 1)

        history_buttons_layout = QHBoxLayout()
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.clicked.connect(self.delete_selected_meeting)
        self.delete_button.setEnabled(False)
        self.retry_button = QPushButton("Retry Process Selected")
        self.retry_button.clicked.connect(self.retry_selected_meeting)
        self.retry_button.setEnabled(False)
        history_buttons_layout.addWidget(self.delete_button)
        history_buttons_layout.addWidget(self.retry_button)
        history_pane_layout.addLayout(history_buttons_layout)

        report_gen_group = QWidget()
        report_gen_layout_outer = QVBoxLayout(report_gen_group)
        report_gen_layout_outer.setContentsMargins(0, 5, 0, 0)
        report_project_input_layout = QHBoxLayout()
        report_project_input_layout.addWidget(QLabel("Report Project:"))
        self.report_project_edit = QLineEdit()
        self.report_project_edit.setPlaceholderText("Project for Notes/Recap")
        report_project_input_layout.addWidget(self.report_project_edit)
        report_gen_layout_outer.addLayout(report_project_input_layout)
        report_buttons_layout = QHBoxLayout()
        self.generate_report_button = QPushButton("Stand-up Notes (120h)")
        self.generate_report_button.clicked.connect(self.generate_standup_report)
        report_buttons_layout.addWidget(self.generate_report_button)
        self.generate_recap_button = QPushButton("Weekly Recap (Exec)")
        self.generate_recap_button.clicked.connect(self.generate_weekly_recap)
        report_buttons_layout.addWidget(self.generate_recap_button)
        report_gen_layout_outer.addLayout(report_buttons_layout)
        report_gen_layout_outer.addWidget(QLabel("Generated Notes / Recap:"))
        self.report_output_text = QTextEdit()
        self.report_output_text.setReadOnly(True)
        self.report_output_text.setAcceptRichText(True)
        report_gen_layout_outer.addWidget(self.report_output_text, 1)
        history_pane_layout.addWidget(report_gen_group)

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(QLabel("Selected: Transcript"));
        self.history_transcript = QTextEdit();
        self.history_transcript.setReadOnly(True);
        details_layout.addWidget(self.history_transcript, 1) # Adjusted stretch factor
        details_layout.addWidget(QLabel("Selected: Summary"));
        self.history_summary = QTextEdit();
        self.history_summary.setReadOnly(True);
        self.history_summary.setAcceptRichText(True);
        details_layout.addWidget(self.history_summary, 1) # Adjusted stretch factor

        # --- Mentor Feedback UI Removed ---
        # details_layout.addWidget(QLabel("Selected: Mentor Feedback (Aldis)"));
        # self.history_mentor_feedback = QTextEdit();
        # self.history_mentor_feedback.setReadOnly(True);
        # self.history_mentor_feedback.setAcceptRichText(True);
        # details_layout.addWidget(self.history_mentor_feedback, 1) # Adjusted stretch factor

        wiki_update_group = QWidget()
        wiki_update_layout = QVBoxLayout(wiki_update_group)
        wiki_update_layout.setContentsMargins(0, 10, 0, 0)
        wiki_controls_layout = QHBoxLayout()
        wiki_controls_layout.addWidget(QLabel("Update Wiki Section:"))
        self.wiki_section_combo = QComboBox()
        self.wiki_section_combo.addItems(["Overview", "Goals", "Key Features", "Daily Log", "Risks/Mitigations"])
        wiki_controls_layout.addWidget(self.wiki_section_combo)
        self.suggest_wiki_updates_button = QPushButton("Suggest Updates")
        self.suggest_wiki_updates_button.clicked.connect(self.handle_suggest_wiki_updates_click)
        self.suggest_wiki_updates_button.setEnabled(False)
        wiki_controls_layout.addWidget(self.suggest_wiki_updates_button)
        wiki_update_layout.addLayout(wiki_controls_layout)
        wiki_update_layout.addWidget(QLabel("AI Suggested Wiki Section Content (Editable):"))
        self.wiki_suggestion_textedit = QTextEdit()
        self.wiki_suggestion_textedit.setPlaceholderText("AI suggestions will appear here...")
        wiki_update_layout.addWidget(self.wiki_suggestion_textedit, 2) # Keep this stretch
        wiki_apply_buttons_layout = QHBoxLayout()
        self.apply_wiki_changes_button = QPushButton("Apply to Wiki File")
        self.apply_wiki_changes_button.clicked.connect(
            self.handle_apply_wiki_changes)
        self.apply_wiki_changes_button.setEnabled(False)
        wiki_apply_buttons_layout.addWidget(self.apply_wiki_changes_button)
        self.discard_wiki_suggestion_button = QPushButton("Discard Suggestion")
        self.discard_wiki_suggestion_button.clicked.connect(
            self.handle_discard_wiki_suggestion)
        self.discard_wiki_suggestion_button.setEnabled(False)
        wiki_apply_buttons_layout.addWidget(self.discard_wiki_suggestion_button)
        wiki_update_layout.addLayout(wiki_apply_buttons_layout)
        details_layout.addWidget(wiki_update_group, 2) # Keep this stretch

        content_splitter.addWidget(history_pane_widget)
        content_splitter.addWidget(details_widget)
        content_splitter.setSizes([350, 450])
        main_layout.addWidget(content_splitter, 1)

        self.status_label = QLabel("Ready.");
        main_layout.addWidget(self.status_label)
        self.setCentralWidget(main_widget);
        self.load_history_list()

    def update_status(self, message):
        print(f"STATUS: {message}"); self.status_label.setText(message); QApplication.processEvents()

    def display_error(self, message):
        print(f"ERROR: {message}"); QMessageBox.warning(self, "Error", message); self.update_status(f"Error: {message}")

    def _format_meeting_notes_md(self, meeting, notes_data):
        md_string = ""
        if not isinstance(notes_data, dict):
            md_string += f"  *   **Notes Error:** Could not parse JSON notes for this meeting.\n"
            return md_string
        sections_to_include = {
            "Decisions": notes_data.get("decisions", []),
            "Action Items": notes_data.get("action_items", []),
            "Risks": notes_data.get("risks", []),
            "Open Questions": notes_data.get("open_questions", [])
        }
        has_content = False
        meeting_md = ""
        meeting_name = getattr(meeting, 'name', 'Unknown Meeting')
        meeting_project = getattr(meeting, 'project_name', 'Unknown Project')
        meeting_date = getattr(meeting, 'date', 'Unknown Date')
        for title, items in sections_to_include.items():
            if items and isinstance(items, list) and len(items) > 0:
                has_content = True
                meeting_md += f"  *   **{title}:**\n"
                for item_index, item in enumerate(items):
                    try:
                        item_text = str(item).replace('\n', ' ')
                        meeting_md += f"      *   {item_text}\n"
                    except Exception as str_e:
                        print(
                            f"ERROR: Could not convert item {item_index} in section '{title}' of meeting {meeting_name} to string: {str_e}")
                        meeting_md += f"      *   [Error converting item to string]\n"
        if has_content:
            md_string += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
            md_string += meeting_md
        else:
            print(f"DEBUG:   No content found in specified sections for {meeting_name}")
        return md_string

    def generate_standup_report(self):
        target_project = self.report_project_edit.text().strip()
        if not target_project:
            self.display_error("Please enter a project name in the 'Report Project' field.")
            return
        if self.processing_active or self.is_recording:
            self.display_error("Cannot generate report while recording or processing is active.")
            return
        try:
            _ = timedelta(hours=1)
        except NameError:
            self.display_error("FATAL: timedelta is not defined. Check imports.")
            print("FATAL ERROR: timedelta is not defined. Check imports at the top of the file.")
            return
        except Exception as e:
            self.display_error(f"FATAL: Error using timedelta: {e}")
            print(f"FATAL ERROR: Error using timedelta: {e}")
            return
        self.update_status(f"Generating stand-up notes for project: {target_project}...")
        self.generate_report_button.setEnabled(False)
        self.generate_recap_button.setEnabled(False)
        self.report_output_text.clear()
        QApplication.processEvents()
        hours_back = 120
        now = datetime.now()
        cutoff_time = now - timedelta(hours=hours_back)
        target_project_lower = target_project.lower()
        relevant_meetings = []
        for i, meeting in enumerate(self.history.meetings):
            meeting_id = getattr(meeting, 'meeting_id', 'N/A')
            meeting_name = getattr(meeting, 'name', 'N/A')
            try:
                meeting_project_name = getattr(meeting, 'project_name', None)
                meeting_date_str = getattr(meeting, 'date', None)
                meeting_notes_path = getattr(meeting, 'json_notes_path', None)
                if not meeting_project_name:
                    continue
                if not meeting_date_str:
                    continue
                if meeting_project_name.lower() == target_project_lower:
                    meeting_date = datetime.strptime(meeting_date_str, "%Y-%m-%d %H:%M")
                    if meeting_date >= cutoff_time:
                        notes_path_exists = False
                        if meeting_notes_path:
                            if isinstance(meeting_notes_path, str) and meeting_notes_path.strip():
                                try:
                                    full_notes_path = os.path.abspath(meeting_notes_path)
                                    notes_path_exists = os.path.exists(full_notes_path)
                                except Exception as path_e:
                                    print(f"ERROR: Could not check existence of path '{meeting_notes_path}': {path_e}")
                                    notes_path_exists = False
                            else:
                                notes_path_exists = False
                        if notes_path_exists:
                            relevant_meetings.append(meeting)
            except ValueError as ve:
                print(
                    f"ERROR: Could not parse date '{meeting_date_str}' for meeting '{meeting_name}' during report generation: {ve}. Skipping meeting.")
            except AttributeError as ae:
                print(
                    f"ERROR: Meeting record for '{meeting_name}' might be missing attributes ({ae}). Skipping for report.")
            except Exception as e:
                print(
                    f"ERROR: Unexpected error processing meeting {i} ('{meeting_name}'): {type(e).__name__} - {e}. Skipping meeting.")
        if not relevant_meetings:
            report_md = f"## Stand-up Notes: {target_project} (Last {hours_back} Hours)\n\n"
            report_md += f"(No relevant meeting notes found with existing JSON files for this project in the specified time frame)"
            self.report_output_text.setMarkdown(report_md)
            self.update_status(f"Report generated: No relevant notes found for {target_project}.")
            self.generate_report_button.setEnabled(True)
            self.generate_recap_button.setEnabled(True)
            return
        try:
            relevant_meetings.sort(key=lambda m: datetime.strptime(m.date, "%Y-%m-%d %H:%M"))
        except Exception as e:
            self.display_error(f"Error sorting meetings: {e}")
            print(f"ERROR: Could not sort meetings: {e}")
            self.generate_report_button.setEnabled(True)
            self.generate_recap_button.setEnabled(True)
            return
        final_report_md = f"## Stand-up Notes: {target_project} (Last {hours_back} Hours)\n\n"
        meetings_processed_count = 0
        for meeting in relevant_meetings:
            meeting_name = getattr(meeting, 'name', 'Unknown Meeting')
            notes_path = getattr(meeting, 'json_notes_path', None)
            meeting_project = getattr(meeting, 'project_name', 'Unknown Project')
            meeting_date = getattr(meeting, 'date', 'Unknown Date')
            if not notes_path:
                continue
            try:
                if not isinstance(notes_path, str) or not notes_path.strip():
                    print(f"ERROR: Invalid notes path type or empty for {meeting_name}: {notes_path}. Skipping file.")
                    final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                    final_report_md += "  *   **Error:** Invalid notes file path stored.\n\n---\n\n"
                    continue
                full_notes_path = os.path.abspath(notes_path)
                with open(full_notes_path, 'r', encoding='utf-8') as f:
                    notes_content = f.read()
                    notes_data = None
                    if not notes_content.strip():
                        print(f"WARNING: Notes file is empty: {full_notes_path}")
                        notes_data = {}
                    else:
                        try:
                            initial_data = json.loads(notes_content)
                            print(
                                f"DEBUG:   Initial JSON loaded. Keys: {list(initial_data.keys()) if isinstance(initial_data, dict) else 'Not a dict'}")
                            if isinstance(initial_data, dict) and \
                                    initial_data.get("error") == "LLM did not return valid JSON format." and \
                                    "raw_output" in initial_data:
                                raw_output_str = initial_data.get("raw_output", "")
                                cleaned_str = raw_output_str.strip()
                                if cleaned_str.startswith("```json"):
                                    cleaned_str = cleaned_str[len("```json"):].strip()
                                elif cleaned_str.startswith("```"):
                                    cleaned_str = cleaned_str[len("```"):].strip()
                                if cleaned_str.endswith("```"):
                                    cleaned_str = cleaned_str[:-len("```")].strip()
                                if not cleaned_str:
                                    print("ERROR:   Cleaned raw_output string is empty.")
                                    notes_data = {"error_parsing_raw": "Cleaned raw_output was empty"}
                                else:
                                    try:
                                        notes_data = json.loads(cleaned_str)
                                        print("DEBUG:   Successfully parsed JSON from cleaned raw_output.")
                                    except json.JSONDecodeError as inner_jde:
                                        print(f"ERROR:   Could not parse cleaned raw_output as JSON: {inner_jde}")
                                        print(f"ERROR:   Cleaned Raw Output was: {cleaned_str}")
                                        notes_data = {"error_parsing_raw": f"Failed to parse raw_output: {inner_jde}",
                                                      "original_raw": cleaned_str}
                            else:
                                print(
                                    "DEBUG:   Initial JSON seems valid (no specific error structure found). Using as notes_data.")
                                notes_data = initial_data
                        except json.JSONDecodeError as outer_jde:
                            print(
                                f"ERROR: Could not decode initial JSON from file: {full_notes_path}. Error: {outer_jde}")
                            final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                            final_report_md += f"  *   **Error:** Could not read notes file (Invalid JSON): {outer_jde}.\n\n---\n\n"
                            continue
                    if notes_data is None:
                        print(
                            f"ERROR: notes_data is None after attempting to load/parse for {meeting_name}. Skipping formatting.")
                        final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                        final_report_md += f"  *   **Error:** Failed to load or parse notes data structure.\n\n---\n\n"
                        continue
                    elif isinstance(notes_data, dict) and "error_parsing_raw" in notes_data:
                        print(f"ERROR: Failed parsing raw_output for {meeting_name}. Skipping formatting.")
                        final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                        final_report_md += f"  *   **Error:** Notes file contained an error structure and the raw data inside could not be parsed.\n\n---\n\n"
                        continue
                    print(
                        f"DEBUG:   Final notes_data type: {type(notes_data)}, Keys: {list(notes_data.keys()) if isinstance(notes_data, dict) else 'Not a dict'}")
                    meeting_md_snippet = self._format_meeting_notes_md(meeting, notes_data)
                    print(f"DEBUG:   _format_meeting_notes_md returned snippet (len={len(meeting_md_snippet)}).")
                    if meeting_md_snippet:
                        final_report_md += meeting_md_snippet + "\n---\n\n"
                        meetings_processed_count += 1
                        print(f"DEBUG:   Added snippet to final report. Processed count: {meetings_processed_count}")
                    else:
                        print(f"DEBUG:   Snippet was empty, not added to report.")
            except FileNotFoundError:
                print(f"ERROR: Notes file not found during formatting: {full_notes_path}")
                final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                final_report_md += "  *   **Error:** Notes file not found at specified path.\n\n---\n\n"
            except IOError as ioe:
                print(f"ERROR: Could not open or read notes file {full_notes_path} for report: {ioe}")
                final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                final_report_md += f"  *   **Error:** Could not read notes file (IO Error): {ioe}.\n\n---\n\n"
            except Exception as e:
                print(
                    f"ERROR: Unexpected error processing notes file {notes_path} or formatting meeting {meeting_name}: {type(e).__name__} - {e}")
                final_report_md += f"### {meeting_name} ({meeting_project} - {meeting_date})\n"
                final_report_md += f"  *   **Error:** Could not process notes file ({type(e).__name__}: {e}).\n\n---\n\n"
        if meetings_processed_count == 0:
            if relevant_meetings:
                if "Error:" not in final_report_md[-500:]:
                    final_report_md += "(No extracted Decisions, Action Items, Risks, or Questions found or processed successfully in relevant meetings)\n"
        print("DEBUG: Setting final report markdown in UI...")
        try:
            self.report_output_text.setMarkdown(final_report_md)
        except Exception as ui_e:
            try:
                self.report_output_text.setPlainText(final_report_md)
            except Exception as ui_plain_e:
                print(f"ERROR: Failed to set plain text in QTextEdit: {ui_plain_e}")
                self.report_output_text.setPlainText("Error: Could not display report content.")
        self.update_status(f"Stand-up notes report generated for project '{target_project}'.")
        self.generate_report_button.setEnabled(True)
        self.generate_recap_button.setEnabled(True)

    def load_history_list(self):
        self.history_list.clear()
        sorted_meetings = sorted(self.history.meetings, key=lambda m: m.date, reverse=True)
        for meeting in sorted_meetings: item = QListWidgetItem(
            f"{meeting.name} ({meeting.project_name} - {meeting.date})"); item.setData(Qt.UserRole,
                                                                                       meeting.meeting_id); self.history_list.addItem(
            item)
        self.clear_history_displays();
        self.current_selected_meeting_id = None

    def clear_history_displays(self):
        self.history_transcript.clear();
        self.history_summary.clear()
        # self.history_mentor_feedback.clear() # <<< REMOVED
        self.wiki_suggestion_textedit.clear()
        self.suggest_wiki_updates_button.setEnabled(False)
        self.apply_wiki_changes_button.setEnabled(False)
        self.discard_wiki_suggestion_button.setEnabled(False)
        self.delete_button.setEnabled(False);
        self.retry_button.setEnabled(False)

    def load_meeting_from_history(self, item):
        meeting_id = item.data(Qt.UserRole);
        self.current_selected_meeting_id = meeting_id;
        self.delete_button.setEnabled(True)
        meeting = next((m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id), None)
        if not meeting: self.display_error("Selected meeting data not found."); self.clear_history_displays(); return

        can_retry = bool(meeting.full_audio_path and os.path.exists(meeting.full_audio_path));
        self.retry_button.setEnabled(can_retry)
        if not can_retry: print(
            f"Retry disabled: Full audio path missing or file not found ('{meeting.full_audio_path}')")

        if meeting.project_name and meeting.project_name != "Unknown" and meeting.project_name.strip() != "":
            self.suggest_wiki_updates_button.setEnabled(True)
            self.report_project_edit.setText(meeting.project_name)
        else:
            self.suggest_wiki_updates_button.setEnabled(False)
            self.report_project_edit.clear()

        self.wiki_suggestion_textedit.clear()
        self.apply_wiki_changes_button.setEnabled(False)
        self.discard_wiki_suggestion_button.setEnabled(False)

        try:
            if meeting.transcript_path and os.path.exists(meeting.transcript_path):
                with open(meeting.transcript_path, 'r', encoding='utf-8') as f:
                    self.history_transcript.setText(f.read())
            else:
                self.history_transcript.setText("Transcript file not found.")
        except Exception as e:
            self.display_error(
                f"Error loading transcript file {meeting.transcript_path}: {e}");
            self.history_transcript.setText(
                "Error loading transcript.")
        try:
            if meeting.summary_path and os.path.exists(meeting.summary_path):
                with open(meeting.summary_path, 'r', encoding='utf-8') as f:
                    self.history_summary.setHtml(markdown2.markdown(f.read()))
            else:
                self.history_summary.setText("Summary file not found.")
        except Exception as e:
            self.display_error(f"Error loading summary file {meeting.summary_path}: {e}");
            self.history_summary.setText(
                "Error loading summary.")

        # --- Mentor Feedback Loading Removed ---
        # try:
        #     if hasattr(meeting, 'mentor_feedback_path') and meeting.mentor_feedback_path and os.path.exists(meeting.mentor_feedback_path):
        #         with open(meeting.mentor_feedback_path, 'r', encoding='utf-8') as f:
        #             self.history_mentor_feedback.setHtml(markdown2.markdown(f.read()))
        #     else:
        #         self.history_mentor_feedback.setText("Mentor feedback file not found or N/A.")
        # except Exception as e:
        #     self.display_error(
        #         f"Error loading mentor feedback file {getattr(meeting, 'mentor_feedback_path', 'N/A')}: {e}");
        #     self.history_mentor_feedback.setText(
        #         "Error loading mentor feedback.")

    def delete_selected_meeting(self):
        if not self.current_selected_meeting_id: return
        meeting_to_delete = next((m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id),
                                 None)
        if not meeting_to_delete: self.display_error("Cannot find meeting to delete."); return
        reply = QMessageBox.question(self, 'Confirm Delete', f"Delete '{meeting_to_delete.name}' and associated files?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.history.delete_meeting(self.current_selected_meeting_id):
                self.update_status(
                    f"Meeting '{meeting_to_delete.name}' deleted."); self.clear_history_displays(); self.current_selected_meeting_id = None; self.load_history_list()
            else:
                self.display_error(f"Failed to delete meeting '{meeting_to_delete.name}'.")

    def handle_suggest_wiki_updates_click(self):
        if not self.current_selected_meeting_id:
            self.display_error("Please select a meeting from the history first.")
            return
        if self.processing_active:
            self.display_error("Another meeting processing is active. Please wait.")
            return
        selected_meeting = next((m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id),
                                None)
        if not selected_meeting: self.display_error("Selected meeting data not found."); return
        if not selected_meeting.project_name or selected_meeting.project_name == "Unknown" or selected_meeting.project_name.strip() == "":
            self.display_error(
                f"Meeting '{selected_meeting.name}' does not have a project assigned. Cannot suggest wiki updates.")
            return
        target_section_title = self.wiki_section_combo.currentText()
        if not target_section_title: self.display_error("Please select a wiki section to update."); return
        project_name = selected_meeting.project_name
        wiki_file_path = self._get_project_wiki_path(project_name)
        if not wiki_file_path:
            self.display_error(f"Could not determine wiki path for project '{project_name}'.");
            return
        if not os.path.exists(wiki_file_path):
            reply = QMessageBox.question(self, "Wiki File Not Found",
                                         f"The wiki file for project '{project_name}'\n({os.path.basename(wiki_file_path)})\ndoes not exist.\n\nCreate it with a basic template including sections like Overview, Goals, etc?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                try:
                    os.makedirs(os.path.dirname(wiki_file_path), exist_ok=True)
                    with open(wiki_file_path, 'w', encoding='utf-8') as wf_new:
                        wf_new.write(f"# Project Wiki - {project_name}\n\n")
                        wf_new.write("## Overview\n\n\n")
                        wf_new.write("## Goals\n\n\n")
                        wf_new.write("## Key Features\n\n\n")
                        wf_new.write("## Daily Log\n\n\n")
                        wf_new.write("## Risks/Mitigations\n\n\n")
                    self.update_status(f"Created template wiki: {os.path.basename(wiki_file_path)}")
                except Exception as e_create:
                    self.display_error(f"Could not create template wiki: {e_create}")
                    return
            else:
                self.update_status("Wiki update suggestion cancelled (file does not exist and template not created).")
                return
        current_section_content = self._read_wiki_section(wiki_file_path, target_section_title)
        if current_section_content is None:
            self.update_status(f"Failed to read section '{target_section_title}'. Aborting suggestion.")
            return
        meeting_info_source_path = selected_meeting.transcript_path
        meeting_info_text_source = "transcript"
        if not meeting_info_source_path or not os.path.exists(meeting_info_source_path):
            if selected_meeting.json_notes_path and os.path.exists(selected_meeting.json_notes_path):
                meeting_info_source_path = selected_meeting.json_notes_path
                meeting_info_text_source = "JSON notes"
            else:
                self.display_error("Neither transcript nor JSON notes found for the selected meeting.");
                return
        try:
            with open(meeting_info_source_path, 'r', encoding='utf-8') as f_info:
                meeting_info_text = f_info.read()
        except Exception as e_read_info:
            self.display_error(f"Error reading meeting info from {meeting_info_source_path}: {e_read_info}");
            return
        if not meeting_info_text.strip(): self.display_error("Meeting information (transcript/notes) is empty."); return
        self.update_status(
            f"Generating AI suggestion for '{target_section_title}' in '{project_name}' wiki (using {meeting_info_text_source})...")
        self.suggest_wiki_updates_button.setEnabled(False);
        self.apply_wiki_changes_button.setEnabled(False);
        self.discard_wiki_suggestion_button.setEnabled(False)
        self.wiki_suggestion_textedit.setPlaceholderText("AI is thinking...");
        QApplication.processEvents()
        worker = WikiUpdateSuggestionWorker(current_section_content, meeting_info_text, target_section_title,
                                            project_name, self.api_key)
        worker.signals.wiki_suggestion_result.connect(self._handle_wiki_suggestion_received)
        worker.signals.error.connect(self._handle_wiki_suggestion_error)
        worker.signals.finished.connect(self._handle_wiki_suggestion_finished)
        self.threadpool.start(worker)

    def _handle_wiki_suggestion_received(self, suggested_text, target_section_title):
        self.current_wiki_suggestion_target_section = target_section_title
        self.wiki_suggestion_textedit.setText(suggested_text)
        self.apply_wiki_changes_button.setEnabled(True)
        self.discard_wiki_suggestion_button.setEnabled(True)
        self.update_status(f"AI suggestion received for section: {target_section_title}")

    def _handle_wiki_suggestion_error(self, error_message):
        self.display_error(f"Wiki Suggestion Error: {error_message}")
        self.wiki_suggestion_textedit.setPlaceholderText("Error generating suggestion. See status bar.")

    def _handle_wiki_suggestion_finished(self):
        if self.current_selected_meeting_id:
            selected_meeting = next(
                (m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id), None)
            if selected_meeting and selected_meeting.project_name and selected_meeting.project_name != "Unknown":
                self.suggest_wiki_updates_button.setEnabled(True)
            else:
                self.suggest_wiki_updates_button.setEnabled(False)
        else:
            self.suggest_wiki_updates_button.setEnabled(False)

    def handle_apply_wiki_changes(self):
        if not self.current_selected_meeting_id: self.display_error("Cannot apply: No meeting selected."); return
        if not self.current_wiki_suggestion_target_section: self.display_error(
            "Cannot apply: No active wiki suggestion."); return
        selected_meeting = next((m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id),
                                None)
        if not selected_meeting or not selected_meeting.project_name or selected_meeting.project_name == "Unknown":
            self.display_error("Cannot apply: Selected meeting or its project is invalid.");
            return
        project_name = selected_meeting.project_name
        target_section_title = self.current_wiki_suggestion_target_section
        new_section_content_from_llm = self.wiki_suggestion_textedit.toPlainText()
        wiki_file_path = self._get_project_wiki_path(project_name)
        if not wiki_file_path: self.display_error(
            f"Cannot apply: Could not get wiki path for '{project_name}'."); return
        reply = QMessageBox.question(self, 'Confirm Wiki Update',
                                     f"Apply changes to '{target_section_title}' in wiki for '{project_name}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No: self.update_status("Wiki update cancelled."); return
        self.update_status(f"Applying changes to '{target_section_title}' in '{project_name}' wiki...")
        QApplication.processEvents()
        success = False
        if target_section_title.lower() == "daily log":
            if new_section_content_from_llm.strip().lower() == "no new log entries from this meeting.":
                self.update_status("No new log entries to add from this meeting.")
                success = True
            else:
                success = self._update_daily_log_section(wiki_file_path, new_section_content_from_llm)
        else:
            success = self._replace_wiki_section(wiki_file_path, target_section_title, new_section_content_from_llm)
        if success:
            self.update_status(f"Wiki section '{target_section_title}' successfully updated.")
        else:
            self.update_status(
                f"Failed to update wiki section '{target_section_title}'. Check messages.")
        self.wiki_suggestion_textedit.clear();
        self.wiki_suggestion_textedit.setPlaceholderText("AI suggestions will appear here...")
        self.apply_wiki_changes_button.setEnabled(False);
        self.discard_wiki_suggestion_button.setEnabled(False)
        self.current_wiki_suggestion_target_section = None

    def handle_discard_wiki_suggestion(self):
        self.wiki_suggestion_textedit.clear()
        self.wiki_suggestion_textedit.setPlaceholderText("AI suggestions will appear here...")
        self.apply_wiki_changes_button.setEnabled(False)
        self.discard_wiki_suggestion_button.setEnabled(False)
        self.current_wiki_suggestion_target_section = None
        self.update_status("Wiki suggestion discarded.")

    def retry_selected_meeting(self):
        if not self.current_selected_meeting_id:
            self.display_error("No meeting selected to retry.")
            return
        if self.processing_active:
            self.display_error("Another meeting processing is already active. Please wait.")
            return
        meeting_to_retry = next((m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id),
                                None)
        if not meeting_to_retry:
            self.display_error("Could not find data for the selected meeting.")
            return
        full_audio_path_to_retry = meeting_to_retry.full_audio_path
        if not full_audio_path_to_retry or not os.path.exists(full_audio_path_to_retry):
            self.display_error(f"Cannot retry: Original full audio file not found at '{full_audio_path_to_retry}'.")
            self.retry_button.setEnabled(False)
            return
        has_results = bool(meeting_to_retry.transcript_path and os.path.exists(
            meeting_to_retry.transcript_path))
        if has_results:
            reply = QMessageBox.question(self, 'Confirm Retry',
                                         f"Meeting '{meeting_to_retry.name}' already has results. Retrying will overwrite them. Continue?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return
        self.update_status(f"Retrying processing for: {meeting_to_retry.name}")
        self.retry_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.processing_active = True
        try:
            with wave.open(full_audio_path_to_retry, 'rb') as wf:
                loaded_audio_data = wf.readframes(wf.getnframes())
                loaded_sample_width = wf.getsampwidth()
                if wf.getnchannels() != CHANNELS or wf.getframerate() != RATE:
                    self.display_error("Warning: Audio parameters in saved file differ from current settings.")
        except Exception as e:
            self.display_error(f"Error reading audio file for retry: {e}")
            self.retry_button.setEnabled(True)
            self.delete_button.setEnabled(True)
            self.processing_active = False
            return
        self.current_meeting_id = meeting_to_retry.meeting_id
        self.current_meeting_name = meeting_to_retry.name
        self.current_project_name = meeting_to_retry.project_name
        self.full_audio_file_path = full_audio_path_to_retry
        self.reset_processing_state()
        self.start_post_processing(loaded_audio_data, loaded_sample_width)

    def start_meeting(self):
        if self.is_recording: return
        if self.processing_active: self.display_error("Another meeting processing is active."); return
        meeting_name = self.meeting_name_edit.text().strip();
        project_name = self.project_name_edit.text().strip()
        if not meeting_name: self.display_error("Please enter a meeting name."); return
        if not self.api_key_valid: self.display_error("Cannot start: API Key is missing."); return
        self.current_meeting_name = meeting_name
        self.current_project_name = project_name if project_name else "Default"
        self.current_meeting_id = f"meeting_{int(time.time())}"
        self.full_audio_file_path = ""
        self.reset_processing_state()
        self.update_status(f"Starting meeting: {self.current_meeting_name} (Project: {self.current_project_name})")
        self.processing_active = True
        self.recorder_thread = RecorderThread()
        self.recorder_thread.update_signal.connect(self.update_status)
        self.recorder_thread.recording_finished_signal.connect(
            self.start_post_processing)
        self.recorder_thread.start()
        self.is_recording = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.meeting_name_edit.setReadOnly(True)
        self.project_name_edit.setReadOnly(True)

    def stop_meeting(self):
        if not self.is_recording or not self.recorder_thread: return
        self.update_status("Stopping recording...");
        self.stop_button.setEnabled(False);
        self.recorder_thread.stop()

    def reset_processing_state(self):
        self.pending_chunk_files = []
        self.chunk_transcripts = {}
        self.transcriptions_done = 0
        self.total_chunks = 0
        self.full_meeting_transcript = ""
        self.final_summary = ""
        self.final_notes_json_string = ""
        self.final_transcript_path = ""
        self.final_summary_path = ""
        # self.final_mentor_path = "" # <<< REMOVED
        self.final_notes_path = ""

    def handle_chunk_transcription_result(self, transcript_text, chunk_path, success=True):
        chunk_filename = os.path.basename(chunk_path)
        self.update_status(f"Received result for {chunk_filename} (Success: {success})")
        try:
            index_str = chunk_filename.split('_')[-1].split('.')[0]
            chunk_index = int(index_str) - 1
        except (IndexError, ValueError) as e:
            print(f"ERROR: Could not parse chunk index from filename: {chunk_filename}. Error: {e}")
            self.transcriptions_done += 1
            self.check_all_transcriptions_done()
            return
        self.chunk_transcripts[chunk_index] = transcript_text
        self.transcriptions_done += 1
        try:
            if os.path.exists(chunk_path):
                os.remove(chunk_path)
        except OSError as e:
            print(f"Warning: Could not delete audio chunk {chunk_path}: {e}")
        self.check_all_transcriptions_done()

    def handle_chunk_transcription_error(self, error_message, chunk_path):
        chunk_filename = os.path.basename(chunk_path)
        self.display_error(f"Transcription error for {chunk_filename}: {error_message}")
        error_text = f"[ERROR: Transcription failed for {chunk_filename} - {error_message}]"
        self.handle_chunk_transcription_result(error_text, chunk_path, success=False)

    def check_all_transcriptions_done(self):
        if self.transcriptions_done >= self.total_chunks:
            self.update_status("All transcription chunks processed. Aggregating...")
            QApplication.processEvents()
            self.aggregate_and_start_notes()

    def aggregate_and_start_notes(self):
        aggregated_parts = [];
        missing_chunks = []
        for i in range(self.total_chunks):
            if i in self.chunk_transcripts:
                aggregated_parts.append(self.chunk_transcripts[i])
            else:
                chunk_file_name_placeholder = f"{self.current_meeting_id}_chunk_{i + 1}.wav"
                print(
                    f"Warning: Transcript for chunk index {i} (expected file ~{chunk_file_name_placeholder}) was missing during aggregation.")
                missing_chunks.append(i + 1)
                aggregated_parts.append(f"[ERROR: Transcript missing for chunk {i + 1}]")
        if missing_chunks:
            self.update_status(f"Warning: Missing transcripts for chunks: {missing_chunks}")
        self.full_meeting_transcript = " ".join(aggregated_parts).strip()
        self.final_transcript_path = os.path.join(TRANSCRIPTS_FOLDER, f"{self.current_meeting_id}.txt")
        try:
            with open(self.final_transcript_path, 'w', encoding='utf-8') as f:
                f.write(self.full_meeting_transcript)
            self.update_status(f"Full transcript saved: {self.final_transcript_path}")
        except IOError as e:
            self.display_error(f"Error saving final transcript: {e}")
            self.finalize_meeting_processing(success=False)
            return
        is_transcript_valid = bool(self.full_meeting_transcript) and \
                              not all("[ERROR:" in part for part in aggregated_parts if isinstance(part, str))
        if not is_transcript_valid:
            self.update_status(
                "Transcript contains errors or is empty. Skipping JSON extraction and summary.")
            self.final_notes_path = ""
            self.final_summary_path = ""
            # self.final_mentor_path = "" # <<< REMOVED
            self.finalize_meeting_processing(success=True)
            return
        self.update_status("Starting JSON note extraction...");
        QApplication.processEvents()
        worker = JsonExtractionWorker(self.full_meeting_transcript, self.api_key)
        worker.signals.json_notes_result.connect(self.handle_final_notes)
        worker.signals.error.connect(self.handle_final_notes_error)
        worker.signals.finished.connect(
            lambda: print("DEBUG: JsonExtractionWorker finished signal received."))
        self.threadpool.start(worker)

    def handle_final_notes(self, json_string):
        self.update_status("JSON note extraction complete.");
        self.final_notes_json_string = json_string;
        self.final_notes_path = f"{NOTES_FOLDER}/{self.current_meeting_id}_notes.json"
        try:
            try:
                parsed = json.loads(json_string); pretty_json = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pretty_json = json_string; self.display_error(
                    "Warning: Failed to parse extracted notes as JSON, saved raw output.")
            with open(self.final_notes_path, 'w', encoding='utf-8') as f:
                f.write(pretty_json)
            self.update_status(f"JSON notes saved: {self.final_notes_path}")
        except IOError as e:
            self.display_error(f"Error saving JSON notes file: {e}"); self.final_notes_path = ""
        self.update_status("Starting summarization...");
        QApplication.processEvents()
        worker = SummarizationWorker(self.full_meeting_transcript, self.api_key)
        worker.signals.summarization_result.connect(self.handle_final_summary)
        worker.signals.error.connect(self.handle_final_summary_error)
        worker.signals.finished.connect(
            lambda: print("DEBUG: SummarizationWorker finished signal received."))
        self.threadpool.start(worker)

    def handle_final_notes_error(self, error_message):
        self.display_error(f"JSON note extraction failed: {error_message}");
        self.final_notes_json_string = "";
        self.final_notes_path = ""
        self.update_status("JSON extraction failed. Starting summarization...");
        QApplication.processEvents()
        worker = SummarizationWorker(self.full_meeting_transcript, self.api_key)
        worker.signals.summarization_result.connect(self.handle_final_summary)
        worker.signals.error.connect(self.handle_final_summary_error)
        worker.signals.finished.connect(
            lambda: print("DEBUG: SummarizationWorker (after notes error) finished signal received."))
        self.threadpool.start(worker)

    def handle_final_summary(self, summary_text):
        self.update_status("Summarization complete.");
        self.final_summary = summary_text
        self.final_summary_path = f"{SUMMARIES_FOLDER}/{self.current_meeting_id}_summary.md"
        try:
            with open(self.final_summary_path, 'w', encoding='utf-8') as f:
                f.write(self.final_summary)
            self.update_status(f"Summary saved: {self.final_summary_path}")
        except IOError as e:
            self.display_error(f"Error saving summary file: {e}");
            self.final_summary_path = ""

        # --- Mentor Feedback Worker Call Removed ---
        # Directly finalize processing
        self.finalize_meeting_processing(success=True)

    def handle_final_summary_error(self, error_message):
        self.display_error(f"Summarization failed: {error_message}");
        self.final_summary = "";
        self.final_summary_path = ""

        # --- Mentor Feedback Worker Call Removed ---
        # Directly finalize processing
        self.finalize_meeting_processing(success=True)

    # --- handle_mentor_feedback and handle_mentor_feedback_error REMOVED ---

    def finalize_meeting_processing(self, success=True):
        self.update_status("Finalizing meeting processing...")
        QApplication.processEvents()
        transcript_path_valid = bool(self.final_transcript_path and os.path.exists(self.final_transcript_path))
        meeting_id_valid = bool(self.current_meeting_id)

        if success and transcript_path_valid and meeting_id_valid:
            updated_meeting_data = MeetingData(
                self.current_meeting_id,
                self.current_meeting_name,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                self.current_project_name,
                self.final_summary_path,
                self.final_transcript_path,
                # self.final_mentor_path, # <<< REMOVED
                self.full_audio_file_path,
                self.final_notes_path
            )
            existing_meeting_index = -1
            for idx, meeting in enumerate(self.history.meetings):
                if meeting.meeting_id == self.current_meeting_id:
                    existing_meeting_index = idx
                    break
            if existing_meeting_index != -1:
                self.history.meetings[existing_meeting_index] = updated_meeting_data
                self.update_status(f"Meeting '{self.current_meeting_name}' processing results updated.")
            else:
                self.history.add_meeting(updated_meeting_data)
                self.update_status(f"Meeting '{self.current_meeting_name}' processed and saved.")
            self.history.save_history()
            self.load_history_list()
        elif not success:
            self.update_status(f"Meeting '{self.current_meeting_name}' processing FAILED. Check logs.")
        else:
            self.update_status(
                f"Meeting '{self.current_meeting_name}' processed, but history not updated (transcript/ID invalid).")

        self.is_recording = False
        if self.recorder_thread and self.recorder_thread.isRunning():
            print("Warning: Recorder thread still running during finalize. Attempting to stop again.")
            self.recorder_thread.quit()
            self.recorder_thread.wait(1000)
        self.recorder_thread = None
        self.processing_active = False
        self.start_button.setEnabled(self.api_key_valid)
        self.stop_button.setEnabled(False)
        self.meeting_name_edit.setReadOnly(False)
        self.project_name_edit.setReadOnly(False)
        if self.current_selected_meeting_id:
            self.delete_button.setEnabled(True)
            meeting = next((m for m in self.history.meetings if m.meeting_id == self.current_selected_meeting_id), None)
            can_retry_now = bool(meeting and meeting.full_audio_path and os.path.exists(meeting.full_audio_path))
            self.retry_button.setEnabled(can_retry_now)
        else:
            self.delete_button.setEnabled(False)
            self.retry_button.setEnabled(False)
        print("DEBUG: Finalize_meeting_processing complete.")

    def closeEvent(self, event):
        self.update_status("Attempting to close application...")
        QApplication.processEvents()
        if self.is_recording:
            reply = QMessageBox.question(self, 'Exit Confirmation',
                                         'A meeting is currently recording. Stop recording and exit? (Current meeting processing will be cancelled)',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                if self.recorder_thread:
                    self.recorder_thread.stop()
                self.processing_active = False
                self.is_recording = False
                self.update_status("Recording stopped. Shutting down threads...")
                QApplication.processEvents()
                self.threadpool.clear()
                if not self.threadpool.waitForDone(2000):
                    print("Warning: Not all threads finished cleanly on exit.")
                event.accept()
            else:
                event.ignore()
                self.update_status("Exit cancelled.")
                return
        elif self.processing_active:
            reply = QMessageBox.question(self, 'Exit Confirmation',
                                         'Meeting post-processing is active. Exit now? (Processing will be incomplete)',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.processing_active = False
                self.update_status("Processing stopped. Shutting down threads...")
                QApplication.processEvents()
                self.threadpool.clear()
                if not self.threadpool.waitForDone(2000):
                    print("Warning: Not all threads finished cleanly on exit.")
                event.accept()
            else:
                event.ignore()
                self.update_status("Exit cancelled.")
                return
        else:
            self.update_status("Shutting down threads...")
            QApplication.processEvents()
            if not self.threadpool.waitForDone(1000):
                print("Warning: Minor thread activity on close, but no major processing was active.")
            event.accept()

    def _get_project_wiki_path(self, project_name_or_id):
        if not project_name_or_id:
            return None
        filename_project_name = "".join(
            c if c.isalnum() or c in [' ', '-'] else '_' for c in project_name_or_id).strip().replace(' ', '_')
        if not filename_project_name:
            filename_project_name = "default_project"
        os.makedirs(PROJECT_WIKIS_FOLDER, exist_ok=True)
        return os.path.join(PROJECT_WIKIS_FOLDER, f"{filename_project_name}_wiki.md")

    def _read_wiki_section(self, wiki_file_path, section_title):
        if not wiki_file_path or not os.path.exists(wiki_file_path):
            print(f"Wiki file not found (or path is None) for reading section: {wiki_file_path}")
            return None
        try:
            with open(wiki_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            self.display_error(f"Error reading wiki file {wiki_file_path}: {e}")
            return None
        section_content_lines = []
        in_section = False
        import re
        target_header_pattern = re.compile(r"^\s*#+\s*" + re.escape(section_title) + r"\s*$", re.IGNORECASE)
        next_major_header_pattern = re.compile(r"^\s*##\s+.*")
        for i, line in enumerate(lines):
            if not in_section and target_header_pattern.match(line):
                in_section = True
                continue
            if in_section:
                is_next_major_header = next_major_header_pattern.match(line)
                if is_next_major_header and not target_header_pattern.match(line):
                    break
                section_content_lines.append(line)
        if not in_section:
            print(f"Section '{section_title}' not found in {wiki_file_path}. Assuming empty content.")
            return ""
        return "".join(section_content_lines).strip()

    def _replace_wiki_section(self, wiki_file_path, section_title, new_section_content):
        if new_section_content and not new_section_content.endswith('\n'):
            new_section_content += '\n'
        if not new_section_content:
            new_section_content = '\n'
        import re
        target_header_pattern_search = re.compile(r"^\s*(#+)\s*" + re.escape(section_title) + r"\s*$", re.IGNORECASE)
        header_level_to_write = "##"
        lines = []
        file_existed = os.path.exists(wiki_file_path)
        if file_existed:
            try:
                with open(wiki_file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception as e:
                self.display_error(f"Error reading wiki file {wiki_file_path} for replacement: {e}")
                return False
        if file_existed:
            for line_check in lines:
                match = target_header_pattern_search.match(line_check)
                if match:
                    header_level_to_write = match.group(1)
                    break
        new_full_section_text = f"{header_level_to_write} {section_title}\n{new_section_content}"
        if not file_existed:
            try:
                with open(wiki_file_path, 'w', encoding='utf-8') as f:
                    f.write(new_full_section_text)
                self.update_status(f"Created new wiki file with section: {os.path.basename(wiki_file_path)}")
                return True
            except Exception as e:
                self.display_error(f"Error creating new wiki file {os.path.basename(wiki_file_path)}: {e}")
                return False
        output_lines = []
        in_section_to_replace = False
        section_replaced_or_found = False
        any_header_pattern = re.compile(r"^\s*#+\s+.*")
        i = 0
        while i < len(lines):
            line = lines[i]
            if target_header_pattern_search.match(line):
                if not section_replaced_or_found:
                    output_lines.append(new_full_section_text)
                    section_replaced_or_found = True
                    in_section_to_replace = True
                i += 1
                continue
            if in_section_to_replace:
                if any_header_pattern.match(line):
                    in_section_to_replace = False
                    output_lines.append(line)
            else:
                output_lines.append(line)
            i += 1
        if not section_replaced_or_found:
            if output_lines and output_lines[-1].strip() != "":
                if not output_lines[-1].endswith('\n'): output_lines[-1] += '\n'
                output_lines.append('\n')
            output_lines.append(new_full_section_text)
            self.update_status(f"Section '{section_title}' appended to wiki.")
        try:
            with open(wiki_file_path, 'w', encoding='utf-8') as f:
                f.writelines(output_lines)
            self.update_status(f"Wiki section '{section_title}' updated in {os.path.basename(wiki_file_path)}")
            return True
        except Exception as e:
            self.display_error(f"Error writing updated wiki file {os.path.basename(wiki_file_path)}: {e}")
            return False

    def _update_daily_log_section(self, wiki_file_path, new_log_entry_text, entry_date_str=None):
        if not new_log_entry_text.strip() or new_log_entry_text.strip().lower() == "no new log entries from this meeting.":
            self.update_status("Daily log update skipped: New entry text is empty or indicates no new entries.")
            return True
        if entry_date_str is None:
            entry_date_str = datetime.now().strftime("%Y-%m-%d")
        daily_log_main_header = "## Daily Log"
        date_subheader = f"### {entry_date_str}"
        lines_of_new_entry = new_log_entry_text.strip().split('\n')
        formatted_new_entry_lines = []
        for line in lines_of_new_entry:
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith(("* ", "- ", "### ")):
                formatted_new_entry_lines.append(f"- {stripped_line}")
            elif stripped_line:
                formatted_new_entry_lines.append(line)
        new_log_entry_block = "\n".join(formatted_new_entry_lines)
        if not new_log_entry_block.endswith('\n'):
            new_log_entry_block += '\n'
        lines = []
        file_existed = os.path.exists(wiki_file_path)
        if file_existed:
            try:
                with open(wiki_file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception as e:
                self.display_error(f"Error reading wiki file {os.path.basename(wiki_file_path)} for daily log: {e}")
                return False
        output_lines = []
        daily_log_section_found = False
        import re
        daily_log_header_pattern = re.compile(r"^\s*##\s*Daily Log\s*$", re.IGNORECASE)
        date_subheader_pattern = re.compile(r"^\s*###\s*" + re.escape(entry_date_str) + r"\s*$", re.IGNORECASE)
        any_h2_header_pattern = re.compile(r"^\s*##\s+.*")
        any_h3_header_pattern = re.compile(r"^\s*###\s+.*")
        daily_log_start_index = -1
        today_date_header_index = -1
        first_h3_after_daily_log_index = -1
        for i, line in enumerate(lines):
            if daily_log_header_pattern.match(line):
                daily_log_section_found = True
                daily_log_start_index = i
                for j in range(i + 1, len(lines)):
                    line_j = lines[j]
                    if any_h2_header_pattern.match(line_j):
                        break
                    if date_subheader_pattern.match(line_j):
                        today_date_header_index = j
                        break
                    if first_h3_after_daily_log_index == -1 and any_h3_header_pattern.match(line_j):
                        first_h3_after_daily_log_index = j
                break
        if not daily_log_section_found:
            output_lines.extend(lines)
            if output_lines and output_lines[-1].strip() != "":
                if not output_lines[-1].endswith('\n'): output_lines[-1] += '\n'
                output_lines.append('\n')
            output_lines.append(f"{daily_log_main_header}\n")
            output_lines.append(f"{date_subheader}\n")
            output_lines.append(new_log_entry_block)
        else:
            if today_date_header_index != -1:
                output_lines.extend(lines[:today_date_header_index + 1])
                output_lines.append(new_log_entry_block)
                for k in range(today_date_header_index + 1, len(lines)):
                    line_k = lines[k]
                    if any_h3_header_pattern.match(line_k) or any_h2_header_pattern.match(line_k):
                        output_lines.extend(lines[k:])
                        break
                    output_lines.append(line_k)
                else:
                    pass
            else:
                insert_at = daily_log_start_index + 1
                if first_h3_after_daily_log_index != -1:
                    insert_at = first_h3_after_daily_log_index
                output_lines.extend(lines[:insert_at])
                output_lines.append(f"{date_subheader}\n")
                output_lines.append(new_log_entry_block)
                if insert_at < len(lines) and lines[insert_at].strip() != "" and not new_log_entry_block.endswith(
                        "\n\n"):
                    if not new_log_entry_block.endswith("\n"): output_lines[
                        -1] += "\n"
                    output_lines.append("\n")
                output_lines.extend(lines[insert_at:])
        try:
            with open(wiki_file_path, 'w', encoding='utf-8') as f:
                f.writelines(output_lines)
            self.update_status(f"Daily log updated in {os.path.basename(wiki_file_path)} for {entry_date_str}")
            return True
        except Exception as e:
            self.display_error(f"Error writing updated wiki file {os.path.basename(wiki_file_path)}: {e}")
            return False


# --- Main Execution Block ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Meeting Summarizer & Coach v2")
    window = MeetingTranscriberApp()
    window.show()
    sys.exit(app.exec_())



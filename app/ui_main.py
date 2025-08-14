import sys
from datetime import datetime
from typing import Optional, List, Tuple
from enum import Enum

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QToolBar,
    QAction,
    QMenuBar,
    QMenu,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QInputDialog,
)
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QTextDocument, QTextCharFormat, QColor, QMovie, QTransform
from pathlib import Path
import markdown2
import re

from loguru import logger

from services.config import load_config
from services.logging_setup import setup_logging
from services.storage import StoragePaths, ensure_directories
from services.recorder import PyAudioRecorder, IRecorder
from services import get_transcription_backend, TranscriptionUnavailable
from services.suggest import SuggestionGenerator, SuggestionUnavailable, MeetingSuggestions
from services.wiki import ensure_project_wiki, upsert_meeting_section
from services.journal import ensure_journal_date_section, append_journal_entry
from services.project_manager import project_manager
from services.history import MeetingHistory, MeetingRecord
from services.weekly import generate_weekly_from_journal
from services.meeting_index import meeting_index_builder
from services.query_parser import query_parser, build_search_query, filter_results_by_context
import threading
import time


class AppStatus(Enum):
    """Application status states with associated colors and messages."""
    READY = ("Ready", "#666666", False)  # Gray, no spinning
    RECORDING = ("Recording...", "#DC3545", True)  # Red, spinning
    PROCESSING_TRANSCRIPT = ("Processing transcript...", "#007BFF", True)  # Blue, spinning
    GENERATING_SUMMARY = ("Generating summary...", "#007BFF", True)  # Blue, spinning
    UPDATING_WIKI = ("Updating wiki...", "#007BFF", True)  # Blue, spinning
    SAVED = ("Saved", "#28A745", False)  # Green, no spinning
    ERROR = ("Error", "#DC3545", False)  # Red, no spinning

class SpinningLabel(QLabel):
    """A QLabel that can display a spinning animation."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._angle = 0
        self._timer = QTimer()
        self._timer.timeout.connect(self._rotate)
        self._spinning = False
        self._current_spinner = "⠋"
        self._base_text = ""
        
    def start_spinning(self):
        """Start the spinning animation."""
        if not self._spinning:
            self._spinning = True
            self._timer.start(50)  # Update every 50ms for smooth animation
            
    def stop_spinning(self):
        """Stop the spinning animation."""
        if self._spinning:
            self._spinning = False
            self._timer.stop()
            self._angle = 0
            self.setStyleSheet(self.styleSheet())  # Reset any transform
            
    def _rotate(self):
        """Update the rotation angle."""
        self._angle = (self._angle + 30) % 360
        # Simple text-based spinning using Unicode characters
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spinner_index = (self._angle // 30) % len(spinner_chars)
        self._current_spinner = spinner_chars[spinner_index]
        self._update_text()
        
    def _update_text(self):
        """Update text with current spinner character."""
        # Always use the latest base text instead of whatever is currently rendered
        if self._spinning:
            super().setText(f"{self._current_spinner} {self._base_text}")
        
    def setText(self, text):
        """Override setText to add spinner icon when spinning."""
        self._base_text = text
        if self._spinning:
            # Update immediately so label reflects new base text
            self._update_text()
        else:
            super().setText(text)


class MainWindow(QMainWindow):
    # Signals to marshal updates back to the UI thread safely from workers
    ui_set_status = pyqtSignal(object, object)  # (AppStatus, auto_reset_seconds or None)
    ui_set_transcript = pyqtSignal(str)
    ui_set_suggestions = pyqtSignal(object)  # MeetingSuggestions
    def __init__(self) -> None:
        super().__init__()

        # Config and logging
        self.config = load_config()
        setup_logging(self.config.logs_dir)
        logger.info("App starting up")

        # Ensure folders
        ensure_directories(
            StoragePaths(
                base_dir=self.config.base_dir,
                data_base=self.config.data_base,
                project_wikis_dir=self.config.project_wikis_dir,
                recordings_dir=self.config.recordings_dir,
                transcripts_dir=self.config.transcripts_dir,
                summaries_dir=self.config.summaries_dir,
                weekly_summaries_dir=self.config.weekly_summaries_dir,
                json_notes_dir=self.config.json_notes_dir,
                logs_dir=self.config.logs_dir,
            )
        )

        self.setWindowTitle("AibaTS Desktop Tool")
        self.setGeometry(150, 150, 1000, 700)

        # Create main widget with tab container
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Create main recording tab
        self.main_tab = QWidget()
        main_tab_layout = QVBoxLayout(self.main_tab)
        self.tab_widget.addTab(self.main_tab, "Recording")
        
        # Create wiki tab
        self.wiki_tab = QWidget()
        self.tab_widget.addTab(self.wiki_tab, "Wiki")
        self._setup_wiki_tab()

        # Create meetings tab (added after project combo is ready)
        self.meetings_tab = QWidget()
        self.tab_widget.addTab(self.meetings_tab, "Meetings")
        self._setup_meetings_tab()
        # Now that project_combo exists, load the meetings list
        self._load_meetings_list()

        # Track last valid project selection to handle "New Project…" cancel/revert
        self._last_valid_project_name: Optional[str] = None

        # --- Toolbar with actions ---
        self.toolbar = QToolBar("Main", self)
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        # Create QAction attributes BEFORE wiring
        self.record_toggle_btn = QAction("▶ Start Recording", self)
        self.record_toggle_btn.setCheckable(True)
        # Remove old manual actions; replace with weekly summary on toolbar
        self.weekly_toolbar_btn = QAction("Generate Weekly Summary", self)

        # Add to toolbar in order with separators
        self.toolbar.addAction(self.record_toggle_btn)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.weekly_toolbar_btn)

        # Connect signals to handlers
        self.record_toggle_btn.triggered.connect(self._on_record_toggle_clicked)
        self.weekly_toolbar_btn.triggered.connect(self._on_weekly_clicked)
        
        # Add setting for auto-processing (can be disabled if causing crashes)
        self._auto_process = True

        # Initial button states will be set by _set_status(AppStatus.READY)

        # Top: Project picker and meeting name
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self._load_projects()
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        # Delete project button
        self.delete_project_btn = QPushButton("Delete Project…")
        self.delete_project_btn.setToolTip("Delete the selected project and its files")
        self.delete_project_btn.clicked.connect(self._on_delete_project)
        row1.addWidget(self.project_combo, 1)
        row1.addWidget(self.delete_project_btn)

        row1.addWidget(QLabel("Meeting:"))
        self.meeting_edit = QLineEdit()
        self.meeting_edit.setPlaceholderText("Enter meeting name")
        row1.addWidget(self.meeting_edit, 2)
        main_tab_layout.addLayout(row1)
        # Initialize last valid project to the first non "New Project…" item, if any
        for i in range(self.project_combo.count()):
            text_i = self.project_combo.itemText(i).strip()
            if text_i and text_i != "New Project…":
                self._last_valid_project_name = text_i
                break



        # Status with spinning animation support
        self.status_label = SpinningLabel()
        self.status_label.setMinimumHeight(30)
        self.status_label.setStyleSheet("QLabel { padding: 5px; border-radius: 3px; font-weight: bold; }")
        main_tab_layout.addWidget(self.status_label)

        # Timer for auto-reset status
        self._status_reset_timer = QTimer()
        self._status_reset_timer.setSingleShot(True)
        self._status_reset_timer.timeout.connect(lambda: self._set_status(AppStatus.READY))

        # Connect UI-thread signals
        self.ui_set_status.connect(lambda status, secs: self._set_status(status, secs))
        self.ui_set_transcript.connect(self._update_transcript_ui)
        self.ui_set_suggestions.connect(self._update_suggestions_ui)



        # Key status
        if not self.config.openai_api_key:
            self._warn_missing_key()

        # Transcript display
        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        main_tab_layout.addWidget(QLabel("Transcript:"))
        main_tab_layout.addWidget(self.transcript_view)

        # Suggestions display only (actions live in toolbar)

        self.suggestions_view = QTextEdit()
        self.suggestions_view.setReadOnly(True)
        main_tab_layout.addWidget(QLabel("Suggestions (recap/decisions/actions/risks/open questions):"))
        main_tab_layout.addWidget(self.suggestions_view)

        # Weekly Summary moved to toolbar; bottom section removed

        self.setCentralWidget(main_widget)
        self._recorder: IRecorder = PyAudioRecorder()
        self._current_meeting_id: Optional[str] = None
        self._last_audio_path: Optional[str] = None
        self._transcribe_thread: Optional[threading.Thread] = None
        self._history = MeetingHistory(self.config.data_base / "meeting_history.json")
        self._last_suggestions: Optional[MeetingSuggestions] = None
        self._transcribing: bool = False

        # Set initial status
        self._set_status(AppStatus.READY)

    def _setup_wiki_tab(self) -> None:
        """Setup the Wiki tab with markdown viewer and editor."""
        wiki_layout = QVBoxLayout(self.wiki_tab)
        
        # Search bar at the top
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search wiki content...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self.search_input, 1)
        
        # Search navigation controls
        self.search_count_label = QLabel("0/0")
        search_layout.addWidget(self.search_count_label)
        
        self.prev_match_btn = QPushButton("Previous")
        self.prev_match_btn.clicked.connect(self._on_previous_match)
        self.prev_match_btn.setEnabled(False)
        search_layout.addWidget(self.prev_match_btn)
        
        self.next_match_btn = QPushButton("Next")
        self.next_match_btn.clicked.connect(self._on_next_match)
        self.next_match_btn.setEnabled(False)
        search_layout.addWidget(self.next_match_btn)
        
        wiki_layout.addLayout(search_layout)
        
        # Quick Query section
        query_layout = QVBoxLayout()
        query_header = QLabel("Quick Query - Ask natural language questions about meetings:")
        query_header.setStyleSheet("font-weight: bold; color: #2E7D32; margin-top: 10px;")
        query_layout.addWidget(query_header)
        
        query_input_layout = QHBoxLayout()
        
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText('e.g. "When did we decide to use SQL?" or "What did Sarah discuss about authentication?"')
        self.query_input.returnPressed.connect(self._on_quick_query)
        query_input_layout.addWidget(self.query_input, 1)
        
        self.query_btn = QPushButton("Ask")
        self.query_btn.clicked.connect(self._on_quick_query)
        query_input_layout.addWidget(self.query_btn)
        
        self.clear_query_btn = QPushButton("Clear")
        self.clear_query_btn.setToolTip("Clear results and reset view")
        self.clear_query_btn.clicked.connect(self._on_clear_query)
        self.clear_query_btn.setVisible(False)
        query_input_layout.addWidget(self.clear_query_btn)
        
        query_layout.addLayout(query_input_layout)
        
        # Query results area
        self.query_results = QTextBrowser()
        self.query_results.setMaximumHeight(200)
        self.query_results.setVisible(False)
        query_layout.addWidget(self.query_results)
        
        wiki_layout.addLayout(query_layout)
        
        # Top controls
        controls_layout = QHBoxLayout()
        
        # Edit mode toggle
        self.edit_mode_cb = QCheckBox("Edit Mode")
        self.edit_mode_cb.stateChanged.connect(self._on_edit_mode_toggled)
        controls_layout.addWidget(self.edit_mode_cb)
        
        controls_layout.addStretch()
        
        # Refresh button
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._on_wiki_refresh)
        controls_layout.addWidget(self.refresh_btn)
        
        # Save button (initially hidden)
        self.save_wiki_btn = QPushButton("Save Changes")
        self.save_wiki_btn.clicked.connect(self._on_wiki_save)
        self.save_wiki_btn.setVisible(False)
        controls_layout.addWidget(self.save_wiki_btn)
        
        wiki_layout.addLayout(controls_layout)
        
        # Wiki content area (stacked: viewer and editor)
        self.wiki_viewer = QTextBrowser()
        self.wiki_viewer.setOpenExternalLinks(True)
        wiki_layout.addWidget(self.wiki_viewer)
        
        self.wiki_editor = QTextEdit()
        self.wiki_editor.setVisible(False)
        wiki_layout.addWidget(self.wiki_editor)
        
        # Tab change event to load wiki when tab is activated
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # Search functionality setup
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._perform_search)
        self.search_matches = []
        self.current_match_index = -1
        self.current_search_term = ""
        
        # Load initial content
        self._load_wiki_content()

    def _setup_meetings_tab(self) -> None:
        """Setup the Meetings tab with a list and transcript viewer and search."""
        layout = QVBoxLayout(self.meetings_tab)

        # Search bar for meetings/transcripts
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Search:"))
        self.meetings_search_input = QLineEdit()
        self.meetings_search_input.setPlaceholderText("Search meetings or transcripts...")
        self.meetings_search_input.textChanged.connect(self._on_meetings_search)
        top_bar.addWidget(self.meetings_search_input, 1)
        layout.addLayout(top_bar)

        # Splitter: left list of meetings, right transcript viewer
        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # Left: meeting list
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        self.meetings_list = QListWidget()
        self.meetings_list.itemSelectionChanged.connect(self._on_meeting_selected)
        left_layout.addWidget(self.meetings_list)
        splitter.addWidget(left_container)

        # Right: transcript viewer
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        self.transcript_viewer = QTextBrowser()
        right_layout.addWidget(self.transcript_viewer)
        splitter.addWidget(right_container)

        # Initial list load is deferred until project selector exists

    def _load_meetings_list(self) -> None:
        """Load meetings from index for current project into the list."""
        # Guard: project combo may not be ready during early init
        if not hasattr(self, 'project_combo'):
            return
        self.meetings_list.clear()
        project = self._current_project_name()
        index = meeting_index_builder.build_project_index(project, force_rebuild=False)
        self._meetings_entries = index.meetings  # cache
        for entry in self._meetings_entries:
            item = QListWidgetItem(f"{entry.date} — {entry.meeting_name}")
            item.setData(Qt.UserRole, entry)
            self.meetings_list.addItem(item)

    def _on_meeting_selected(self) -> None:
        items = self.meetings_list.selectedItems()
        if not items:
            self.transcript_viewer.clear()
            return
        entry = items[0].data(Qt.UserRole)
        # Display transcript if available, else summary info
        if entry.full_transcript:
            self.transcript_viewer.setPlainText(entry.full_transcript)
        else:
            # Fallback content
            details = []
            if entry.decisions:
                details.append("Decisions:\n- " + "\n- ".join(entry.decisions))
            if entry.action_items:
                details.append("To Do:\n- " + "\n- ".join(entry.action_items))
            self.transcript_viewer.setPlainText("\n\n".join(details) or "No transcript available.")

    def _on_meetings_search(self, text: str) -> None:
        query = text.strip()
        self.meetings_list.clear()
        project = self._current_project_name()
        if not query:
            # reload full list
            self._load_meetings_list()
            return
        results = meeting_index_builder.search_index(project, query, max_results=200)
        for entry in results:
            item = QListWidgetItem(f"{entry.date} — {entry.meeting_name}")
            item.setData(Qt.UserRole, entry)
            self.meetings_list.addItem(item)

    def _set_status(self, status: AppStatus, auto_reset_seconds: Optional[int] = None) -> None:
        """Set the application status with appropriate styling and button states.
        
        Args:
            status: The status to set
            auto_reset_seconds: If provided, reset to READY after this many seconds
        """
        message, color, should_spin = status.value
        
        # Update status text and styling
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            f"QLabel {{ padding: 5px; border-radius: 3px; font-weight: bold; "
            f"background-color: {color}; color: white; }}"
        )
        
        # Handle spinning animation
        if should_spin:
            self.status_label.start_spinning()
        else:
            self.status_label.stop_spinning()
        
        # Update button states based on status
        if status == AppStatus.READY:
            self._set_button_states('ready')
        elif status == AppStatus.RECORDING:
            self._set_button_states('recording')
        elif status in [AppStatus.PROCESSING_TRANSCRIPT, AppStatus.GENERATING_SUMMARY, AppStatus.UPDATING_WIKI]:
            # While processing, disable all buttons but visually reset the toggle text to Start
            self._set_button_states('processing')
            self.record_toggle_btn.blockSignals(True)
            try:
                self.record_toggle_btn.setText("▶ Start Recording")
                self.record_toggle_btn.setChecked(False)
            finally:
                self.record_toggle_btn.blockSignals(False)
        elif status == AppStatus.ERROR:
            self._set_button_states('error')
        elif status == AppStatus.SAVED:
            self._set_button_states('ready')  # After save, return to ready state
        
        # Stop any existing timer
        self._status_reset_timer.stop()
        
        # Set auto-reset if requested
        if auto_reset_seconds:
            self._status_reset_timer.start(auto_reset_seconds * 1000)
        
        # Log status change
        logger.info(f"Status changed to: {message} (spinning: {should_spin})")
        logger.info(f"Button state will be set to: {status.name.lower()}")
        
        # Force UI update
        self.status_label.update()
        self.record_toggle_btn.parent().update() if self.record_toggle_btn.parent() else None

    def _update_status_safe(self, status: AppStatus, auto_reset_seconds: Optional[int] = None) -> None:
        """Thread-safe status update using QTimer.singleShot."""
        QTimer.singleShot(0, lambda: self._set_status(status, auto_reset_seconds))

    # --- Toolbar action wrappers ---
    def _on_record_toggle_clicked(self) -> None:
        """Handle the main record toggle button - implements the full workflow."""
        if self.record_toggle_btn.isChecked():
            # Start recording
            self._start_recording()
        else:
            # Stop recording and trigger automatic workflow
            self._stop_recording_and_process()

    def _set_button_states(self, state: str) -> None:
        """Set button states based on current application state.
        
        Args:
            state: One of 'ready', 'recording', 'processing', 'error'
        """
        # Block signals to prevent triggering actions during programmatic state changes
        self.record_toggle_btn.blockSignals(True)
        
        try:
            if state == 'ready':
                # All buttons enabled, record button shows "Start Recording"
                self.record_toggle_btn.setEnabled(True)
                self.record_toggle_btn.setText("▶ Start Recording")
                self.record_toggle_btn.setChecked(False)
                # No other toolbar actions to toggle now
                
            elif state == 'recording':
                # Only stop recording button enabled
                self.record_toggle_btn.setEnabled(True)
                self.record_toggle_btn.setText("⏹ Stop Recording")
                self.record_toggle_btn.setChecked(True)
                # No other toolbar actions to toggle now
                
            elif state == 'processing':
                # All buttons disabled during processing
                self.record_toggle_btn.setEnabled(False)
                # No other toolbar actions to toggle now
                
            elif state == 'error':
                # Reset to ready state after error
                self.record_toggle_btn.setEnabled(True)
                self.record_toggle_btn.setText("▶ Start Recording")
                self.record_toggle_btn.setChecked(False)
                # No other toolbar actions to toggle now
        finally:
            # Always re-enable signals
            self.record_toggle_btn.blockSignals(False)
        
        logger.info(f"Button states set to: {state}")
        if state == 'ready':
            logger.info(f"Record button should now show: ▶ Start Recording (checked: False)")
        elif state == 'recording':
            logger.info(f"Record button should now show: ⏹ Stop Recording (checked: True)")

    def _set_busy(self, is_busy: bool) -> None:
        """Legacy method - use _set_button_states instead."""
        if is_busy:
            self._set_button_states('processing')
        else:
            self._set_button_states('ready')

    def _load_projects(self) -> None:
        """Load projects from both old structure (project_wikis/) and new structure (projects/)."""
        projects = set()
        
        # Load from old structure: project_wikis/*_wiki.md
        wiki_files = sorted(self.config.project_wikis_dir.glob("*_wiki.md"))
        for wf in wiki_files:
            name = wf.name.removesuffix("_wiki.md")
            projects.add(name)
        
        # Load from new structure: projects/*/wiki.md
        new_projects = project_manager.list_projects()
        projects.update(new_projects)
        
        # Add all projects to combo box
        for project in sorted(projects):
            self.project_combo.addItem(project)
        
        self.project_combo.addItem("New Project…")

    def _on_project_changed(self, project_name: str) -> None:
        """Handle project selection change - ensure project structure exists."""
        if not project_name:
            return

        if project_name == "New Project…":
            # Prompt user for a new project name
            name, ok = QInputDialog.getText(self, "New Project", "Enter new project name:")
            if not ok:
                # Revert to last valid selection if available
                if self._last_valid_project_name:
                    self.project_combo.blockSignals(True)
                    self.project_combo.setCurrentText(self._last_valid_project_name)
                    self.project_combo.blockSignals(False)
                return
            name = name.strip()
            if not name:
                QMessageBox.information(self, "New Project", "Project name cannot be empty.")
                if self._last_valid_project_name:
                    self.project_combo.blockSignals(True)
                    self.project_combo.setCurrentText(self._last_valid_project_name)
                    self.project_combo.blockSignals(False)
                return

            try:
                # Create or open existing project
                project_dir = project_manager.ensure_project_structure(name)
                safe_name = project_dir.name

                # Insert into combo if not present (before the 'New Project…' item)
                existing_texts = {self.project_combo.itemText(i) for i in range(self.project_combo.count())}
                if safe_name not in existing_texts:
                    new_index = max(0, self.project_combo.count() - 1)
                    self.project_combo.insertItem(new_index, safe_name)

                # Select the new project
                self.project_combo.blockSignals(True)
                self.project_combo.setCurrentText(safe_name)
                self.project_combo.blockSignals(False)

                # Update last valid selection and refresh dependent views
                self._last_valid_project_name = safe_name
                self._load_meetings_list()
                if self.tab_widget.currentIndex() == 1:  # Wiki tab active
                    self._load_wiki_content()

                QMessageBox.information(self, "Project Created", f"Project initialized at: {project_dir}")
            except Exception as e:
                logger.error(f"Failed to create new project: {e}")
                QMessageBox.warning(self, "Project Error", f"Failed to create project: {e}")
                # Revert selection on failure
                if self._last_valid_project_name:
                    self.project_combo.blockSignals(True)
                    self.project_combo.setCurrentText(self._last_valid_project_name)
                    self.project_combo.blockSignals(False)
            return
        
        try:
            # Create the project structure if it doesn't exist
            project_dir = project_manager.ensure_project_structure(project_name)
            logger.debug(f"Project structure ensured for: {project_name} at {project_dir}")
            self._last_valid_project_name = project_name
        except Exception as e:
            logger.error(f"Failed to ensure project structure for {project_name}: {e}")
            QMessageBox.warning(self, "Project Error", f"Failed to create project structure: {e}")

    def _on_delete_project(self) -> None:
        """Handle deletion of the currently selected project with confirmation."""
        project_name = self._current_project_name()
        if not project_name or project_name == "New Project…":
            QMessageBox.information(self, "Delete Project", "Select a valid project to delete.")
            return
        # Confirm typing the project name
        confirm_text, ok = QInputDialog.getText(
            self, "Delete Project", f"Type the project name to confirm deletion of '{project_name}':")
        if not ok:
            return
        confirm_text = confirm_text.strip()
        if confirm_text != project_name:
            QMessageBox.warning(self, "Delete Project", "Project name did not match. Deletion cancelled.")
            return
        # Final yes/no confirmation
        ret = QMessageBox.question(
            self,
            "Delete Project",
            f"Are you sure you want to permanently delete project '{project_name}' and all its files?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            project_manager.delete_project(project_name)
            # Remove from combo, keep New Project… at end
            idx = self.project_combo.findText(project_name)
            if idx >= 0:
                self.project_combo.removeItem(idx)
            # Set selection to first remaining project (if any), else default to New Project…
            next_selection = None
            for i in range(self.project_combo.count()):
                txt = self.project_combo.itemText(i)
                if txt and txt != "New Project…":
                    next_selection = txt
                    break
            self.project_combo.blockSignals(True)
            if next_selection:
                self.project_combo.setCurrentText(next_selection)
            else:
                self.project_combo.setCurrentText("New Project…")
            self.project_combo.blockSignals(False)
            self._last_valid_project_name = next_selection
            # Refresh UI views
            self._load_meetings_list()
            if self.tab_widget.currentIndex() == 1:  # Wiki
                self._load_wiki_content()
            QMessageBox.information(self, "Delete Project", f"Project '{project_name}' deleted.")
        except Exception as e:
            logger.error(f"Failed to delete project '{project_name}': {e}")
            QMessageBox.warning(self, "Delete Project", f"Failed to delete: {e}")

    def _warn_missing_key(self) -> None:
        msg = "OPENAI_API_KEY not found. Cloud transcription/suggestions disabled until set."
        logger.warning(msg)
        # Keep this as a temporary status, then return to ready
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("QLabel { padding: 5px; border-radius: 3px; font-weight: bold; background-color: #FFC107; color: black; }")
        QTimer.singleShot(5000, lambda: self._set_status(AppStatus.READY))

    def _start_recording(self) -> None:
        """Start recording and update UI accordingly."""
        if self._recorder.is_recording:
            logger.warning("Recording already in progress")
            return

        project = self._current_project_name()
        meeting = self.meeting_edit.text().strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d_%H%M')}"
        self._set_status(AppStatus.RECORDING)
        logger.info(f"Start recording | project={project} meeting={meeting}")
        
        # Deterministic meeting id based on time
        self._current_meeting_id = f"meeting_{int(datetime.now().timestamp())}"
        output_path = self.config.recordings_dir / f"{self._current_meeting_id}_full.wav"
        ok = self._recorder.start(output_path)
        
        if ok:
            # Button states will be handled by _set_status(AppStatus.RECORDING)
            self._last_suggestions = None
            
            # Clear previous data
            self.transcript_view.clear()
            self.suggestions_view.clear()
        else:
            # Reset button state on failure
            self.record_toggle_btn.blockSignals(True)
            self.record_toggle_btn.setChecked(False)
            self.record_toggle_btn.blockSignals(False)
            self._set_status(AppStatus.ERROR, auto_reset_seconds=5)
            QMessageBox.warning(self, "Recording Error", "Failed to access microphone. See logs.")

    def _stop_recording_and_process(self) -> None:
        """Stop recording and automatically trigger the complete processing workflow."""
        logger.info("Stop recording and process")
        
        try:
            # Step 1: Stop the audio recording
            logger.info("Step 1: Stopping audio recording")
            ok = self._recorder.stop()
            
            if not ok:
                # Reset button state on failure
                self.record_toggle_btn.blockSignals(True)
                self.record_toggle_btn.setChecked(False)
                self.record_toggle_btn.setText("▶ Start Recording")
                self.record_toggle_btn.blockSignals(False)
                self._set_status(AppStatus.ERROR, auto_reset_seconds=5)
                logger.error("Failed to stop recording properly")
                QMessageBox.warning(self, "Recording Error", "Failed to stop recording properly. See logs.")
                return
            
            # Recording stopped successfully
            self._last_audio_path = str(self._recorder.output_path) if self._recorder.output_path else None
            
            logger.info(f"Recording stopped successfully: {self._last_audio_path}")
            
            # Immediately update status to show recording is stopped
            if self._auto_process and self._last_audio_path:
                # Set status to processing and start workflow
                # Also reset the toggle visually to Start (remain disabled during processing)
                self.record_toggle_btn.blockSignals(True)
                try:
                    self.record_toggle_btn.setText("▶ Start Recording")
                    self.record_toggle_btn.setChecked(False)
                finally:
                    self.record_toggle_btn.blockSignals(False)
                self._set_status(AppStatus.PROCESSING_TRANSCRIPT)
                QTimer.singleShot(100, self._start_complete_workflow)
            else:
                self._set_status(AppStatus.READY)
                QMessageBox.information(self, "Recording Complete", 
                                      "Recording saved. Click 'Generate Suggestions' to continue processing.")
                
        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
            # Reset button state on failure - _set_status will handle this
            self.record_toggle_btn.blockSignals(True)
            self.record_toggle_btn.setChecked(False)
            self.record_toggle_btn.blockSignals(False)
            self._set_status(AppStatus.ERROR, auto_reset_seconds=5)
            QMessageBox.warning(self, "Recording Error", f"Error stopping recording: {e}")

    def _start_complete_workflow(self) -> None:
        """Complete workflow: transcribe -> generate summary -> save meeting -> update wiki -> update index."""
        if not self._last_audio_path:
            logger.error("No audio path available for workflow")
            self._set_status(AppStatus.ERROR)
            return

        logger.info(f"Starting complete workflow for: {self._last_audio_path}")
        self._transcribing = True

        def complete_workflow():
            transcript_text = None
            suggestions = None
            
            try:
                # Step 2: Processing transcript (ensure UI status on UI thread)
                logger.info("Step 2: Processing transcript")
                self.ui_set_status.emit(AppStatus.PROCESSING_TRANSCRIPT, None)
                
                # Step 3: Run transcription
                try:
                    backend = get_transcription_backend("openai")
                    start_time = time.time()
                    transcript_text = backend.transcribe(self._last_audio_path)
                    duration = time.time() - start_time
                    
                    if not transcript_text or not transcript_text.strip():
                        raise Exception("No transcript generated from audio")
                    
                    # Save transcript to file
                    self._save_transcript(transcript_text)
                    logger.info(f"Transcription completed in {duration:.2f}s")
                    
                    # Update UI with transcript (thread-safe)
                    self.ui_set_transcript.emit(transcript_text)
                    
                except TranscriptionUnavailable as e:
                    logger.warning(f"Transcription service unavailable: {e}")
                    self.ui_set_status.emit(AppStatus.ERROR, 5)
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Transcription Error", f"Transcription service unavailable: {e}"))
                    return
                except Exception as e:
                    logger.error(f"Transcription error: {e}")
                    self.ui_set_status.emit(AppStatus.ERROR, 5)
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Transcription Error", f"Failed to transcribe audio: {e}"))
                    return
                
                # Step 4: Update status to "Generating summary..."
                self.ui_set_status.emit(AppStatus.GENERATING_SUMMARY, None)
                logger.info("Step 4: Generating AI summary")
                
                # Step 5: Generate AI summary
                try:
                    gen = SuggestionGenerator()
                    suggestions = gen.generate(transcript_text)
                    
                    if not suggestions:
                        raise Exception("Failed to generate meeting summary")
                    
                    logger.info("AI summary generated successfully")
                    
                    # Update UI with suggestions (thread-safe)
                    self.ui_set_suggestions.emit(suggestions)
                    
                except SuggestionUnavailable as e:
                    logger.warning(f"Summary service unavailable: {e}")
                    self.ui_set_status.emit(AppStatus.ERROR, 5)
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Summary Error", f"AI summary service unavailable: {e}"))
                    return
                except Exception as e:
                    logger.error(f"Summary generation error: {e}")
                    self.ui_set_status.emit(AppStatus.ERROR, 5)
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Summary Error", f"Failed to generate summary: {e}"))
                    return
                
                # Step 6: Update status to "Updating wiki..."
                self.ui_set_status.emit(AppStatus.UPDATING_WIKI, None)
                logger.info("Step 6: Updating wiki and saving data")
                
                # Step 7-9: Save meeting JSON, Update wiki.md, Update meetings index
                try:
                    self._complete_save_workflow(suggestions, transcript_text)
                    logger.info("Save workflow completed successfully")
                except Exception as e:
                    logger.error(f"Save workflow error: {e}")
                    self.ui_set_status.emit(AppStatus.ERROR, 5)
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Save Error", f"Failed to save meeting data: {e}"))
                    return
                
                # Step 10: Update status to "Saved"
                logger.info("Step 10: Setting status to Saved")
                self.ui_set_status.emit(AppStatus.SAVED, 3)
                logger.info("Complete workflow finished successfully")
                
            except Exception as e:
                logger.error(f"Unexpected workflow error: {e}")
                self.ui_set_status.emit(AppStatus.ERROR, 5)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Workflow Error", f"Unexpected error during processing: {e}"))
            finally:
                # Re-enable buttons - this should happen after status is set
                logger.info("Workflow finally block - cleaning up")
                self._transcribing = False

        # Start workflow in background thread
        self._workflow_thread = threading.Thread(target=complete_workflow, daemon=True)
        self._workflow_thread.start()

    def _start_automatic_workflow(self) -> None:
        """Legacy method - redirect to complete workflow."""
        self._start_complete_workflow()

    def _save_transcript(self, transcript_text: str) -> None:
        """Save transcript to file and update meeting history."""
        if not self._current_meeting_id:
            logger.warning("No current meeting ID for transcript saving")
            return
        
        try:
            # Save transcript file
            out_path = self.config.transcripts_dir / f"{self._current_meeting_id}.txt"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(transcript_text, encoding="utf-8")
            
            # Update meeting history
            project = self._current_project_name()
            record = MeetingRecord(
                meeting_id=self._current_meeting_id,
                name=self.meeting_edit.text().strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d_%H%M')}",
                date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                project_name=project,
                transcript_path=str(out_path),
                summary_path=None,
                full_audio_path=self._last_audio_path,
            )
            self._history.add_or_update(record)
            logger.info(f"Transcript saved: {out_path}")
            
        except Exception as e:
            logger.error(f"Failed to save transcript: {e}")
            raise

    def _update_transcript_ui(self, transcript_text: str) -> None:
        """Update UI with transcript text."""
        self.transcript_view.setPlainText(transcript_text or "")

    def _update_suggestions_ui(self, suggestions: MeetingSuggestions) -> None:
        """Update UI with recap and BA/PM follow-ups only."""
        parts = []

        # Always show recap, if present
        recap_text = (suggestions.recap or "").strip()
        if recap_text:
            parts.append(f"RECAP:\n{recap_text}")

        # Build BA/PM follow-ups from action items and actionable questions
        followups: list[str] = []
        seen = set()
        # Include action items as-is
        for a in suggestions.actions or []:
            a_norm = a.strip()
            if a_norm and a_norm.lower() not in seen:
                followups.append(a_norm)
                seen.add(a_norm.lower())

        # Heuristics: include open questions that seem actionable
        import re as _re
        actionable_verbs = (
            r"follow|schedule|create|prepare|investigate|coordinate|confirm|draft|review|collect|align|meet|plan|define|specify|document|update|notify|ping|email|call|decide|approve|assign|track|test|deploy|fix|resolve|validate|estimate|prioritize"
        )
        pattern = _re.compile(rf"^(?:{actionable_verbs})\b|follow[- ]?up", _re.IGNORECASE)
        for q in suggestions.open_questions or []:
            q_norm = q.strip()
            if q_norm and pattern.search(q_norm):
                low = q_norm.lower()
                if low not in seen:
                    followups.append(q_norm)
                    seen.add(low)

        # Only add section if we have anything to do
        if followups:
            parts.append("BA/PM FOLLOW-UPS:\n" + "\n".join(f"• {f}" for f in followups))

        self.suggestions_view.setPlainText("\n\n".join(parts))

    def _complete_save_workflow(self, suggestions: MeetingSuggestions, transcript_text: str) -> None:
        """Complete the save workflow: JSON, wiki, and index updates."""
        project = self._current_project_name()
        meeting = self.meeting_edit.text().strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d_%H%M')}"
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Step 7: Save meeting JSON
        try:
            logger.info("Step 7: Saving meeting JSON")
            self._save_json_notes_and_update_index(project, suggestions)
            logger.info("Meeting JSON saved successfully")
        except Exception as e:
            logger.error(f"Failed to save meeting JSON: {e}")
            raise Exception(f"Failed to save meeting JSON: {e}")

        # Step 8: Update wiki.md
        try:
            logger.info("Step 8: Updating wiki.md")
            if project_manager.project_exists(project):
                wiki_path = project_manager.get_project_wiki_path(project)
            else:
                wiki_path = ensure_project_wiki(self.config.project_wikis_dir, project)
            
            upsert_meeting_section(
                wiki_path=wiki_path,
                meeting_date_yyyy_mm_dd=date_str,
                meeting_name=meeting,
                meeting_id=self._current_meeting_id,
                suggestions=suggestions,
            )
            logger.info(f"Wiki updated successfully: {wiki_path}")
        except Exception as e:
            logger.error(f"Failed to update wiki: {e}")
            raise Exception(f"Failed to update wiki: {e}")

        # Step 9: Update journal
        try:
            logger.info("Step 9: Updating journal")
            ensure_journal_date_section(self.config.project_wikis_dir, date_str)
            detail_bullets = []
            # Focus journal on what matters per your preference
            for t in (suggestions.recap or "").splitlines():
                t = t.strip()
                if t:
                    detail_bullets.append(f"Topic: {t}")
            for a in suggestions.actions:
                detail_bullets.append(f"To Do: {a}")
            for d in suggestions.decisions:
                detail_bullets.append(f"Accomplished: {d}")
                
            append_journal_entry(
                project_wikis_dir=self.config.project_wikis_dir,
                date_str=date_str,
                project=project,
                meeting=meeting,
                recap_one_line=suggestions.recap or meeting,
                details_bullets=detail_bullets or None,
            )
            logger.info("Journal updated successfully")
        except Exception as e:
            logger.error(f"Failed to update journal: {e}")
            raise Exception(f"Failed to update journal: {e}")
            
        logger.info(f"Complete save workflow finished successfully")

    def _reset_ui_after_workflow(self) -> None:
        """Reset UI state after workflow completion."""
        # Button states will be handled by the final status update
        # This method is kept for any additional cleanup needed
        pass

    def _workflow_transcription_complete(self, text: str) -> None:
        """Handle transcription completion in the automatic workflow."""
        self.transcript_view.setPlainText(text or "")
        
        # Save transcript
        if self._current_meeting_id and text:
            out_path = self.config.transcripts_dir / f"{self._current_meeting_id}.txt"
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text, encoding="utf-8")
                
                # Add to history
                project = self._current_project_name()
                record = MeetingRecord(
                    meeting_id=self._current_meeting_id,
                    name=self.meeting_edit.text().strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d_%H%M')}",
                    date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    project_name=project,
                    transcript_path=str(out_path),
                    summary_path=None,
                    full_audio_path=self._last_audio_path,
                )
                self._history.add_or_update(record)
            except Exception as e:
                logger.error(f"Failed to save transcript: {e}")

    def _workflow_suggestions_complete(self, suggestions: MeetingSuggestions) -> None:
        """Handle suggestions completion in the automatic workflow."""
        self._last_suggestions = suggestions
        
        # Pretty-print suggestions
        parts = []
        if suggestions.recap:
            parts.append(f"Recap: {suggestions.recap}")
        if suggestions.decisions:
            parts.append("Decisions:\n- " + "\n- ".join(suggestions.decisions))
        if suggestions.actions:
            parts.append("Actions:\n- " + "\n- ".join(suggestions.actions))
        if suggestions.risks:
            parts.append("Risks:\n- " + "\n- ".join(suggestions.risks))
        if suggestions.open_questions:
            parts.append("Open Questions:\n- " + "\n- ".join(suggestions.open_questions))
        
        self.suggestions_view.setPlainText("\n\n".join(parts))

    def _save_to_wiki_automatic(self, suggestions: MeetingSuggestions) -> None:
        """Save suggestions to wiki automatically (called from background thread)."""
        try:
            project = self._current_project_name()
            meeting = self.meeting_edit.text().strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d_%H%M')}"
            date_str = datetime.now().strftime("%Y-%m-%d")

            # Project wiki section upsert - use new project structure if available
            if project_manager.project_exists(project):
                # Use new structure: ./projects/{project}/wiki.md
                wiki_path = project_manager.get_project_wiki_path(project)
            else:
                # Fallback to old structure: ./meeting_data_v2/project_wikis/{project}_wiki.md
                wiki_path = ensure_project_wiki(self.config.project_wikis_dir, project)
            
            upsert_meeting_section(
                wiki_path=wiki_path,
                meeting_date_yyyy_mm_dd=date_str,
                meeting_name=meeting,
                meeting_id=self._current_meeting_id,
                suggestions=suggestions,
            )

            # Journal append
            ensure_journal_date_section(self.config.project_wikis_dir, date_str)
            detail_bullets = []
            for t in (suggestions.recap or "").splitlines():
                t = t.strip()
                if t:
                    detail_bullets.append(f"Topic: {t}")
            for a in suggestions.actions:
                detail_bullets.append(f"To Do: {a}")
            for d in suggestions.decisions:
                detail_bullets.append(f"Accomplished: {d}")
                
            append_journal_entry(
                project_wikis_dir=self.config.project_wikis_dir,
                date_str=date_str,
                project=project,
                meeting=meeting,
                recap_one_line=suggestions.recap or meeting,
                details_bullets=detail_bullets or None,
            )
            
            # Save JSON notes and update meeting index
            self._save_json_notes_and_update_index(project, suggestions)
            
            logger.info(f"Auto-saved to wiki: {wiki_path}")
            
        except Exception as e:
            logger.error(f"Auto-save to wiki failed: {e}")
            raise

    def _save_json_notes_and_update_index(self, project: str, suggestions: MeetingSuggestions) -> None:
        """Save JSON notes and update the meeting index."""
        try:
            if not self._current_meeting_id:
                logger.warning("No current meeting ID for JSON notes saving")
                return
            
            # Create JSON notes structure
            json_notes = {
                "decisions": suggestions.decisions,
                "action_items": suggestions.actions,
                "risks": suggestions.risks,
                "open_questions": suggestions.open_questions
            }
            
            # Save to old structure (meeting_data_v2/json_notes) for compatibility
            old_json_path = self.config.json_notes_dir / f"{self._current_meeting_id}_notes.json"
            old_json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(old_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(json_notes, f, indent=2, ensure_ascii=False)
            
            # Also save to new project structure if project exists in new system
            new_json_path = None
            if project_manager.project_exists(project):
                meetings_dir = project_manager.get_project_meetings_dir(project)
                new_json_path = meetings_dir / f"{self._current_meeting_id}_notes.json"
                new_json_path.parent.mkdir(parents=True, exist_ok=True)
                with open(new_json_path, 'w', encoding='utf-8') as f:
                    json.dump(json_notes, f, indent=2, ensure_ascii=False)
            
            # Update meeting history with JSON notes path
            if hasattr(self, '_history') and self._history:
                for record in self._history.records:
                    if record.meeting_id == self._current_meeting_id:
                        record.json_notes_path = str(old_json_path)
                        break
                self._history._save()
            
            # Get transcript path for index
            transcript_path = None
            if hasattr(self, '_current_meeting_id') and self._current_meeting_id:
                transcript_path = self.config.transcripts_dir / f"{self._current_meeting_id}.txt"
                if not transcript_path.exists():
                    transcript_path = None
            
            # Update meeting index
            meeting_index_builder.update_index_with_meeting(
                project_name=project,
                meeting_id=self._current_meeting_id,
                json_file_path=str(new_json_path if new_json_path else old_json_path),
                transcript_file_path=str(transcript_path) if transcript_path else None
            )
            
            logger.info(f"Saved JSON notes and updated index for meeting {self._current_meeting_id}")
            
        except Exception as e:
            logger.error(f"Failed to save JSON notes and update index: {e}")

    def _on_transcribe_clicked(self) -> None:
        """Manual transcription - kept for compatibility but not used in main workflow."""
        if not self._last_audio_path:
            QMessageBox.information(self, "Transcription", "No recording available to transcribe.")
            return
        self._start_transcription()

    def _start_transcription(self) -> None:
        if self._transcribing:
            self._set_status(AppStatus.ERROR)
            return
        if not self._last_audio_path:
            return
        self._set_status(AppStatus.PROCESSING_TRANSCRIPT)
        logger.info(f"Transcribing file: {self._last_audio_path}")
        self._transcribing = True
        # Button states will be handled by status updates
        self._set_button_states('processing')

        backend = get_transcription_backend("openai")

        def worker():
            start = time.time()
            try:
                text = backend.transcribe(self._last_audio_path)
            except TranscriptionUnavailable as e:
                logger.warning(str(e))
                self._update_status_safe(AppStatus.ERROR)
                self._transcription_finished_safe(None, error=str(e))
                return
            except Exception as e:
                logger.error(f"Transcription error: {e}")
                self._transcription_finished_safe(None, error=str(e))
                return
            duration = time.time() - start
            size = Path(self._last_audio_path).stat().st_size if self._last_audio_path else 0
            logger.info(f"Transcription completed in {duration:.2f}s, size={size} bytes")
            self._transcription_finished_safe(text)

        self._transcribe_thread = threading.Thread(target=worker, daemon=True)
        self._transcribe_thread.start()

    def _transcription_finished_safe(self, text: Optional[str], error: Optional[str] = None) -> None:
        # Marshal back to UI thread via singleShot event
        from PyQt5.QtCore import QTimer

        def apply():
            self._transcribing = False
            if error:
                self._set_status(AppStatus.ERROR)
                QMessageBox.warning(self, "Transcription", f"Failed: {error}")
                # Button states will be handled by status updates
            else:
                self.transcript_view.setPlainText(text or "")
                # Save to transcripts/<meeting_id>.txt if we have an id
                if self._current_meeting_id:
                    out_path = self.config.transcripts_dir / f"{self._current_meeting_id}.txt"
                    try:
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_text(text or "", encoding="utf-8")
                        self._set_status(AppStatus.READY)
                        has_text = bool(text and text.strip())
                        # Button states will be handled by _set_status
                        # Add minimal history record now (summary path will be added later steps)
                        project = self._current_project_name()
                        record = MeetingRecord(
                            meeting_id=self._current_meeting_id,
                            name=self.meeting_edit.text().strip() or f"Meeting {datetime.now().strftime('%Y-%m-%d_%H%M')}",
                            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                            project_name=project,
                            transcript_path=str(out_path),
                            summary_path=None,
                            full_audio_path=self._last_audio_path,
                        )
                        self._history.add_or_update(record)
                    except Exception as e:
                        logger.error(f"Failed to save transcript: {e}")
                        self._set_status(AppStatus.ERROR)
                else:
                    self._set_status(AppStatus.READY)
            # Nothing else here; handled above

        QTimer.singleShot(0, apply)

    def _on_suggest_clicked(self) -> None:
        """Deprecated: toolbar no longer exposes this action. Kept for backward compatibility."""
        text = self.transcript_view.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Suggestions", "No transcript available.")
            return
            
        gen = SuggestionGenerator()
        self._set_status(AppStatus.GENERATING_SUMMARY)
        self._set_busy(True)

        def worker():
            try:
                sugg = gen.generate(text)
                self._suggestions_finished_safe(sugg)
            except SuggestionUnavailable as e:
                logger.warning(str(e))
                self._suggestions_finished_safe(None, error=str(e))
            except Exception as e:
                logger.error(f"Suggestions error: {e}")
                self._suggestions_finished_safe(None, error=str(e))
            finally:
                QTimer.singleShot(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _suggestions_finished_safe(self, suggestions: Optional[MeetingSuggestions], error: Optional[str] = None) -> None:
        from PyQt5.QtCore import QTimer

        def apply():
            if error:
                self._set_status(AppStatus.ERROR)
                QMessageBox.warning(self, "Suggestions", f"Failed: {error}")
                return
            if not suggestions:
                self._set_status(AppStatus.READY)
                self.suggestions_view.clear()
                return
            # Pretty-print
            parts = []
            if suggestions.recap:
                parts.append(f"Recap: {suggestions.recap}")
            if suggestions.decisions:
                parts.append("Decisions:\n- " + "\n- ".join(suggestions.decisions))
            if suggestions.actions:
                parts.append("Actions:\n- " + "\n- ".join(suggestions.actions))
            if suggestions.risks:
                parts.append("Risks:\n- " + "\n- ".join(suggestions.risks))
            if suggestions.open_questions:
                parts.append("Open Questions:\n- " + "\n- ".join(suggestions.open_questions))
            self.suggestions_view.setPlainText("\n\n".join(parts))
            self._set_status(AppStatus.READY)
            self._last_suggestions = suggestions
            # Enable save-to-wiki/journal after suggestions present
            # Save action stays as currently enabled status

        QTimer.singleShot(0, apply)

    def _on_save_clicked(self) -> None:
        """Deprecated: toolbar no longer exposes this action. Kept for backward compatibility."""
        if not self._last_suggestions:
            QMessageBox.information(self, "Save", "No suggestions to save.")
            return
        if not self._current_meeting_id:
            QMessageBox.information(self, "Save", "No meeting id available.")
            return

        self._set_status(AppStatus.UPDATING_WIKI)
        self._set_busy(True)

        def save_worker():
            try:
                self._save_to_wiki_automatic(self._last_suggestions)
                QTimer.singleShot(0, lambda: self._set_status(AppStatus.SAVED, auto_reset_seconds=3))
                
                # Show path based on new or old structure
                project = self._current_project_name()
                if project_manager.project_exists(project):
                    wiki_path = project_manager.get_project_wiki_path(project)
                else:
                    wiki_path = self.config.project_wikis_dir / f'{project}_wiki.md'
                
                QTimer.singleShot(0, lambda: QMessageBox.information(
                    self, "Save", 
                    f"Saved to:\n- {wiki_path}\n- {self.config.project_wikis_dir / 'Journal_wiki.md'}"
                ))
            except Exception as e:
                logger.error(f"Manual save failed: {e}")
                QTimer.singleShot(0, lambda: self._set_status(AppStatus.ERROR))
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "Save Error", f"Failed to save: {e}"))
            finally:
                QTimer.singleShot(0, lambda: self._set_busy(False))

        threading.Thread(target=save_worker, daemon=True).start()



    def _on_weekly_clicked(self) -> None:
        self._set_status(AppStatus.UPDATING_WIKI)
        try:
            # Get current project
            project_name = self._current_project_name()
            
            # Build structured summary for popup
            from services.weekly import build_weekly_structured_summary_for_project
            data = build_weekly_structured_summary_for_project(
                self.config.project_wikis_dir, 
                project_name
            )

            # Also persist the weekly file as before
            out = generate_weekly_from_journal(
                project_wikis_dir=self.config.project_wikis_dir,
                weekly_dir=self.config.weekly_summaries_dir,
                project_name=project_name,
            )

            # Compose a copyable HTML in a dialog
            topics = data.get('topics', [])
            dates = data.get('dates', [])
            accomplished = data.get('accomplished', [])
            next_week = data.get('next_week', [])
            challenges = data.get('challenges', [])
            
            # Generate title like the example image
            from datetime import date
            target_day = date.today()
            iso_year, iso_week, _ = target_day.isocalendar()
            week_ending = target_day.strftime("%B %d, %Y")
            title = f"Weekly Status Update: {project_name} (Week Ending {week_ending})"
            
            html = [
                "<div style='font-family:Segoe UI, Arial, sans-serif; font-size:14px; line-height:1.6; max-width:800px; margin:0 auto;'>",
                f"<h1 style='margin:0 0 20px 0; color:#2c3e50; font-size:18px; font-weight:600;'>{title}</h1>",
            ]
            
            # Executive Summary - prominent and rich
            exec_summary = data.get('exec_summary', 'No summary available.')
            html.append(f"<h2 style='margin:0 0 10px 0; color:#34495e; font-size:16px;'>Executive Summary:</h2>")
            html.append(f"<p style='margin:0 0 24px 0; padding:16px; background:#f8f9fa; border-left:4px solid #3498db; text-align:justify; line-height:1.5;'>{exec_summary}</p>")
            
            # What We Accomplished This Week
            if accomplished:
                html.append("<h2 style='margin:0 0 10px 0; color:#27ae60; font-size:16px;'>What We Accomplished This Week:</h2>")
                html.append("<ul style='margin:0 0 24px 0; padding-left:0; list-style:none;'>")
                for item in accomplished:
                    html.append(f"<li style='margin:8px 0; padding:8px 0 8px 24px; border-left:3px solid #27ae60; background:#f8fff8; position:relative;'>")
                    html.append(f"<span style='position:absolute; left:8px; color:#27ae60; font-weight:bold;'>•</span>{item}")
                    html.append("</li>")
                html.append("</ul>")
            
            # Plans for Next Week
            if next_week:
                html.append("<h2 style='margin:0 0 10px 0; color:#e67e22; font-size:16px;'>Plans for Next Week:</h2>")
                html.append("<ul style='margin:0 0 24px 0; padding-left:0; list-style:none;'>")
                for item in next_week:
                    html.append(f"<li style='margin:8px 0; padding:8px 0 8px 24px; border-left:3px solid #e67e22; background:#fffaf6; position:relative;'>")
                    html.append(f"<span style='position:absolute; left:8px; color:#e67e22; font-weight:bold;'>•</span>{item}")
                    html.append("</li>")
                html.append("</ul>")
            
            # Challenges & Issues (if any)
            if challenges:
                html.append("<h2 style='margin:0 0 10px 0; color:#e74c3c; font-size:16px;'>Challenges & Issues to Address:</h2>")
                html.append("<ul style='margin:0 0 24px 0; padding-left:0; list-style:none;'>")
                for item in challenges:
                    html.append(f"<li style='margin:8px 0; padding:8px 0 8px 24px; border-left:3px solid #e74c3c; background:#fef8f8; position:relative;'>")
                    html.append(f"<span style='position:absolute; left:8px; color:#e74c3c; font-weight:bold;'>!</span>{item}")
                    html.append("</li>")
                html.append("</ul>")
            
            # Key Topics (condensed)
            if topics:
                html.append("<h2 style='margin:0 0 10px 0; color:#95a5a6; font-size:14px;'>Key Topics Discussed:</h2>")
                html.append(f"<p style='margin:0 0 24px 0; font-style:italic; color:#7f8c8d;'>{', '.join(topics[:8])}</p>")
            
            # No data message
            if not accomplished and not next_week and not challenges:
                html.append("<div style='text-align:center; padding:40px 20px; color:#95a5a6; font-style:italic;'>")
                html.append("<p>No significant activity recorded for this project during the selected time period.</p>")
                html.append("<p style='font-size:12px;'>Ensure meetings are being recorded and journal entries are being made to generate comprehensive summaries.</p>")
                html.append("</div>")
            
            # Footer
            html.append(f"<hr style='margin:30px 0 20px 0; border:none; border-top:1px solid #ecf0f1;'>")
            if dates:
                date_range = f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else dates[0]
                html.append(f"<p style='color:#95a5a6; font-size:12px; margin:0 0 8px 0;'>Report Period: {date_range}</p>")
            html.append(f"<p style='color:#95a5a6; font-size:12px; margin:0;'>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Saved to: {out.name}</p>")
            html.append("</div>")

            # Show in a modal with copyable content
            dlg = QDialog(self)
            dlg.setWindowTitle("Weekly Summary Preview")
            dlg.resize(700, 500)
            v = QVBoxLayout(dlg)
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml("".join(html))
            v.addWidget(browser, 1)
            btns = QHBoxLayout()
            copy_btn = QPushButton("Copy to Clipboard")
            def _copy():
                QApplication.clipboard().setText(browser.toPlainText())
                QMessageBox.information(self, "Copied", "Weekly summary copied to clipboard.")
            copy_btn.clicked.connect(_copy)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dlg.accept)
            btns.addWidget(copy_btn)
            btns.addStretch()
            btns.addWidget(close_btn)
            v.addLayout(btns)
            dlg.exec_()

            self._set_status(AppStatus.SAVED, auto_reset_seconds=3)
        except Exception as e:
            logger.error(f"Weekly summary failed: {e}")
            self._set_status(AppStatus.ERROR)
            QMessageBox.warning(self, "Weekly Summary", f"Failed: {e}")

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change event."""
        if index == 1:  # Wiki tab (0=Recording, 1=Wiki, 2=Meetings)
            self._load_wiki_content()
        elif index == 2:
            # Refresh meetings list when switching to Meetings tab
            self._load_meetings_list()

    def _load_wiki_content(self) -> None:
        """Load the wiki content for the currently selected project."""
        try:
            project_name = self._current_project_name()
            
            # Try to get wiki from new project structure first
            if project_manager.project_exists(project_name):
                wiki_path = project_manager.get_project_wiki_path(project_name)
            else:
                # Fallback to old structure
                wiki_path = self.config.project_wikis_dir / f"{project_name}_wiki.md"
            
            if wiki_path.exists():
                content = wiki_path.read_text(encoding="utf-8")
                
                # Convert markdown to HTML for viewer
                html_content = markdown2.markdown(content, extras=['fenced-code-blocks', 'tables'])
                self.wiki_viewer.setHtml(html_content)
                
                # Set raw content in editor
                self.wiki_editor.setPlainText(content)
            else:
                # Show empty state
                empty_msg = f"No wiki found for project '{project_name}'. Select a project from the Recording tab to create a wiki."
                self.wiki_viewer.setPlainText(empty_msg)
                self.wiki_editor.setPlainText("")
                
        except Exception as e:
            logger.error(f"Failed to load wiki content: {e}")
            self.wiki_viewer.setPlainText(f"Error loading wiki: {e}")

    def _on_edit_mode_toggled(self, state: int) -> None:
        """Handle edit mode toggle."""
        edit_mode = bool(state)
        
        # Toggle visibility
        self.wiki_viewer.setVisible(not edit_mode)
        self.wiki_editor.setVisible(edit_mode)
        self.save_wiki_btn.setVisible(edit_mode)
        
        # Clear search when switching modes to avoid confusion
        self._clear_search()
        self.search_input.clear()
        
        if edit_mode:
            # Focus the editor
            self.wiki_editor.setFocus()

    def _on_wiki_refresh(self) -> None:
        """Refresh wiki content from file."""
        self._load_wiki_content()
        QMessageBox.information(self, "Wiki", "Wiki content refreshed.")

    def _on_wiki_save(self) -> None:
        """Save wiki changes."""
        try:
            project_name = self._current_project_name()
            
            # Get current content from editor
            content = self.wiki_editor.toPlainText()
            
            # Determine save path (prefer new structure)
            if project_manager.project_exists(project_name):
                wiki_path = project_manager.get_project_wiki_path(project_name)
            else:
                # Create new project structure if it doesn't exist
                project_manager.ensure_project_structure(project_name)
                wiki_path = project_manager.get_project_wiki_path(project_name)
            
            # Save content
            wiki_path.write_text(content, encoding="utf-8")
            
            # Refresh viewer
            html_content = markdown2.markdown(content, extras=['fenced-code-blocks', 'tables'])
            self.wiki_viewer.setHtml(html_content)
            
            self._set_status(AppStatus.SAVED, auto_reset_seconds=3)
            QMessageBox.information(self, "Wiki", f"Wiki saved successfully to {wiki_path}")
            
        except Exception as e:
            logger.error(f"Failed to save wiki: {e}")
            self._set_status(AppStatus.ERROR)
            QMessageBox.warning(self, "Wiki Error", f"Failed to save wiki: {e}")

    def _on_search_text_changed(self, text: str) -> None:
        """Handle search text changes with debouncing."""
        self.search_timer.stop()
        if text.strip():
            # Start timer for debounced search (300ms delay)
            self.search_timer.start(300)
        else:
            # Clear search immediately if text is empty
            self._clear_search()

    def _perform_search(self) -> None:
        """Perform the actual search with highlighting."""
        search_term = self.search_input.text().strip()
        if not search_term:
            self._clear_search()
            return
        
        self.current_search_term = search_term
        
        # Get the current content
        if self.edit_mode_cb.isChecked():
            # Search in editor
            text_widget = self.wiki_editor
            content = self.wiki_editor.toPlainText()
        else:
            # Search in viewer (use plain text version)
            text_widget = self.wiki_viewer
            content = self.wiki_viewer.toPlainText()
        
        # Find all matches (case-insensitive)
        self.search_matches = []
        if content and search_term:
            # Use regex to find all matches with their positions
            pattern = re.compile(re.escape(search_term), re.IGNORECASE)
            for match in pattern.finditer(content):
                self.search_matches.append((match.start(), match.end()))
        
        # Update UI
        self._update_search_ui()
        
        # Highlight matches and go to first match
        if self.search_matches:
            self.current_match_index = 0
            self._highlight_matches(text_widget, content)
            self._go_to_current_match(text_widget)

    def _clear_search(self) -> None:
        """Clear search results and highlighting."""
        self.search_matches = []
        self.current_match_index = -1
        self.current_search_term = ""
        self._update_search_ui()
        
        # Clear highlighting
        if self.edit_mode_cb.isChecked():
            # For editor, we'll need to reload the content to clear highlighting
            cursor = self.wiki_editor.textCursor()
            cursor.clearSelection()
        else:
            # For viewer, reload the content to clear highlighting
            self._load_wiki_content()

    def _update_search_ui(self) -> None:
        """Update search UI elements (count, buttons)."""
        match_count = len(self.search_matches)
        current_pos = self.current_match_index + 1 if self.current_match_index >= 0 else 0
        
        self.search_count_label.setText(f"{current_pos}/{match_count}")
        
        has_matches = match_count > 0
        self.prev_match_btn.setEnabled(has_matches and match_count > 1)
        self.next_match_btn.setEnabled(has_matches and match_count > 1)

    def _highlight_matches(self, text_widget, content: str) -> None:
        """Highlight all search matches in the text widget."""
        if not self.search_matches or not self.current_search_term:
            return
        
        if self.edit_mode_cb.isChecked():
            # For QTextEdit, use text cursor to highlight
            self._highlight_in_editor(text_widget, content)
        else:
            # For QTextBrowser, modify HTML content with highlighting
            self._highlight_in_viewer(content)

    def _highlight_in_editor(self, editor, content: str) -> None:
        """Highlight matches in the editor using selections."""
        cursor = editor.textCursor()
        cursor.clearSelection()
        
        # Create selection format for highlighting
        format = QTextCharFormat()
        format.setBackground(QColor(255, 255, 0, 128))  # Yellow background
        
        # Clear previous formatting
        cursor.select(QTextDocument.SelectionType.Document)
        cursor.mergeCharFormat(QTextCharFormat())  # Clear formatting
        cursor.clearSelection()
        
        # Note: QTextEdit doesn't easily support multiple highlights simultaneously
        # For simplicity, we'll just go to the current match
        if self.current_match_index >= 0 and self.current_match_index < len(self.search_matches):
            start, end = self.search_matches[self.current_match_index]
            cursor.setPosition(start)
            cursor.setPosition(end, QTextDocument.FindFlag.KeepAnchor)
            cursor.mergeCharFormat(format)

    def _highlight_in_viewer(self, content: str) -> None:
        """Highlight matches in the viewer by modifying HTML."""
        if not self.current_search_term:
            return
        
        # Convert content to HTML if it's not already
        if not content.startswith('<'):
            html_content = markdown2.markdown(content, extras=['fenced-code-blocks', 'tables'])
        else:
            html_content = content
        
        # Add highlighting to HTML
        pattern = re.compile(f'({re.escape(self.current_search_term)})', re.IGNORECASE)
        highlighted_html = pattern.sub(r'<mark style="background-color: yellow;">\1</mark>', html_content)
        
        self.wiki_viewer.setHtml(highlighted_html)

    def _go_to_current_match(self, text_widget) -> None:
        """Navigate to the current match in the text widget."""
        if not self.search_matches or self.current_match_index < 0:
            return
        
        start, end = self.search_matches[self.current_match_index]
        
        if self.edit_mode_cb.isChecked():
            # For editor
            cursor = self.wiki_editor.textCursor()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextDocument.FindFlag.KeepAnchor)
            self.wiki_editor.setTextCursor(cursor)
            self.wiki_editor.ensureCursorVisible()
        else:
            # For viewer, we've already highlighted in HTML, just scroll to top of highlighted content
            # QTextBrowser doesn't have great support for scrolling to specific positions
            # So we'll use a simple approach
            cursor = self.wiki_viewer.textCursor()
            cursor.setPosition(start)
            self.wiki_viewer.setTextCursor(cursor)
            self.wiki_viewer.ensureCursorVisible()

    def _on_previous_match(self) -> None:
        """Navigate to the previous search match."""
        if not self.search_matches:
            return
        
        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self._update_search_ui()
        
        # Re-highlight and navigate
        if self.edit_mode_cb.isChecked():
            content = self.wiki_editor.toPlainText()
            self._highlight_matches(self.wiki_editor, content)
            self._go_to_current_match(self.wiki_editor)
        else:
            content = self.wiki_viewer.toPlainText()
            self._highlight_in_viewer(content)
            self._go_to_current_match(self.wiki_viewer)

    def _on_next_match(self) -> None:
        """Navigate to the next search match."""
        if not self.search_matches:
            return
        
        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self._update_search_ui()
        
        # Re-highlight and navigate
        if self.edit_mode_cb.isChecked():
            content = self.wiki_editor.toPlainText()
            self._highlight_matches(self.wiki_editor, content)
            self._go_to_current_match(self.wiki_editor)
        else:
            content = self.wiki_viewer.toPlainText()
            self._highlight_in_viewer(content)
            self._go_to_current_match(self.wiki_viewer)

    def _on_quick_query(self) -> None:
        """Handle natural language queries about meetings."""
        query_text = self.query_input.text().strip()
        if not query_text:
            self.query_results.setVisible(False)
            return
        
        project_name = self._current_project_name()
        
        try:
            # Parse the natural language query
            context = query_parser.parse(query_text)
            
            # Build search query from parsed context
            search_query = build_search_query(context)
            
            if not search_query:
                self._show_query_results("No searchable terms found in your query. Try asking about specific topics, people, or decisions.")
                return
            
            # Search the meeting index
            results = meeting_index_builder.search_index(project_name, search_query, max_results=20)
            
            if not results:
                self._show_query_results(f"No meetings found for '{query_text}'. Try different keywords or check if the project has meetings indexed.")
                return
            
            # Filter results by context (intent, people, etc.)
            filtered_results = filter_results_by_context(results, context)
            
            # Format and display results
            formatted_results = self._format_query_results(filtered_results, context, query_text)
            self._show_query_results(formatted_results)
            
        except Exception as e:
            logger.error(f"Error processing quick query: {e}")
            self._show_query_results(f"Error processing query: {e}")

    def _show_query_results(self, html_content: str) -> None:
        """Display query results in the results area."""
        self.query_results.setHtml(html_content)
        self.query_results.setVisible(True)
        self.clear_query_btn.setVisible(True)

    def _on_clear_query(self) -> None:
        """Clear quick query input and results, restoring default view."""
        self.query_input.clear()
        self.query_results.clear()
        self.query_results.setVisible(False)
        self.clear_query_btn.setVisible(False)
        # Optionally refocus input for next query
        self.query_input.setFocus()

    def _format_query_results(self, results, context, original_query: str) -> str:
        """Format search results as HTML with excerpts and links."""
        if not results:
            return f"<p><i>No results found for: '{original_query}'</i></p>"
        
        html = f"<h3>Results for: '{original_query}'</h3>"
        html += f"<p><small>Found {len(results)} matching meetings</small></p>"
        
        for i, meeting in enumerate(results[:10]):  # Limit to top 10 results
            html += f"<div style='border: 1px solid #ddd; margin: 10px 0; padding: 10px; border-radius: 5px;'>"
            
            # Meeting header
            html += f"<h4 style='margin: 0 0 5px 0; color: #1976D2;'>{meeting.meeting_name}</h4>"
            html += f"<p style='margin: 0 0 10px 0; color: #666; font-size: 12px;'>📅 {meeting.date} | 🏷️ {meeting.project_name} | 📝 {meeting.word_count:,} words</p>"
            
            # Show relevant content based on intent
            excerpts = self._extract_relevant_excerpts(meeting, context, original_query)
            
            if excerpts:
                html += "<div style='background: #f5f5f5; padding: 8px; border-radius: 3px; margin: 5px 0;'>"
                for excerpt_type, excerpt_text in excerpts:
                    html += f"<p><strong>{excerpt_type}:</strong> {excerpt_text}</p>"
                html += "</div>"
            
            # Link to wiki (this could be enhanced to link to specific meeting sections)
            project_wiki_path = f"./projects/{meeting.project_name}/wiki.md"
            html += f"<p style='margin: 5px 0 0 0;'><small>📁 <a href='file:///{project_wiki_path}'>View in Wiki</a> | 📄 <code>{meeting.json_file_path}</code></small></p>"
            
            html += "</div>"
        
        if len(results) > 10:
            html += f"<p><i>... and {len(results) - 10} more results. Try refining your search for more specific results.</i></p>"
        
        return html

    def _extract_relevant_excerpts(self, meeting, context, query: str) -> List[Tuple[str, str]]:
        """Extract relevant excerpts from a meeting based on the query context."""
        excerpts = []
        query_lower = query.lower()
        
        # Helper function to truncate text around keywords
        def get_excerpt(text: str, max_length: int = 150) -> str:
            if not text:
                return ""
            
            # Find the best position to show (around query keywords)
            best_pos = 0
            for keyword in context.keywords + [name.lower() for name in context.people]:
                pos = text.lower().find(keyword)
                if pos != -1:
                    best_pos = max(0, pos - 50)
                    break
            
            if len(text) <= max_length:
                return text
            
            start = best_pos
            end = min(len(text), start + max_length)
            
            excerpt = text[start:end]
            if start > 0:
                excerpt = "..." + excerpt
            if end < len(text):
                excerpt = excerpt + "..."
                
            return excerpt
        
        # Check decisions based on intent
        if context.intent in ['decision', 'general'] and meeting.decisions:
            for decision in meeting.decisions:
                if any(keyword in decision.lower() for keyword in context.keywords + [query_lower]):
                    excerpts.append(("Decision", get_excerpt(decision)))
                    break
        
        # Check action items
        if context.intent in ['action', 'general'] and meeting.action_items:
            for action in meeting.action_items:
                if any(keyword in action.lower() for keyword in context.keywords + [query_lower]) or \
                   any(person.lower() in action.lower() for person in context.people):
                    excerpts.append(("Action Item", get_excerpt(action)))
                    if context.intent == 'action':  # Show more actions for action queries
                        continue
                    break
        
        # Check risks
        if context.intent in ['risk', 'general'] and meeting.risks:
            for risk in meeting.risks:
                if any(keyword in risk.lower() for keyword in context.keywords + [query_lower]):
                    excerpts.append(("Risk", get_excerpt(risk)))
                    break
        
        # Check open questions
        if context.intent in ['question', 'general'] and meeting.open_questions:
            for question in meeting.open_questions:
                if any(keyword in question.lower() for keyword in context.keywords + [query_lower]):
                    excerpts.append(("Open Question", get_excerpt(question)))
                    break
        
        # If no structured content matches, check transcript
        if not excerpts and meeting.full_transcript:
            # Find a relevant excerpt from the transcript
            transcript_lower = meeting.full_transcript.lower()
            for keyword in context.keywords:
                pos = transcript_lower.find(keyword)
                if pos != -1:
                    start = max(0, pos - 75)
                    end = min(len(meeting.full_transcript), pos + 75)
                    excerpt = meeting.full_transcript[start:end]
                    if start > 0:
                        excerpt = "..." + excerpt
                    if end < len(meeting.full_transcript):
                        excerpt = excerpt + "..."
                    excerpts.append(("Transcript", excerpt))
                    break
        
        return excerpts[:3]  # Limit to 3 excerpts per meeting

    def _current_project_name(self) -> str:
        val = self.project_combo.currentText().strip()
        if not val or val == "New Project…":
            return "Default"
        return val


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("AibaTS Desktop Tool")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())



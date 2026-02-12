"""Main application window with sidebar navigation."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QStackedWidget,
    QPushButton,
    QLabel,
    QStatusBar,
    QFrame,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, QTimer
from PyQt6.QtGui import QCloseEvent, QIcon, QKeySequence, QPixmap, QShortcut, QFont

from src.utils.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
)
from pathlib import Path

from src.utils.logger import get_logger

_LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logo.png"
from src.gui.worker import (
    ProcessingWorker,
    ReviewApplyWorker,
    PreviewApplyWorker,
    ManualSearchWorker,
)
from src.core.batch_processor import BatchResult
from src.models.track import Track
from src.models.match_result import MatchCandidate, MatchResult
from src.models.processing_state import ProcessingState

logger = get_logger("gui.app")


class ToastNotification(QFrame):
    """Non-blocking notification banner that auto-dismisses.

    Shows a summary message at the top of the window with a close button.
    Automatically hides after *duration_ms* milliseconds.
    """

    def __init__(
        self, message: str, parent: QWidget, duration_ms: int = 8000,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setStyleSheet("""
            #toast {
                background-color: #313244;
                border: 1px solid #a6e3a1;
                border-radius: 10px;
                padding: 12px 16px;
            }
            #toast QLabel { color: #cdd6f4; }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(msg_label, 1)

        close_btn = QPushButton("Dismiss")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn)

        # Auto-dismiss timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(duration_ms)

    def _dismiss(self) -> None:
        """Hide and schedule deletion."""
        self._timer.stop()
        self.hide()
        self.deleteLater()


class SidebarButton(QPushButton):
    """Styled sidebar navigation button."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation and stacked content area.

    Layout:
    ┌──────────┬────────────────────────────────────┐
    │ Sidebar  │ Content Area (stacked views)        │
    │          │                                     │
    │ Import   │  0                                  │
    │ Progress │  1                                  │
    │ Preview  │  2                                  │
    │ Review   │  3                                  │
    │ Library  │  4                                  │
    │ Settings │  5                                  │
    │          │                                     │
    └──────────┴────────────────────────────────────┘
    │                  Status Bar                    │
    └────────────────────────────────────────────────┘
    """

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._sidebar_buttons: list[SidebarButton] = []
        self._worker: ProcessingWorker | None = None
        self._worker_thread: QThread | None = None
        self._review_worker: ReviewApplyWorker | None = None
        self._review_thread: QThread | None = None
        self._preview_apply_worker: PreviewApplyWorker | None = None
        self._preview_apply_thread: QThread | None = None
        self._search_worker: ManualSearchWorker | None = None
        self._search_thread: QThread | None = None
        self._last_result: BatchResult | None = None
        self._dry_run_pending: bool = False

        self._setup_window()
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._apply_theme()

        # Select the first view by default
        self._switch_view(0)

        logger.info("Main window initialized")

    def _setup_window(self) -> None:
        """Configure window properties."""
        self.setWindowTitle(APP_NAME)

        # Build a multi-size icon for crisp rendering at every DPI and
        # context (title-bar, taskbar, Alt-Tab, etc.).
        if _LOGO_PATH.exists():
            icon = QIcon()
            source = QPixmap(str(_LOGO_PATH))
            if not source.isNull():
                for size in (16, 24, 32, 48, 64, 128, 256):
                    icon.addPixmap(
                        source.scaled(
                            size, size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            self.setWindowIcon(icon)

        width = self._config.get("window_width", DEFAULT_WINDOW_WIDTH)
        height = self._config.get("window_height", DEFAULT_WINDOW_HEIGHT)
        self.resize(width, height)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

    def _setup_ui(self) -> None:
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Sidebar ---
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(4)

        # App logo in sidebar
        if _LOGO_PATH.exists():
            logo_label = QLabel()
            logo_label.setObjectName("sidebarLogo")
            pixmap = QPixmap(str(_LOGO_PATH))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo_label.setPixmap(pixmap)
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sidebar_layout.addWidget(logo_label)
                sidebar_layout.addSpacing(4)

        # App title in sidebar
        title_label = QLabel(APP_NAME)
        title_label.setObjectName("sidebarTitle")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(title_label)
        sidebar_layout.addSpacing(20)

        # Navigation buttons
        nav_items = [
            "Import",
            "Progress",
            "Preview",
            "Review",
            "Library",
            "Settings",
        ]

        for idx, name in enumerate(nav_items):
            btn = SidebarButton(name)
            btn.clicked.connect(lambda checked, i=idx: self._switch_view(i))
            self._sidebar_buttons.append(btn)
            sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()

        # Version label at bottom of sidebar
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("versionLabel")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version_label)

        main_layout.addWidget(sidebar)

        # --- Content Area ---
        self._content_stack = QStackedWidget()
        self._content_stack.setObjectName("contentStack")

        from src.gui.views.import_view import ImportView
        from src.gui.views.scan_progress_view import ScanProgressView
        from src.gui.views.preview_view import PreviewView
        from src.gui.views.review_view import ReviewView
        from src.gui.views.library_view import LibraryView
        from src.gui.views.settings_view import SettingsView

        self._import_view = ImportView(self._config)
        self._progress_view = ScanProgressView(self._config)
        self._preview_view = PreviewView(self._config)
        self._review_view = ReviewView(self._config)
        self._library_view = LibraryView(self._config)
        self._settings_view = SettingsView(self._config)

        self._content_stack.addWidget(self._import_view)      # 0
        self._content_stack.addWidget(self._progress_view)     # 1
        self._content_stack.addWidget(self._preview_view)      # 2
        self._content_stack.addWidget(self._review_view)       # 3
        self._content_stack.addWidget(self._library_view)      # 4
        self._content_stack.addWidget(self._settings_view)     # 5

        main_layout.addWidget(self._content_stack)

        # --- Status Bar ---
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

    def _connect_signals(self) -> None:
        """Wire up all view signals to their handlers."""
        # Import view -> start processing
        self._import_view.scan_requested.connect(self._on_scan_requested)
        self._import_view.preview_requested.connect(self._on_preview_requested)

        # Progress view -> pause/resume/cancel
        self._progress_view.pause_requested.connect(self._on_pause)
        self._progress_view.resume_requested.connect(self._on_resume)
        self._progress_view.cancel_requested.connect(self._on_cancel)

        # Preview view -> apply approved / back to import
        self._preview_view.apply_approved.connect(self._on_preview_apply)
        self._preview_view.back_to_import.connect(lambda: self._switch_view(0))

        # Review view -> batch apply / skip / manual search
        self._review_view.batch_apply_requested.connect(self._on_batch_apply)
        self._review_view.track_skipped.connect(self._on_track_skipped)
        self._review_view.manual_search_requested.connect(self._on_manual_search)

        # Settings view -> reload config and re-apply theme
        self._settings_view.settings_changed.connect(self._on_settings_changed)

    def _setup_shortcuts(self) -> None:
        """Set up keyboard shortcuts."""
        shortcuts = [
            ("Ctrl+1", 0),  # Import
            ("Ctrl+2", 1),  # Progress
            ("Ctrl+3", 2),  # Preview
            ("Ctrl+4", 3),  # Review
            ("Ctrl+5", 4),  # Library
            ("Ctrl+6", 5),  # Settings
        ]
        for key_combo, view_idx in shortcuts:
            shortcut = QShortcut(QKeySequence(key_combo), self)
            shortcut.activated.connect(lambda i=view_idx: self._switch_view(i))

    def _switch_view(self, index: int) -> None:
        """Switch the content area to a different view.

        Args:
            index: View index (0=Import, 1=Progress, 2=Preview,
                   3=Review, 4=Library, 5=Settings).
        """
        self._content_stack.setCurrentIndex(index)

        # Update sidebar button states
        for i, btn in enumerate(self._sidebar_buttons):
            btn.setChecked(i == index)

    def _apply_theme(self) -> None:
        """Apply the dark or light theme stylesheet."""
        from src.gui.styles.theme import get_dark_theme_qss, get_light_theme_qss

        theme = self._config.get("theme", "dark")

        if theme == "dark":
            self.setStyleSheet(get_dark_theme_qss())
        else:
            self.setStyleSheet(get_light_theme_qss())

    def update_status(self, message: str) -> None:
        """Update the status bar message.

        Args:
            message: Status message to display.
        """
        self._status_bar.showMessage(message)

    def _show_toast(self, message: str, duration_ms: int = 8000) -> None:
        """Show a non-blocking toast notification at the top of the content area.

        Args:
            message: Text to display.
            duration_ms: Auto-dismiss delay in milliseconds.
        """
        toast = ToastNotification(message, self._content_stack, duration_ms)
        toast.setFixedWidth(self._content_stack.width() - 80)
        toast.move(40, 10)
        toast.show()
        toast.raise_()

    # --- Signal Handlers ---

    def _on_scan_requested(self, paths: list) -> None:
        """Handle the scan request from the Import view.

        Creates a worker thread and starts the batch processor.

        Args:
            paths: List of file/folder path strings.
        """
        if self._worker_thread and self._worker_thread.isRunning():
            QMessageBox.warning(
                self,
                "Processing In Progress",
                "A scan is already running. Please wait for it to finish or cancel it first.",
            )
            return

        logger.info("Starting scan for %d paths", len(paths))
        self.update_status("Starting scan...")

        # Switch to progress view
        self._switch_view(1)

        # Reset progress view
        self._progress_view.reset(0)

        # Create worker and thread
        self._worker_thread = QThread()
        self._worker = ProcessingWorker(paths, self._config)
        self._worker.moveToThread(self._worker_thread)

        # Connect worker signals
        self._worker_thread.started.connect(self._worker.run)
        self._worker.scan_completed.connect(self._on_scan_completed)
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.stats_updated.connect(self._on_stats_updated)
        self._worker.processing_finished.connect(self._on_processing_finished)
        self._worker.error_occurred.connect(self._on_worker_error)

        # Clean up thread when done
        self._worker.processing_finished.connect(self._worker_thread.quit)
        self._worker.error_occurred.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._on_thread_finished)

        # Start
        self._worker_thread.start()

    def _on_preview_requested(self, paths: list) -> None:
        """Handle the preview request from the Import view (dry-run).

        Creates a worker thread with dry_run=True.

        Args:
            paths: List of file/folder path strings.
        """
        if self._worker_thread and self._worker_thread.isRunning():
            QMessageBox.warning(
                self,
                "Processing In Progress",
                "A scan is already running. Please wait for it to finish or cancel it first.",
            )
            return

        logger.info("Starting preview (dry-run) for %d paths", len(paths))
        self.update_status("Starting preview scan...")
        self._dry_run_pending = True

        # Switch to progress view
        self._switch_view(1)
        self._progress_view.reset(0)

        # Create worker with dry_run=True
        self._worker_thread = QThread()
        self._worker = ProcessingWorker(paths, self._config, dry_run=True)
        self._worker.moveToThread(self._worker_thread)

        # Connect worker signals (same as normal scan)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.scan_completed.connect(self._on_scan_completed)
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.stats_updated.connect(self._on_stats_updated)
        self._worker.processing_finished.connect(self._on_processing_finished)
        self._worker.error_occurred.connect(self._on_worker_error)

        # Clean up thread when done
        self._worker.processing_finished.connect(self._worker_thread.quit)
        self._worker.error_occurred.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._on_thread_finished)

        self._worker_thread.start()

    def _on_scan_completed(self, total_files: int) -> None:
        """Handle the scan phase completing (files counted)."""
        self._progress_view.reset(total_files)
        self.update_status(f"Processing {total_files} audio files...")

    def _on_progress_updated(
        self, current: int, total: int, filename: str, status: str
    ) -> None:
        """Handle progress updates from the worker."""
        self._progress_view.update_progress(current, total, filename, status)
        self.update_status(f"[{current}/{total}] {filename} - {status}")

    def _on_stats_updated(
        self,
        processed: int,
        auto_matched: int,
        needs_review: int,
        unmatched: int,
        errors: int,
    ) -> None:
        """Handle stats updates from the worker."""
        self._progress_view.update_stats(
            processed, auto_matched, needs_review, unmatched, errors
        )

    def _on_processing_finished(self, result: BatchResult) -> None:
        """Handle the batch processing completing.

        If this was a dry-run (preview), routes to the Preview view.
        Otherwise populates the Review/Library views as before.
        """
        self._last_result = result
        stats = result.stats

        self.update_status(
            f"Done! {stats.auto_matched} auto-matched, "
            f"{stats.needs_review} need review, "
            f"{stats.unmatched} unmatched, "
            f"{stats.errors} errors"
        )

        # Update final stats on progress view
        self._progress_view.update_stats(
            stats.processed,
            stats.auto_matched,
            stats.needs_review,
            stats.unmatched,
            stats.errors,
        )

        # --- Dry-run: route to Preview Report ---
        if self._dry_run_pending:
            self._dry_run_pending = False
            self._preview_view.set_preview_data(result)
            self._switch_view(2)  # Preview
            self._show_toast(
                f"Preview complete -- {stats.auto_matched} auto-matched, "
                f"{stats.needs_review} need review, "
                f"{stats.unmatched} unmatched, "
                f"{stats.errors} errors. "
                f"Approve the artists you want to process."
            )
            return

        # --- Normal scan: route to Review / Library ---
        # Populate review view with tracks that need user action
        # (NEEDS_REVIEW = has candidates, UNMATCHED = no candidates found)
        review_items = []
        for track in result.tracks:
            if track.state.needs_user_action():
                match_key = str(track.file_path)
                match_result = result.match_results.get(match_key)
                if match_result:
                    review_items.append((track, match_result))

        if review_items:
            self._review_view.set_review_items(review_items)

        # Populate library view with all completed tracks
        completed_tracks = [
            t for t in result.tracks
            if t.state in (ProcessingState.COMPLETED, ProcessingState.AUTO_MATCHED)
        ]
        self._library_view.set_tracks(completed_tracks)

        # Refresh the import view's retry banner
        self._import_view.refresh_retry_banner()

        # Auto-navigate: go to Review if there are items, otherwise Library
        if review_items:
            self._switch_view(3)  # Review
            self._show_toast(
                f"Processing complete -- {stats.auto_matched} auto-matched, "
                f"{stats.needs_review} need review, "
                f"{stats.unmatched} unmatched, "
                f"{stats.errors} errors. "
                f"Please review the uncertain matches."
            )
        else:
            self._switch_view(4)  # Library
            self._show_toast(
                f"All done! {stats.auto_matched} auto-matched, "
                f"{stats.unmatched} unmatched, "
                f"{stats.errors} errors. "
                f"Your library has been organized."
            )

    def _on_worker_error(self, error_message: str) -> None:
        """Handle an error from the worker thread."""
        logger.error("Worker error: %s", error_message)
        self.update_status(f"Error: {error_message}")
        QMessageBox.critical(self, "Processing Error", error_message)
        self._switch_view(0)  # Return to Import view

    def _on_thread_finished(self) -> None:
        """Clean up after the worker thread finishes."""
        logger.debug("Worker thread finished, cleaning up")
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._worker_thread:
            self._worker_thread.deleteLater()
            self._worker_thread = None

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close: cancel any running worker and wait briefly.

        Without this, closing the window while fingerprinting is in progress
        leaves ThreadPoolExecutor threads alive, blocking Python's shutdown
        and forcing the user to kill the process manually.
        """
        # Cancel the main processing worker
        if self._worker:
            self._worker.cancel()

        # Give the worker thread a moment to finish cleanly
        if self._worker_thread and self._worker_thread.isRunning():
            logger.info("Waiting for worker thread to finish...")
            if not self._worker_thread.wait(3000):  # 3 second timeout
                logger.warning("Worker thread did not finish in time, terminating")
                self._worker_thread.terminate()
                self._worker_thread.wait(1000)

        # Also clean up any other running threads
        for thread in (
            self._review_thread,
            self._preview_apply_thread,
            self._search_thread,
        ):
            if thread and thread.isRunning():
                thread.quit()
                if not thread.wait(2000):
                    thread.terminate()

        logger.info("Application closing")
        super().closeEvent(event)

    def _on_pause(self) -> None:
        """Handle pause request from progress view."""
        if self._worker:
            self._worker.pause()
            self.update_status("Paused")

    def _on_resume(self) -> None:
        """Handle resume request from progress view."""
        if self._worker:
            self._worker.resume()
            self.update_status("Resumed")

    def _on_cancel(self) -> None:
        """Handle cancel request from progress view."""
        if self._worker:
            self._worker.cancel()
            self.update_status("Cancelling...")

    # --- Preview Apply Handlers ---

    def _on_preview_apply(
        self,
        auto_tracks: list,
        review_items: list,
        batch_result: BatchResult,
    ) -> None:
        """Handle 'Apply Approved' from the Preview view.

        Launches PreviewApplyWorker for auto-matched tracks and
        routes needs-review tracks to the Review view.

        Args:
            auto_tracks: Tracks ready to apply (auto-matched 90%+).
            review_items: (Track, MatchResult) tuples needing candidate selection.
            batch_result: The original BatchResult (for match_results lookup).
        """
        if self._preview_apply_thread and self._preview_apply_thread.isRunning():
            QMessageBox.warning(
                self,
                "Apply In Progress",
                "A previous apply is still running. Please wait.",
            )
            return

        # Route needs-review tracks to the Review view
        if review_items:
            self._review_view.set_review_items(review_items)

        if auto_tracks:
            logger.info(
                "Preview apply: %d auto-matched, %d need review",
                len(auto_tracks), len(review_items),
            )
            self.update_status(f"Applying {len(auto_tracks)} approved tracks...")

            self._preview_apply_thread = QThread()
            self._preview_apply_worker = PreviewApplyWorker(
                auto_tracks,
                batch_result.match_results,
                self._config,
            )
            self._preview_apply_worker.moveToThread(self._preview_apply_thread)

            self._preview_apply_thread.started.connect(
                self._preview_apply_worker.run
            )
            self._preview_apply_worker.progress_updated.connect(
                self._on_preview_apply_progress
            )
            self._preview_apply_worker.finished.connect(
                lambda applied, dups, errs: self._on_preview_apply_finished(
                    applied, dups, errs, review_items,
                )
            )
            self._preview_apply_worker.error_occurred.connect(
                self._on_preview_apply_error
            )

            self._preview_apply_worker.finished.connect(
                self._preview_apply_thread.quit
            )
            self._preview_apply_worker.error_occurred.connect(
                self._preview_apply_thread.quit
            )
            self._preview_apply_thread.finished.connect(
                self._on_preview_apply_thread_finished
            )

            self._preview_apply_thread.start()
        elif review_items:
            # No auto tracks, go straight to review
            self._switch_view(3)  # Review
            self._show_toast(
                f"{len(review_items)} tracks need your review. "
                f"Select the correct match for each track."
            )

    def _on_preview_apply_progress(
        self, current: int, total: int, filename: str, status: str,
    ) -> None:
        """Handle progress from the preview apply worker."""
        self.update_status(f"[{current}/{total}] {filename} -- {status}")

    def _on_preview_apply_finished(
        self,
        applied: int,
        duplicates: int,
        errors: int,
        review_items: list,
    ) -> None:
        """Handle preview apply completion.

        Args:
            applied: Successfully applied tracks.
            duplicates: Duplicate tracks skipped.
            errors: Failed tracks.
            review_items: Tracks that still need review.
        """
        self._preview_view.on_apply_finished(applied, duplicates, errors)

        # Refresh library view with completed tracks
        if self._last_result:
            completed = [
                t for t in self._last_result.tracks
                if t.state in (ProcessingState.COMPLETED, ProcessingState.AUTO_MATCHED)
            ]
            self._library_view.set_tracks(completed)

        parts = []
        if applied:
            parts.append(f"{applied} applied")
        if duplicates:
            parts.append(f"{duplicates} duplicates skipped")
        if errors:
            parts.append(f"{errors} errors")
        summary = ", ".join(parts) or "Nothing to apply"

        self.update_status(f"Done: {summary}")

        # Navigate: to Review if there are items, otherwise Library
        if review_items:
            self._switch_view(3)  # Review
            self._show_toast(
                f"Applied {applied} tracks. "
                f"{len(review_items)} tracks need your review.",
            )
        else:
            self._switch_view(4)  # Library
            self._show_toast(f"All done! {summary}.")

        self._import_view.refresh_retry_banner()

    def _on_preview_apply_error(self, error_message: str) -> None:
        """Handle a fatal error from the preview apply worker."""
        logger.error("Preview apply error: %s", error_message)
        self.update_status(f"Error: {error_message}")
        self._preview_view.on_apply_finished(0, 0, 0)
        QMessageBox.critical(self, "Apply Error", error_message)

    def _on_preview_apply_thread_finished(self) -> None:
        """Clean up after the preview apply thread finishes."""
        if self._preview_apply_worker:
            self._preview_apply_worker.deleteLater()
            self._preview_apply_worker = None
        if self._preview_apply_thread:
            self._preview_apply_thread.deleteLater()
            self._preview_apply_thread = None

    # --- Review Handlers ---

    def _on_batch_apply(self, selections: list) -> None:
        """Handle batch apply from the review view.

        Launches a background thread to apply all selected matches without
        blocking the UI.

        Args:
            selections: List of (Track, MatchCandidate) tuples.
        """
        if self._review_thread and self._review_thread.isRunning():
            QMessageBox.warning(
                self,
                "Apply In Progress",
                "Matches are already being applied. Please wait.",
            )
            return

        logger.info("Batch applying %d review selections", len(selections))
        self.update_status(f"Applying {len(selections)} matches...")

        # Create worker and thread
        self._review_thread = QThread()
        self._review_worker = ReviewApplyWorker(selections, self._config)
        self._review_worker.moveToThread(self._review_thread)

        # Connect signals
        self._review_thread.started.connect(self._review_worker.run)
        self._review_worker.progress_updated.connect(self._on_review_progress)
        self._review_worker.finished.connect(self._on_review_apply_finished)
        self._review_worker.error_occurred.connect(self._on_review_apply_error)

        # Clean up
        self._review_worker.finished.connect(self._review_thread.quit)
        self._review_worker.error_occurred.connect(self._review_thread.quit)
        self._review_thread.finished.connect(self._on_review_thread_finished)

        self._review_thread.start()

    def _on_review_progress(
        self, current: int, total: int, filename: str, status: str
    ) -> None:
        """Handle progress from the review apply worker."""
        self.update_status(f"[{current}/{total}] {filename} -- {status}")

    def _on_review_apply_finished(
        self, applied: int, duplicates: int, errors: int
    ) -> None:
        """Handle batch apply completion.

        Args:
            applied: Successfully applied matches.
            duplicates: Skipped duplicates.
            errors: Failed matches.
        """
        # Tell the review view to clean up decided cards
        self._review_view.on_batch_apply_finished(applied, duplicates, errors)

        # Refresh library view
        if self._last_result:
            completed = [
                t for t in self._last_result.tracks
                if t.state in (ProcessingState.COMPLETED, ProcessingState.AUTO_MATCHED)
            ]
            self._library_view.set_tracks(completed)

        # Build status message
        parts = []
        if applied:
            parts.append(f"{applied} applied")
        if duplicates:
            parts.append(f"{duplicates} duplicates skipped")
        if errors:
            parts.append(f"{errors} errors")
        summary = ", ".join(parts) or "Nothing to apply"

        self.update_status(f"Done: {summary}")

        self._show_toast(
            f"Batch apply finished -- {summary}.",
        )

    def _on_review_apply_error(self, error_message: str) -> None:
        """Handle a fatal error from the review apply worker."""
        logger.error("Review apply error: %s", error_message)
        self.update_status(f"Error: {error_message}")
        self._review_view.on_batch_apply_finished(0, 0, 0)
        QMessageBox.critical(self, "Apply Error", error_message)

    def _on_review_thread_finished(self) -> None:
        """Clean up after the review apply thread finishes."""
        if self._review_worker:
            self._review_worker.deleteLater()
            self._review_worker = None
        if self._review_thread:
            self._review_thread.deleteLater()
            self._review_thread = None

    def _on_track_skipped(self, track: Track) -> None:
        """Handle a track being skipped in review."""
        track.state = ProcessingState.SKIPPED
        self.update_status(f"Skipped: {track.file_path.name}")

    def _on_manual_search(
        self, track: Track, title: str, artist: str, album: str = "", source: str = "all",
    ) -> None:
        """Handle a manual search request from the review view.

        Launches a background thread to search the selected API source(s).

        Args:
            track: The track that needs results.
            title: Title search term.
            artist: Artist search term.
            album: Album search term.
            source: Which API to query -- "all", "musicbrainz", or "discogs".
        """
        # If a search is already running, detach the old thread and let it
        # finish in the background without crashing.  We disconnect its
        # signals so stale results are silently discarded.
        if self._search_thread and self._search_thread.isRunning():
            logger.debug("Previous search thread still running -- detaching")
            try:
                self._search_worker.results_ready.disconnect()
                self._search_worker.error_occurred.disconnect()
            except (TypeError, RuntimeError):
                pass
            # Let the old thread clean itself up when it finishes naturally
            old_thread = self._search_thread
            old_worker = self._search_worker
            old_thread.finished.connect(old_worker.deleteLater)
            old_thread.finished.connect(old_thread.deleteLater)
            self._search_thread = None
            self._search_worker = None

        track_id = id(track)
        logger.info(
            "Manual search: title='%s', artist='%s', album='%s', source='%s'",
            title, artist, album, source,
        )
        self.update_status(f"Searching: {title} / {artist}...")

        self._search_thread = QThread()
        self._search_worker = ManualSearchWorker(
            track_id, title, artist, self._config,
            album=album, source=source,
        )
        self._search_worker.moveToThread(self._search_thread)

        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.results_ready.connect(self._on_manual_search_results)
        self._search_worker.error_occurred.connect(self._on_manual_search_error)

        self._search_worker.results_ready.connect(self._search_thread.quit)
        self._search_worker.error_occurred.connect(self._search_thread.quit)
        self._search_thread.finished.connect(self._on_search_thread_finished)

        self._search_thread.start()

    def _on_manual_search_results(self, track_id: int, candidates: list) -> None:
        """Route manual search results to the review view."""
        count = len(candidates)
        self.update_status(f"Search complete: {count} result{'s' if count != 1 else ''}")
        self._review_view.on_manual_search_results(track_id, candidates)

    def _on_manual_search_error(self, error_message: str) -> None:
        """Handle a manual search error."""
        logger.error("Manual search error: %s", error_message)
        self.update_status(f"Search failed: {error_message}")

    def _on_search_thread_finished(self) -> None:
        """Clean up after the manual search thread finishes."""
        if self._search_worker:
            self._search_worker.deleteLater()
            self._search_worker = None
        if self._search_thread:
            self._search_thread.deleteLater()
            self._search_thread = None

    def _on_settings_changed(self, new_config: dict) -> None:
        """Handle settings changes -- update config and re-apply theme."""
        self._config.update(new_config)
        self._apply_theme()
        self.update_status("Settings saved")


# Theme stylesheets are now generated from palette classes in
# src/gui/styles/theme.py -- see get_dark_theme_qss() / get_light_theme_qss().

"""Scan progress view -- shows real-time progress during batch processing."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.logger import get_logger

logger = get_logger("gui.scan_progress_view")


class ScanProgressView(QWidget):
    """Displays real-time progress of the scanning/matching pipeline.

    Shows:
    - Overall progress bar
    - Per-file status list with icons
    - Live stats counters
    - Pause/Resume and Cancel buttons

    Signals:
        pause_requested: User clicked pause.
        resume_requested: User clicked resume.
        cancel_requested: User clicked cancel.
    """

    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._is_paused = False
        self._start_time: float | None = None
        self._pause_start: float | None = None
        self._total_paused: float = 0.0

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the progress view layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(16)

        # Title
        title = QLabel("Processing")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Overall progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

        # Progress text label (outside the bar for readability)
        self._progress_text = QLabel("0 / 0 files (0%)")
        self._progress_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_text.setObjectName("progressText")
        layout.addWidget(self._progress_text)

        # Current file label
        self._current_label = QLabel("Waiting to start...")
        self._current_label.setObjectName("currentFileLabel")
        layout.addWidget(self._current_label)

        # ETA / elapsed label
        self._eta_label = QLabel("")
        self._eta_label.setObjectName("etaLabel")
        self._eta_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self._eta_label)

        # Stats row
        stats_frame = QFrame()
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setSpacing(24)

        self._stat_labels = {}
        for name, label_text in [
            ("processed", "Processed"),
            ("auto_matched", "Auto-Matched"),
            ("needs_review", "Needs Review"),
            ("unmatched", "Unmatched"),
            ("errors", "Errors"),
        ]:
            stat_widget = QVBoxLayout()
            count_label = QLabel("0")
            count_font = QFont()
            count_font.setPointSize(20)
            count_font.setBold(True)
            count_label.setFont(count_font)
            count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._stat_labels[name] = count_label

            desc_label = QLabel(label_text)
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setObjectName("statDesc")

            stat_widget.addWidget(count_label)
            stat_widget.addWidget(desc_label)
            stats_layout.addLayout(stat_widget)

        layout.addWidget(stats_frame)

        # File list
        self._file_list = QListWidget()
        self._file_list.setAlternatingRowColors(True)
        layout.addWidget(self._file_list)

        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.clicked.connect(self._on_pause_resume)
        btn_layout.addWidget(self._pause_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

    def reset(self, total: int) -> None:
        """Reset the view for a new processing run.

        Args:
            total: Total number of files to process.
        """
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_text.setText(f"0 / {total} files (0%)")
        self._current_label.setText("Starting...")
        self._eta_label.setText("")
        self._file_list.clear()
        self._is_paused = False
        self._pause_btn.setText("Pause")
        self._cancel_btn.setEnabled(True)
        self._start_time = time.monotonic()
        self._total_paused = 0.0
        self._pause_start = None

        for label in self._stat_labels.values():
            label.setText("0")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration in seconds to a human-readable string."""
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}s"
        minutes, secs = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {secs:02d}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m"

    @pyqtSlot(int, int, str, str)
    def update_progress(self, current: int, total: int, filename: str, status: str) -> None:
        """Update the progress display.

        Args:
            current: Current file number.
            total: Total files.
            filename: Name of the file being processed.
            status: Current status message.
        """
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        percent = int((current / total) * 100) if total > 0 else 0
        self._progress_text.setText(f"{current} / {total} files ({percent}%)")

        self._current_label.setText(f"{filename} — {status}")

        # Calculate ETA
        if self._start_time and current > 0 and total > 0:
            elapsed = time.monotonic() - self._start_time - self._total_paused
            rate = elapsed / current  # seconds per track
            remaining = rate * (total - current)
            elapsed_str = self._format_duration(elapsed)
            if current < total:
                eta_str = self._format_duration(remaining)
                self._eta_label.setText(
                    f"Elapsed: {elapsed_str}  |  ~{eta_str} remaining  |  {rate:.1f}s per track"
                )
            else:
                self._eta_label.setText(f"Completed in {elapsed_str}")

        # Add to file list
        item = QListWidgetItem(f"  {filename} — {status}")
        self._file_list.addItem(item)
        self._file_list.scrollToBottom()

    def update_stats(
        self,
        processed: int = 0,
        auto_matched: int = 0,
        needs_review: int = 0,
        unmatched: int = 0,
        errors: int = 0,
    ) -> None:
        """Update the stat counters.

        Args:
            processed: Total processed.
            auto_matched: Auto-matched count.
            needs_review: Needs review count.
            unmatched: Unmatched count.
            errors: Error count.
        """
        self._stat_labels["processed"].setText(str(processed))
        self._stat_labels["auto_matched"].setText(str(auto_matched))
        self._stat_labels["needs_review"].setText(str(needs_review))
        self._stat_labels["unmatched"].setText(str(unmatched))
        self._stat_labels["errors"].setText(str(errors))

    def _on_pause_resume(self) -> None:
        """Toggle pause/resume."""
        if self._is_paused:
            self._is_paused = False
            self._pause_btn.setText("Pause")
            self._current_label.setText("Resuming...")
            # Account for time spent paused so ETA stays accurate
            if self._pause_start is not None:
                self._total_paused += time.monotonic() - self._pause_start
                self._pause_start = None
            self.resume_requested.emit()
        else:
            self._is_paused = True
            self._pause_btn.setText("Resume")
            self._current_label.setText("Paused")
            self._pause_start = time.monotonic()
            self.pause_requested.emit()

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        self._current_label.setText("Cancelling...")
        self._cancel_btn.setEnabled(False)
        self.cancel_requested.emit()

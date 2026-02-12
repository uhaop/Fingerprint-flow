"""Import view -- drag-and-drop zone and folder picker for importing music files."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.logger import get_logger

logger = get_logger("gui.import_view")


class DropZone(QFrame):
    """Large drag-and-drop area for importing music files/folders."""

    files_dropped = pyqtSignal(list)  # Emits list of file/folder paths

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icon placeholder
        icon_label = QLabel("♫")
        icon_label.setObjectName("dropIcon")
        icon_font = QFont()
        icon_font.setPointSize(48)
        icon_label.setFont(icon_font)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Main text
        main_label = QLabel("Drag & Drop Music Files or Folders Here")
        main_label.setObjectName("dropMainLabel")
        main_font = QFont()
        main_font.setPointSize(16)
        main_font.setBold(True)
        main_label.setFont(main_font)
        main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(main_label)

        # Subtitle
        sub_label = QLabel("Supports MP3, FLAC, M4A, OGG, WAV, AIFF, and more")
        sub_label.setObjectName("dropSubLabel")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub_label)

        self._update_style(False)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drag events that contain file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._update_style(True)

    def dragLeaveEvent(self, event: object) -> None:
        """Reset style when drag leaves the zone."""
        self._update_style(False)

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle dropped files/folders."""
        self._update_style(False)
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                paths.append(path)

        if paths:
            logger.info("Files dropped: %d paths", len(paths))
            self.files_dropped.emit(paths)

    def _update_style(self, is_hovering: bool) -> None:
        """Update the drop zone border style via dynamic property.

        The actual colors come from the global theme QSS which defines
        ``#dropZone`` and ``#dropZone[hovering="true"]`` selectors.
        """
        self.setProperty("hovering", str(is_hovering).lower())
        self.style().unpolish(self)
        self.style().polish(self)


class ImportView(QWidget):
    """Import view with drag-and-drop zone and folder picker button.

    Signals:
        scan_requested: Emitted when the user wants to start scanning
            directly (Scan & Apply).  Carries a list of file/folder
            path strings.
        preview_requested: Emitted when the user wants to preview
            changes before applying (dry-run mode).  Carries a list
            of file/folder path strings.
    """

    scan_requested = pyqtSignal(list)
    preview_requested = pyqtSignal(list)

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._selected_paths: list[str] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the import view layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Import Music")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("Add files or folders to scan and organize your music library.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        # --- Retry Unmatched banner (shown if a previous report exists) ---
        self._retry_frame = QFrame()
        self._retry_frame.setObjectName("retryBanner")
        retry_layout = QHBoxLayout(self._retry_frame)
        retry_layout.setContentsMargins(16, 10, 16, 10)
        retry_layout.setSpacing(12)

        self._retry_info = QLabel("")
        self._retry_info.setObjectName("retryInfoLabel")
        retry_layout.addWidget(self._retry_info)

        retry_layout.addStretch()

        self._retry_btn = QPushButton("Retry Unmatched")
        self._retry_btn.setObjectName("primaryButton")
        self._retry_btn.clicked.connect(self._on_retry_unmatched)
        retry_layout.addWidget(self._retry_btn)

        self._retry_frame.setVisible(False)
        layout.addWidget(self._retry_frame)

        self._check_for_unmatched_report()

        # Drop zone
        self._drop_zone = DropZone()
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        layout.addWidget(self._drop_zone)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._choose_folder_btn = QPushButton("Choose Folder")
        self._choose_folder_btn.clicked.connect(self._on_choose_folder)
        btn_layout.addWidget(self._choose_folder_btn)

        self._choose_files_btn = QPushButton("Choose Files")
        self._choose_files_btn.clicked.connect(self._on_choose_files)
        btn_layout.addWidget(self._choose_files_btn)

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setObjectName("clearButton")
        self._clear_btn.clicked.connect(self._on_clear_all)
        self._clear_btn.setVisible(False)
        btn_layout.addWidget(self._clear_btn)

        btn_layout.addStretch()

        self._scan_btn = QPushButton("Scan && Apply")
        self._scan_btn.setToolTip(
            "Skip preview and apply changes directly (high-confidence matches auto-applied)"
        )
        self._scan_btn.setEnabled(False)
        self._scan_btn.clicked.connect(self._on_start_scan)
        btn_layout.addWidget(self._scan_btn)

        self._preview_btn = QPushButton("Preview Changes")
        self._preview_btn.setObjectName("primaryButton")
        self._preview_btn.setToolTip(
            "Scan and show a full preview report before changing any files"
        )
        self._preview_btn.setEnabled(False)
        self._preview_btn.clicked.connect(self._on_preview)
        btn_layout.addWidget(self._preview_btn)

        layout.addLayout(btn_layout)

        # --- Selected items list ---
        self._file_list_label = QLabel("")
        self._file_list_label.setObjectName("infoLabel")
        layout.addWidget(self._file_list_label)

        # Scrollable list of selected paths
        self._file_list_scroll = QScrollArea()
        self._file_list_scroll.setWidgetResizable(True)
        self._file_list_scroll.setMaximumHeight(200)
        self._file_list_scroll.setVisible(False)
        self._file_list_scroll.setObjectName("fileListScroll")

        self._file_list_container = QWidget()
        self._file_list_layout = QVBoxLayout(self._file_list_container)
        self._file_list_layout.setContentsMargins(8, 8, 8, 8)
        self._file_list_layout.setSpacing(4)
        self._file_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._file_list_scroll.setWidget(self._file_list_container)

        layout.addWidget(self._file_list_scroll)

        layout.addStretch()

    def _on_files_dropped(self, paths: list) -> None:
        """Handle files/folders dropped onto the drop zone.

        Appends to existing selection rather than replacing it,
        so users can drop multiple batches.
        """
        # Add new paths, avoiding duplicates
        existing = set(self._selected_paths)
        for p in paths:
            if p not in existing:
                self._selected_paths.append(p)
                existing.add(p)
        self._rebuild_file_list()

    def _on_choose_folder(self) -> None:
        """Open a folder picker dialog."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Music Folder",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder and folder not in self._selected_paths:
            self._selected_paths.append(folder)
            self._rebuild_file_list()

    def _on_choose_files(self) -> None:
        """Open a file picker dialog."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Music Files",
            "",
            "Audio Files (*.mp3 *.flac *.m4a *.aac *.ogg *.opus *.wma *.aiff *.aif *.wav *.ape *.wv);;All Files (*)",
        )
        if files:
            existing = set(self._selected_paths)
            for f in files:
                if f not in existing:
                    self._selected_paths.append(f)
                    existing.add(f)
            self._rebuild_file_list()

    def _on_clear_all(self) -> None:
        """Remove all selected paths."""
        self._selected_paths.clear()
        self._rebuild_file_list()

    def _on_remove_path(self, path: str) -> None:
        """Remove a single path from the selection."""
        if path in self._selected_paths:
            self._selected_paths.remove(path)
            self._rebuild_file_list()

    def _on_preview(self) -> None:
        """Emit the preview_requested signal for a dry-run scan."""
        if self._selected_paths:
            logger.info("Preview requested for %d paths", len(self._selected_paths))
            self.preview_requested.emit(self._selected_paths)

    def _on_start_scan(self) -> None:
        """Emit the scan_requested signal after user confirms.

        Shows an 'Are you sure?' dialog because this path skips the
        preview and directly applies high-confidence changes.
        """
        if not self._selected_paths:
            return

        reply = QMessageBox.warning(
            self,
            "Scan && Apply Directly",
            "This will skip the preview and directly modify your files.\n\n"
            "High-confidence matches will be auto-applied (tags written, "
            "files moved). Are you sure you want to continue?\n\n"
            "Tip: Use 'Preview Changes' to review everything first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            logger.info("Scan & Apply requested for %d paths", len(self._selected_paths))
            self.scan_requested.emit(self._selected_paths)

    def _check_for_unmatched_report(self) -> None:
        """Check if a previous unmatched report exists and show the retry banner."""
        library_path = self._config.get("library_path", "")
        if not library_path:
            return

        report_path = Path(library_path) / "_unmatched_report.json"
        if not report_path.exists():
            self._retry_frame.setVisible(False)
            return

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            unmatched_count = len(data.get("unmatched", []))
            error_count = len(data.get("errors", []))
            total_retry = unmatched_count + error_count
            generated = data.get("generated_at", "unknown time")

            if total_retry > 0:
                # Count how many files still exist
                existing = 0
                for entry in data.get("unmatched", []) + data.get("errors", []):
                    if Path(entry["file_path"]).exists():
                        existing += 1

                if existing > 0:
                    self._retry_info.setText(
                        f"Previous scan found {existing} unmatched file{'s' if existing != 1 else ''} "
                        f"(from {generated})"
                    )
                    self._retry_frame.setVisible(True)
                    self._retry_report_path = report_path
                else:
                    self._retry_frame.setVisible(False)
            else:
                self._retry_frame.setVisible(False)
        except Exception as e:
            logger.debug("Could not read unmatched report: %s", e)
            self._retry_frame.setVisible(False)

    def _on_retry_unmatched(self) -> None:
        """Load unmatched file paths from the report and trigger a scan."""
        if not hasattr(self, "_retry_report_path"):
            return

        try:
            data = json.loads(self._retry_report_path.read_text(encoding="utf-8"))
            retry_paths = []

            for entry in data.get("unmatched", []) + data.get("errors", []):
                path = Path(entry["file_path"])
                if path.exists():
                    retry_paths.append(str(path))

            if retry_paths:
                logger.info("Retrying %d unmatched files from previous report", len(retry_paths))
                self._selected_paths = retry_paths
                self._rebuild_file_list()
                self.scan_requested.emit(retry_paths)
            else:
                logger.info("No retryable files found (all moved or deleted)")
                self._retry_frame.setVisible(False)
        except Exception as e:
            logger.error("Failed to load retry report: %s", e)

    def refresh_retry_banner(self) -> None:
        """Re-check for unmatched report (call after processing finishes)."""
        self._check_for_unmatched_report()

    def _rebuild_file_list(self) -> None:
        """Rebuild the visual list of selected paths and update controls."""
        # Clear existing list items
        while self._file_list_layout.count():
            child = self._file_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        count = len(self._selected_paths)

        # Update header label
        if count == 0:
            self._file_list_label.setText("")
            self._file_list_scroll.setVisible(False)
            self._clear_btn.setVisible(False)
        else:
            folders = sum(1 for p in self._selected_paths if Path(p).is_dir())
            files = count - folders
            parts = []
            if folders:
                parts.append(f"{folders} folder{'s' if folders != 1 else ''}")
            if files:
                parts.append(f"{files} file{'s' if files != 1 else ''}")
            self._file_list_label.setText(f"Selected: {', '.join(parts)}")
            self._file_list_scroll.setVisible(True)
            self._clear_btn.setVisible(True)

        # Add a row for each selected path
        for path_str in self._selected_paths:
            path = Path(path_str)
            row = QFrame()
            row.setObjectName("fileListRow")

            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 6, 6)
            row_layout.setSpacing(8)

            # Icon
            icon = "📁" if path.is_dir() else "🎵"
            icon_lbl = QLabel(icon)
            icon_lbl.setFixedWidth(24)
            row_layout.addWidget(icon_lbl)

            # Path name and full path
            name_lbl = QLabel(path.name)
            name_font = QFont()
            name_font.setPointSize(10)
            name_font.setBold(True)
            name_lbl.setFont(name_font)
            name_lbl.setObjectName("fileListName")
            row_layout.addWidget(name_lbl)

            # Show parent path as subdued text
            parent_lbl = QLabel(str(path.parent))
            parent_lbl.setObjectName("fileListPath")
            parent_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row_layout.addWidget(parent_lbl)

            # Remove button
            remove_btn = QPushButton("✕")
            remove_btn.setFixedSize(24, 24)
            remove_btn.setObjectName("fileListRemoveBtn")
            # Capture path_str in closure
            remove_btn.clicked.connect(lambda checked, p=path_str: self._on_remove_path(p))
            row_layout.addWidget(remove_btn)

            self._file_list_layout.addWidget(row)

        self._scan_btn.setEnabled(count > 0)
        self._preview_btn.setEnabled(count > 0)

"""Settings view -- configuration UI for Fingerprint Flow."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.utils.constants import (
    DEFAULT_AUTO_APPLY_THRESHOLD,
    DEFAULT_REVIEW_THRESHOLD,
)
from src.utils.logger import get_logger

logger = get_logger("gui.settings_view")


class SettingsView(QWidget):
    """Configuration UI for all Fingerprint Flow settings.

    Groups:
    - Output: library path, backup path, keep originals
    - Naming: folder template, file template
    - Confidence: threshold sliders
    - API Keys: AcoustID, Discogs
    - Appearance: theme selection

    Signals:
        settings_changed: Emitted when any setting is changed. (config dict)
    """

    settings_changed = pyqtSignal(dict)

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config

        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self) -> None:
        """Build the settings view layout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area so settings never get compressed
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Settings")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # --- Output Group ---
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        output_layout.setSpacing(8)

        # Library path row
        lib_row = QHBoxLayout()
        lib_label = QLabel("Library Path:")
        lib_label.setFixedWidth(90)
        lib_row.addWidget(lib_label)
        self._library_path_edit = QLineEdit()
        self._library_path_edit.setMinimumWidth(300)
        self._library_path_edit.setMinimumHeight(36)
        lib_row.addWidget(self._library_path_edit, 1)
        library_browse_btn = QPushButton("Browse...")
        library_browse_btn.setFixedWidth(100)
        library_browse_btn.clicked.connect(self._browse_library_path)
        lib_row.addWidget(library_browse_btn)
        output_layout.addLayout(lib_row)

        # Backup path row
        bak_row = QHBoxLayout()
        bak_label = QLabel("Backup Path:")
        bak_label.setFixedWidth(90)
        bak_row.addWidget(bak_label)
        self._backup_path_edit = QLineEdit()
        self._backup_path_edit.setMinimumWidth(300)
        self._backup_path_edit.setMinimumHeight(36)
        bak_row.addWidget(self._backup_path_edit, 1)
        backup_browse_btn = QPushButton("Browse...")
        backup_browse_btn.setFixedWidth(100)
        backup_browse_btn.clicked.connect(self._browse_backup_path)
        bak_row.addWidget(backup_browse_btn)
        output_layout.addLayout(bak_row)

        self._keep_originals_cb = QCheckBox("Keep backup copies of original files")
        keep_row = QHBoxLayout()
        keep_row.addSpacing(94)  # align with fields above
        keep_row.addWidget(self._keep_originals_cb)
        output_layout.addLayout(keep_row)

        layout.addWidget(output_group)

        # --- Naming Group ---
        naming_group = QGroupBox("File Organization")
        naming_layout = QFormLayout(naming_group)

        self._folder_template_edit = QLineEdit()
        self._folder_template_edit.setPlaceholderText("{artist}/{album} ({year})")
        self._folder_template_edit.textChanged.connect(self._update_template_preview)
        naming_layout.addRow("Folder Template:", self._folder_template_edit)

        self._file_template_edit = QLineEdit()
        self._file_template_edit.setPlaceholderText("{track:02d} - {title}")
        self._file_template_edit.textChanged.connect(self._update_template_preview)
        naming_layout.addRow("File Template:", self._file_template_edit)

        template_help = QLabel(
            "Variables: {artist}, {album}, {year}, {disc}, {track}, {title}\n"
            "Multi-disc albums automatically get a Disc N subfolder."
        )
        template_help.setWordWrap(True)
        template_help.setStyleSheet("font-size: 10px; color: #888; padding: 2px 0;")
        naming_layout.addRow("", template_help)

        self._move_unmatched_cb = QCheckBox("Move unmatched files to a separate folder")
        self._move_unmatched_cb.setToolTip(
            "When unchecked (recommended), files that can't be identified stay\n"
            "in their original location so you don't lose existing folder structure.\n"
            "When checked, they are moved to the _Unmatched folder."
        )
        naming_layout.addRow("", self._move_unmatched_cb)

        self._template_preview = QLabel("")
        self._template_preview.setWordWrap(True)
        self._template_preview.setStyleSheet("font-size: 11px; padding: 4px 0;")
        naming_layout.addRow("Preview:", self._template_preview)

        layout.addWidget(naming_group)

        # --- Confidence Group ---
        confidence_group = QGroupBox("Confidence Thresholds")
        confidence_layout = QFormLayout(confidence_group)

        self._auto_slider = QSlider(Qt.Orientation.Horizontal)
        self._auto_slider.setRange(50, 100)
        self._auto_slider.setValue(DEFAULT_AUTO_APPLY_THRESHOLD)
        self._auto_label = QLabel(f"{DEFAULT_AUTO_APPLY_THRESHOLD}%")
        self._auto_slider.valueChanged.connect(self._on_auto_threshold_changed)
        auto_row = QHBoxLayout()
        auto_row.addWidget(self._auto_slider)
        auto_row.addWidget(self._auto_label)
        confidence_layout.addRow("Auto-Apply Above:", auto_row)

        self._review_slider = QSlider(Qt.Orientation.Horizontal)
        self._review_slider.setRange(30, 100)
        self._review_slider.setValue(DEFAULT_REVIEW_THRESHOLD)
        self._review_label = QLabel(f"{DEFAULT_REVIEW_THRESHOLD}%")
        self._review_slider.valueChanged.connect(self._on_review_threshold_changed)
        review_row = QHBoxLayout()
        review_row.addWidget(self._review_slider)
        review_row.addWidget(self._review_label)
        confidence_layout.addRow("Review Above:", review_row)

        layout.addWidget(confidence_group)

        # --- API Keys Group ---
        api_group = QGroupBox("API Keys")
        api_layout = QFormLayout(api_group)

        self._acoustid_edit = QLineEdit()
        self._acoustid_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._acoustid_edit.setPlaceholderText("Enter your AcoustID API key")
        api_layout.addRow("AcoustID Key:", self._acoustid_edit)

        self._discogs_edit = QLineEdit()
        self._discogs_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._discogs_edit.setPlaceholderText("Enter your Discogs token")
        api_layout.addRow("Discogs Token:", self._discogs_edit)

        layout.addWidget(api_group)

        # --- Appearance Group ---
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance_group)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        appearance_layout.addRow("Theme:", self._theme_combo)

        layout.addWidget(appearance_group)

        # --- Save Button ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._save_btn = QPushButton("Save Settings")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self._save_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)

    def _load_from_config(self) -> None:
        """Populate UI fields from the current config dictionary."""
        self._library_path_edit.setText(self._config.get("library_path", ""))
        self._backup_path_edit.setText(self._config.get("backup_path", ""))
        self._keep_originals_cb.setChecked(self._config.get("keep_originals", True))
        self._folder_template_edit.setText(
            self._config.get("folder_template", "{artist}/{album} ({year})")
        )
        self._file_template_edit.setText(self._config.get("file_template", "{track:02d} - {title}"))
        self._move_unmatched_cb.setChecked(self._config.get("move_unmatched", False))
        self._auto_slider.setValue(
            self._config.get("auto_apply_threshold", DEFAULT_AUTO_APPLY_THRESHOLD)
        )
        self._review_slider.setValue(self._config.get("review_threshold", DEFAULT_REVIEW_THRESHOLD))
        self._acoustid_edit.setText(self._config.get("acoustid_api_key", ""))
        self._discogs_edit.setText(self._config.get("discogs_token", ""))

        theme = self._config.get("theme", "dark")
        idx = self._theme_combo.findText(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        # Show initial template preview
        self._update_template_preview()

    def _on_save(self) -> None:
        """Save settings to config and emit signal."""
        self._config["library_path"] = self._library_path_edit.text()
        self._config["backup_path"] = self._backup_path_edit.text()
        self._config["keep_originals"] = self._keep_originals_cb.isChecked()
        self._config["folder_template"] = self._folder_template_edit.text()
        self._config["file_template"] = self._file_template_edit.text()
        self._config["move_unmatched"] = self._move_unmatched_cb.isChecked()
        self._config["auto_apply_threshold"] = self._auto_slider.value()
        self._config["review_threshold"] = self._review_slider.value()
        self._config["acoustid_api_key"] = self._acoustid_edit.text()
        self._config["discogs_token"] = self._discogs_edit.text()
        self._config["theme"] = self._theme_combo.currentText()

        # Save to YAML file -- filter out internal/runtime-only keys
        # (prefixed with '_') so they don't pollute the config file.
        try:
            import yaml

            config_path = Path(__file__).parent.parent.parent.parent / "config" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            saveable = {k: v for k, v in self._config.items() if not k.startswith("_")}
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(saveable, f, default_flow_style=False, allow_unicode=True)
            logger.info("Settings saved to %s", config_path)
            QMessageBox.information(self, "Settings", "Settings saved successfully.")
        except Exception as e:
            logger.error("Failed to save settings: %s", e)
            QMessageBox.warning(self, "Error", f"Failed to save settings: {e}")

        self.settings_changed.emit(self._config)

    def _on_auto_threshold_changed(self, value: int) -> None:
        """Ensure auto-apply threshold stays >= review threshold."""
        self._auto_label.setText(f"{value}%")
        if value < self._review_slider.value():
            self._review_slider.setValue(value)

    def _on_review_threshold_changed(self, value: int) -> None:
        """Ensure review threshold stays <= auto-apply threshold."""
        self._review_label.setText(f"{value}%")
        if value > self._auto_slider.value():
            self._auto_slider.setValue(value)

    # Sample data for template preview
    _SAMPLE_DATA: ClassVar[dict[str, str | int]] = {
        "artist": "Kendrick Lamar",
        "album": "good kid, m.A.A.d city",
        "year": 2012,
        "track": 3,
        "title": "Backseat Freestyle",
        "disc": 1,
    }

    def _update_template_preview(self) -> None:
        """Validate and preview the folder/file templates with sample data."""
        folder_tmpl = self._folder_template_edit.text() or "{artist}/{album} ({year})"
        file_tmpl = self._file_template_edit.text() or "{track:02d} - {title}"

        try:
            folder_result = folder_tmpl.format(**self._SAMPLE_DATA)
        except (KeyError, ValueError, IndexError) as e:
            self._template_preview.setText(f"Folder template error: {e}")
            self._template_preview.setStyleSheet("color: #f38ba8; font-size: 11px; padding: 4px 0;")
            return

        try:
            file_result = file_tmpl.format(**self._SAMPLE_DATA)
        except (KeyError, ValueError, IndexError) as e:
            self._template_preview.setText(f"File template error: {e}")
            self._template_preview.setStyleSheet("color: #f38ba8; font-size: 11px; padding: 4px 0;")
            return

        preview = f"{folder_result}/{file_result}.mp3"
        self._template_preview.setText(preview)
        self._template_preview.setStyleSheet("color: #a6e3a1; font-size: 11px; padding: 4px 0;")

    def _browse_library_path(self) -> None:
        """Open a folder picker for the library path."""
        folder = QFileDialog.getExistingDirectory(self, "Select Library Folder")
        if folder:
            self._library_path_edit.setText(folder)

    def _browse_backup_path(self) -> None:
        """Open a folder picker for the backup path."""
        folder = QFileDialog.getExistingDirectory(self, "Select Backup Folder")
        if folder:
            self._backup_path_edit.setText(folder)

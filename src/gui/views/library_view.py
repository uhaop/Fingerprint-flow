"""Library view -- browse organized music library in a tree structure."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.utils.constants import SECONDS_PER_MINUTE
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.track import Track

logger = get_logger("gui.library_view")


class TrackInfoPanel(QFrame):
    """Side panel showing details of a selected track."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trackInfoPanel")
        self.setFixedWidth(320)
        self.setStyleSheet("""
            #trackInfoPanel {
                background-color: #181825;
                border-left: 1px solid #313244;
                border-radius: 0px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self._title_label = QLabel("Select a track")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._detail_labels: dict[str, QLabel] = {}
        for field in [
            "Artist",
            "Album",
            "Year",
            "Track",
            "Genre",
            "Duration",
            "Format",
            "Bitrate",
            "Confidence",
            "File",
        ]:
            label = QLabel(f"{field}: —")
            label.setWordWrap(True)
            label.setObjectName("detailLabel")
            self._detail_labels[field] = label
            layout.addWidget(label)

        layout.addStretch()

    def show_track(self, track: Track) -> None:
        """Display details for a track.

        Args:
            track: Track to display.
        """
        self._title_label.setText(track.display_title)
        self._detail_labels["Artist"].setText(f"Artist: {track.display_artist}")
        self._detail_labels["Album"].setText(f"Album: {track.display_album}")
        self._detail_labels["Year"].setText(f"Year: {track.year or '—'}")

        track_str = f"{track.track_number}" if track.track_number else "—"
        if track.total_tracks:
            track_str += f" / {track.total_tracks}"
        self._detail_labels["Track"].setText(f"Track: {track_str}")

        self._detail_labels["Genre"].setText(f"Genre: {track.genre or '—'}")

        dur_str = "—"
        if track.duration:
            mins = int(track.duration // SECONDS_PER_MINUTE)
            secs = int(track.duration % 60)
            dur_str = f"{mins}:{secs:02d}"
        self._detail_labels["Duration"].setText(f"Duration: {dur_str}")

        self._detail_labels["Format"].setText(f"Format: {(track.file_format or '—').upper()}")
        self._detail_labels["Bitrate"].setText(f"Bitrate: {track.bitrate or '—'} kbps")
        self._detail_labels["Confidence"].setText(f"Confidence: {track.confidence:.0f}%")
        self._detail_labels["File"].setText(f"File: {track.file_path.name}")

    def clear(self) -> None:
        """Clear the panel."""
        self._title_label.setText("Select a track")
        for label in self._detail_labels.values():
            field = label.text().split(":")[0]
            label.setText(f"{field}: —")


class LibraryView(QWidget):
    """Browse organized library in an Artist > Album > Track tree.

    Signals:
        track_selected: Emitted when a track is clicked. (Track)
    """

    track_selected = pyqtSignal(object)

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._tracks: list[Track] = []
        self._track_map: dict[int, Track] = {}  # tree item id -> Track

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the library view layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 20)
        layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()

        title = QLabel("Library")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        header_layout.addStretch()

        self._stats_label = QLabel("0 tracks")
        header_layout.addWidget(self._stats_label)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._on_refresh)
        header_layout.addWidget(self._refresh_btn)

        layout.addLayout(header_layout)

        # Content: tree + info panel
        content_layout = QHBoxLayout()

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Tracks", "Year"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(24)
        self._tree.itemClicked.connect(self._on_item_clicked)

        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        content_layout.addWidget(self._tree)

        self._info_panel = TrackInfoPanel()
        content_layout.addWidget(self._info_panel)

        layout.addLayout(content_layout)

    def set_tracks(self, tracks: list[Track]) -> None:
        """Populate the library tree with tracks.

        Args:
            tracks: List of Track objects to display.
        """
        self._tracks = tracks
        self._build_tree()

    def _build_tree(self) -> None:
        """Build the Artist > Album > Track tree structure."""
        self._tree.clear()
        self._track_map.clear()

        # Group by artist > album
        structure: dict[str, dict[str, list[Track]]] = {}
        for track in self._tracks:
            artist = track.display_artist
            album = track.display_album
            if artist not in structure:
                structure[artist] = {}
            if album not in structure[artist]:
                structure[artist][album] = []
            structure[artist][album].append(track)

        # Build tree items
        item_id = 0
        total_tracks = 0

        for artist in sorted(structure.keys()):
            artist_item = QTreeWidgetItem([artist, "", ""])
            artist_track_count = 0

            for album in sorted(structure[artist].keys()):
                tracks = structure[artist][album]
                tracks.sort(key=lambda t: t.track_number or 0)

                year_str = ""
                if tracks and tracks[0].year:
                    year_str = str(tracks[0].year)

                album_item = QTreeWidgetItem([album, str(len(tracks)), year_str])

                for track in tracks:
                    track_name = track.display_title
                    if track.track_number:
                        track_name = f"{track.track_number:02d} - {track_name}"

                    track_item = QTreeWidgetItem([track_name, "", ""])
                    track_item.setData(0, Qt.ItemDataRole.UserRole, item_id)
                    self._track_map[item_id] = track
                    item_id += 1
                    artist_track_count += 1
                    total_tracks += 1

                    album_item.addChild(track_item)

                artist_item.addChild(album_item)

            artist_item.setText(1, str(artist_track_count))
            self._tree.addTopLevelItem(artist_item)

        self._stats_label.setText(f"{total_tracks} tracks")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle tree item click."""
        item_id = item.data(0, Qt.ItemDataRole.UserRole)
        if item_id is not None and item_id in self._track_map:
            track = self._track_map[item_id]
            self._info_panel.show_track(track)
            self.track_selected.emit(track)

    def _on_refresh(self) -> None:
        """Rebuild the tree from current data."""
        self._build_tree()

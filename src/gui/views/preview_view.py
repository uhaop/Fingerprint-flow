"""Preview Report view -- dry-run results grouped by artist with approve/reject."""

from __future__ import annotations

from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QFrame,
    QHeaderView,
    QLineEdit,
    QComboBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from src.models.track import Track
from src.models.match_result import MatchResult
from src.models.processing_state import ProcessingState
from src.core.batch_processor import BatchResult
from src.utils.logger import get_logger

logger = get_logger("gui.preview_view")

# Tag fields shown in the before/after diff
_DIFF_FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("album_artist", "Album Artist"),
    ("track_number", "Track #"),
    ("total_tracks", "Total Tracks"),
    ("disc_number", "Disc #"),
    ("total_discs", "Total Discs"),
    ("year", "Year"),
    ("genre", "Genre"),
]

# Column indices for the tree widget
COL_NAME = 0
COL_CHANGES = 1
COL_CONFIDENCE = 2
COL_STATUS = 3


class _StatCard(QFrame):
    """A single summary stat card (number + label)."""

    def __init__(
        self,
        label: str,
        color_class: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("previewStatCard")
        if color_class:
            self.setProperty("statColor", color_class)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._value_label = QLabel("0")
        value_font = QFont()
        value_font.setPointSize(22)
        value_font.setBold(True)
        self._value_label.setFont(value_font)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_label)

        desc = QLabel(label)
        desc.setObjectName("statCardLabel")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

    def set_value(self, value: int | str) -> None:
        """Update the displayed value."""
        self._value_label.setText(str(value))


def _format_value(value: object) -> str:
    """Format a tag value for display, handling None."""
    if value is None:
        return "(none)"
    return str(value)


def _build_diff_text(track: Track) -> str:
    """Build a compact diff string showing changed fields.

    Returns something like:
        Artist: kendrick lamarr -> Kendrick Lamar | Year: (none) -> 2012
    """
    original = track.original_tags
    if not original:
        return ""

    parts: list[str] = []
    for field_key, field_label in _DIFF_FIELDS:
        old_val = original.get(field_key)
        new_val = getattr(track, field_key, None)
        if old_val != new_val:
            parts.append(
                f"{field_label}: {_format_value(old_val)} -> {_format_value(new_val)}"
            )
    return " | ".join(parts) if parts else "No tag changes"


def _count_changed_fields(track: Track) -> int:
    """Count how many tag fields differ from the originals."""
    original = track.original_tags
    if not original:
        return 0
    count = 0
    for field_key, _ in _DIFF_FIELDS:
        if original.get(field_key) != getattr(track, field_key, None):
            count += 1
    return count


def _change_badges(track: Track) -> str:
    """Return a compact string of change type badges for a track."""
    badges: list[str] = []
    if _count_changed_fields(track) > 0:
        badges.append("[Tags]")
    if track.original_path and track.file_path != track.original_path:
        badges.append("[Move]")
    if track.cover_art_url:
        badges.append("[Art]")
    if not badges:
        badges.append("[No Change]")
    return " ".join(badges)


def _status_label(state: ProcessingState) -> str:
    """Human-readable status string from processing state."""
    return {
        ProcessingState.AUTO_MATCHED: "Auto-matched",
        ProcessingState.NEEDS_REVIEW: "Needs Review",
        ProcessingState.UNMATCHED: "Unmatched",
        ProcessingState.ERROR: "Error",
    }.get(state, state.value.replace("_", " ").title())


# ---- Data grouping types ----
# artist_name -> album_name -> [(Track, MatchResult | None)]
ArtistData = dict[str, dict[str, list[tuple[Track, MatchResult | None]]]]


def _group_by_artist(result: BatchResult) -> ArtistData:
    """Group tracks from a BatchResult into Artist -> Album -> Tracks."""
    data: ArtistData = {}
    for track in result.tracks:
        artist = track.display_artist
        album = track.display_album
        match_key = str(track.original_path or track.file_path)
        match_result = result.match_results.get(match_key)
        data.setdefault(artist, {}).setdefault(album, []).append(
            (track, match_result)
        )
    return data


def _artist_all_auto(album_dict: dict[str, list[tuple[Track, MatchResult | None]]]) -> bool:
    """Return True if every track for an artist is AUTO_MATCHED."""
    for tracks in album_dict.values():
        for track, _ in tracks:
            if track.state != ProcessingState.AUTO_MATCHED:
                return False
    return True


def _artist_track_count(album_dict: dict[str, list[tuple[Track, MatchResult | None]]]) -> int:
    """Total tracks across all albums for an artist."""
    return sum(len(tracks) for tracks in album_dict.values())


def _artist_summary(album_dict: dict[str, list[tuple[Track, MatchResult | None]]]) -> str:
    """Summary like '43 auto, 3 review, 1 unmatched'."""
    counts: dict[str, int] = {}
    for tracks in album_dict.values():
        for track, _ in tracks:
            label = _status_label(track.state)
            counts[label] = counts.get(label, 0) + 1
    parts = [f"{v} {k.lower()}" for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return ", ".join(parts)


def _artist_avg_confidence(album_dict: dict[str, list[tuple[Track, MatchResult | None]]]) -> float:
    """Average confidence across all tracks for an artist."""
    total = 0.0
    count = 0
    for tracks in album_dict.values():
        for track, _ in tracks:
            total += track.confidence
            count += 1
    return total / count if count else 0.0


def _artist_needs_attention(album_dict: dict[str, list[tuple[Track, MatchResult | None]]]) -> bool:
    """Return True if any track is not auto-matched."""
    return not _artist_all_auto(album_dict)


# Sentinel child to enable the expand arrow before lazy-loading
_PLACEHOLDER = "__placeholder__"


class PreviewView(QWidget):
    """Preview Report view -- shows dry-run results grouped by artist.

    Users approve or reject artists, then click Apply to process
    only the approved tracks.

    Signals:
        apply_approved: Emitted when the user clicks Apply.  Carries
            (auto_tracks, review_items) where auto_tracks is a list of
            Track objects ready to apply and review_items is a list of
            (Track, MatchResult) tuples needing candidate selection.
        back_to_import: Emitted when the user clicks Back.
    """

    apply_approved = pyqtSignal(list, list, object)  # auto_tracks, review_items, batch_result
    back_to_import = pyqtSignal()

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._data: ArtistData = {}
        self._result: BatchResult | None = None
        self._lazy_loaded: set[int] = set()  # ids of expanded artist items
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filter)

        self._setup_ui()

    # ------------------------------------------------------------------ #
    #  UI Setup
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        """Build the preview view layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 20)
        layout.setSpacing(16)

        # --- Header ---
        header = QHBoxLayout()
        title = QLabel("Preview Report")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch()

        self._back_btn = QPushButton("Back to Import")
        self._back_btn.clicked.connect(self.back_to_import.emit)
        header.addWidget(self._back_btn)
        layout.addLayout(header)

        subtitle = QLabel(
            "Review what will change before applying. "
            "Check the artists you want to process, then click Apply Approved."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # --- Summary stat cards ---
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._stat_total = _StatCard("Total Files")
        self._stat_auto = _StatCard("Auto-Matched", "green")
        self._stat_review = _StatCard("Needs Review", "yellow")
        self._stat_unmatched = _StatCard("Unmatched", "red")
        self._stat_errors = _StatCard("Errors", "red")

        for card in (
            self._stat_total,
            self._stat_auto,
            self._stat_review,
            self._stat_unmatched,
            self._stat_errors,
        ):
            stats_row.addWidget(card)

        layout.addLayout(stats_row)

        # --- Artist / attention summary ---
        self._artist_summary_label = QLabel("")
        self._artist_summary_label.setObjectName("previewArtistSummary")
        layout.addWidget(self._artist_summary_label)

        # --- Filter bar ---
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search artists or albums...")
        self._search_input.setObjectName("previewSearch")
        self._search_input.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self._search_input)

        self._filter_combo = QComboBox()
        self._filter_combo.addItem("All", "all")
        self._filter_combo.addItem("Needs Attention", "attention")
        self._filter_combo.addItem("Approved", "approved")
        self._filter_combo.addItem("Rejected", "rejected")
        self._filter_combo.setFixedWidth(160)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_combo)

        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Risk (default)", "risk")
        self._sort_combo.addItem("Alphabetical", "alpha")
        self._sort_combo.addItem("Track Count", "count")
        self._sort_combo.addItem("Confidence", "confidence")
        self._sort_combo.setFixedWidth(160)
        self._sort_combo.currentIndexChanged.connect(self._apply_sort)
        filter_row.addWidget(self._sort_combo)

        layout.addLayout(filter_row)

        # --- Artist tree ---
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Changes", "Confidence", "Status"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(24)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection,
        )
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemExpanded.connect(self._on_item_expanded)

        tree_header = self._tree.header()
        tree_header.setStretchLastSection(False)
        tree_header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        tree_header.setSectionResizeMode(COL_CHANGES, QHeaderView.ResizeMode.Stretch)
        tree_header.setSectionResizeMode(COL_CONFIDENCE, QHeaderView.ResizeMode.ResizeToContents)
        tree_header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._tree)

        # --- Empty state ---
        self._empty_label = QLabel(
            "No preview data yet. Start a scan from the Import tab."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("emptyLabel")
        empty_font = QFont()
        empty_font.setPointSize(14)
        self._empty_label.setFont(empty_font)
        self._empty_label.setVisible(True)
        layout.addWidget(self._empty_label)

        # --- Action bar ---
        action_bar = QFrame()
        action_bar.setObjectName("previewActionBar")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(16, 10, 16, 10)
        action_layout.setSpacing(12)

        self._approval_label = QLabel("0 of 0 tracks approved")
        self._approval_label.setObjectName("previewApprovalLabel")
        action_layout.addWidget(self._approval_label)

        action_layout.addStretch()

        self._reject_all_btn = QPushButton("Reject All")
        self._reject_all_btn.clicked.connect(self._on_reject_all)
        action_layout.addWidget(self._reject_all_btn)

        self._approve_safe_btn = QPushButton("Approve All Safe")
        self._approve_safe_btn.setToolTip(
            "Approve only artists where all tracks are auto-matched (90%+)"
        )
        self._approve_safe_btn.clicked.connect(self._on_approve_safe)
        action_layout.addWidget(self._approve_safe_btn)

        self._approve_all_btn = QPushButton("Approve All")
        self._approve_all_btn.clicked.connect(self._on_approve_all)
        action_layout.addWidget(self._approve_all_btn)

        self._apply_btn = QPushButton("Apply Approved")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply)
        action_layout.addWidget(self._apply_btn)

        layout.addWidget(action_bar)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def set_preview_data(self, result: BatchResult) -> None:
        """Populate the view with dry-run results.

        Args:
            result: BatchResult from a dry-run processing pass.
        """
        self._result = result
        self._data = _group_by_artist(result)
        self._lazy_loaded.clear()

        # Update stat cards
        stats = result.stats
        self._stat_total.set_value(stats.total)
        self._stat_auto.set_value(stats.auto_matched)
        self._stat_review.set_value(stats.needs_review)
        self._stat_unmatched.set_value(stats.unmatched)
        self._stat_errors.set_value(stats.errors)

        # Artist-level summary
        total_artists = len(self._data)
        attention_artists = sum(
            1 for albums in self._data.values()
            if _artist_needs_attention(albums)
        )
        ready_artists = total_artists - attention_artists
        self._artist_summary_label.setText(
            f"Artists: {total_artists} total  |  "
            f"{ready_artists} ready  |  "
            f"{attention_artists} need attention"
        )

        self._build_tree()
        self._apply_smart_defaults()
        self._empty_label.setVisible(stats.total == 0)
        self._tree.setVisible(stats.total > 0)
        self._update_approval_count()

    # ------------------------------------------------------------------ #
    #  Tree building
    # ------------------------------------------------------------------ #

    def _build_tree(self) -> None:
        """Build the artist-level tree nodes (albums/tracks are lazy)."""
        self._tree.blockSignals(True)
        self._tree.clear()

        for artist_name in self._sorted_artist_names():
            albums = self._data[artist_name]
            track_count = _artist_track_count(albums)
            avg_conf = _artist_avg_confidence(albums)
            summary = _artist_summary(albums)

            item = QTreeWidgetItem()
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsAutoTristate
            )
            item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            item.setText(COL_NAME, f"{artist_name}  ({track_count} tracks)")
            item.setText(COL_CHANGES, summary)
            item.setText(COL_CONFIDENCE, f"{avg_conf:.0f}%")
            item.setText(
                COL_STATUS,
                "Ready" if _artist_all_auto(albums) else "Needs Attention",
            )
            item.setData(COL_NAME, Qt.ItemDataRole.UserRole, artist_name)

            # Placeholder child so the expand arrow shows
            placeholder = QTreeWidgetItem([_PLACEHOLDER])
            item.addChild(placeholder)

            self._tree.addTopLevelItem(item)

        self._tree.blockSignals(False)

    def _sorted_artist_names(self) -> list[str]:
        """Return artist names sorted according to the current sort combo."""
        sort_key = self._sort_combo.currentData() or "risk"

        if sort_key == "alpha":
            return sorted(self._data.keys(), key=str.lower)
        if sort_key == "count":
            return sorted(
                self._data.keys(),
                key=lambda a: _artist_track_count(self._data[a]),
                reverse=True,
            )
        if sort_key == "confidence":
            return sorted(
                self._data.keys(),
                key=lambda a: _artist_avg_confidence(self._data[a]),
            )
        # Default: risk (needs attention first, then alphabetical)
        return sorted(
            self._data.keys(),
            key=lambda a: (
                0 if _artist_needs_attention(self._data[a]) else 1,
                a.lower(),
            ),
        )

    def _populate_children(self, artist_item: QTreeWidgetItem) -> None:
        """Lazily populate album/track children for an artist node."""
        artist_name = artist_item.data(COL_NAME, Qt.ItemDataRole.UserRole)
        if not artist_name or id(artist_item) in self._lazy_loaded:
            return

        self._lazy_loaded.add(id(artist_item))
        self._tree.blockSignals(True)

        # Remove placeholder
        while artist_item.childCount():
            artist_item.removeChild(artist_item.child(0))

        albums = self._data.get(artist_name, {})
        for album_name in sorted(albums.keys()):
            tracks = albums[album_name]

            # Album node
            year_str = ""
            for t, _ in tracks:
                if t.year:
                    year_str = str(t.year)
                    break

            album_label = f"{album_name}"
            if year_str:
                album_label += f" ({year_str})"

            album_item = QTreeWidgetItem()
            album_item.setFlags(
                album_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsAutoTristate
            )
            album_item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            album_item.setText(COL_NAME, f"{album_label}  [{len(tracks)} tracks]")
            album_item.setText(COL_CHANGES, "")
            album_item.setText(COL_CONFIDENCE, "")
            album_item.setText(COL_STATUS, "")

            # Track nodes
            sorted_tracks = sorted(
                tracks, key=lambda t: t[0].track_number or 0
            )
            for track, match_result in sorted_tracks:
                track_item = QTreeWidgetItem()
                track_item.setFlags(
                    track_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                track_item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)

                # Name: original filename
                original_name = (
                    track.original_path.name
                    if track.original_path
                    else track.file_path.name
                )
                track_item.setText(COL_NAME, original_name)

                # Changes: full before/after diff
                diff = _build_diff_text(track)
                badges = _change_badges(track)
                track_item.setText(COL_CHANGES, f"{badges}  {diff}")

                # Confidence
                track_item.setText(COL_CONFIDENCE, f"{track.confidence:.0f}%")

                # Status
                track_item.setText(COL_STATUS, _status_label(track.state))

                # Store track reference for later retrieval
                track_item.setData(
                    COL_NAME, Qt.ItemDataRole.UserRole, None
                )
                track_item.setData(
                    COL_CHANGES, Qt.ItemDataRole.UserRole, track
                )
                track_item.setData(
                    COL_CONFIDENCE, Qt.ItemDataRole.UserRole, match_result
                )

                album_item.addChild(track_item)

            artist_item.addChild(album_item)

        # Propagate the parent check state to new children
        parent_state = artist_item.checkState(COL_NAME)
        if parent_state == Qt.CheckState.Checked:
            for i in range(artist_item.childCount()):
                album_child = artist_item.child(i)
                album_child.setCheckState(COL_NAME, Qt.CheckState.Checked)
                for j in range(album_child.childCount()):
                    album_child.child(j).setCheckState(
                        COL_NAME, Qt.CheckState.Checked
                    )

        self._tree.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  Smart defaults
    # ------------------------------------------------------------------ #

    def _apply_smart_defaults(self) -> None:
        """Pre-approve artists where all tracks are auto-matched."""
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            artist_name = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
            if artist_name and artist_name in self._data:
                if _artist_all_auto(self._data[artist_name]):
                    item.setCheckState(COL_NAME, Qt.CheckState.Checked)
                else:
                    item.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
        self._tree.blockSignals(False)
        self._update_approval_count()

    # ------------------------------------------------------------------ #
    #  Signal handlers
    # ------------------------------------------------------------------ #

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        """Lazy-load children when an artist node is expanded."""
        # Only load for top-level (artist) items
        if self._tree.indexOfTopLevelItem(item) >= 0:
            if (
                item.childCount() == 1
                and item.child(0).text(COL_NAME) == _PLACEHOLDER
            ):
                self._populate_children(item)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle check state changes -- update approval count."""
        if column == COL_NAME:
            self._update_approval_count()

    def _on_search_changed(self, text: str) -> None:
        """Start a debounced search filter."""
        self._search_timer.start()

    def _apply_filter(self) -> None:
        """Filter the tree based on search text and filter combo."""
        search = self._search_input.text().strip().lower()
        filter_key = self._filter_combo.currentData() or "all"

        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            artist_name = (
                item.data(COL_NAME, Qt.ItemDataRole.UserRole) or ""
            ).lower()

            # Text search
            matches_search = not search or search in artist_name
            if not matches_search:
                # Also check album names in data
                real_name = item.data(COL_NAME, Qt.ItemDataRole.UserRole) or ""
                if real_name in self._data:
                    for album_name in self._data[real_name]:
                        if search in album_name.lower():
                            matches_search = True
                            break

            # Filter dropdown
            matches_filter = True
            if filter_key == "attention":
                real_name = item.data(COL_NAME, Qt.ItemDataRole.UserRole) or ""
                if real_name in self._data:
                    matches_filter = _artist_needs_attention(self._data[real_name])
                else:
                    matches_filter = False
            elif filter_key == "approved":
                matches_filter = item.checkState(COL_NAME) == Qt.CheckState.Checked
            elif filter_key == "rejected":
                matches_filter = item.checkState(COL_NAME) == Qt.CheckState.Unchecked

            item.setHidden(not (matches_search and matches_filter))

    def _apply_sort(self) -> None:
        """Rebuild the tree with the new sort order."""
        if self._data:
            # Preserve check states
            checked_artists: set[str] = set()
            for i in range(self._tree.topLevelItemCount()):
                item = self._tree.topLevelItem(i)
                if item.checkState(COL_NAME) != Qt.CheckState.Unchecked:
                    name = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
                    if name:
                        checked_artists.add(name)

            self._lazy_loaded.clear()
            self._build_tree()

            # Restore check states
            self._tree.blockSignals(True)
            for i in range(self._tree.topLevelItemCount()):
                item = self._tree.topLevelItem(i)
                name = item.data(COL_NAME, Qt.ItemDataRole.UserRole)
                if name in checked_artists:
                    item.setCheckState(COL_NAME, Qt.CheckState.Checked)
            self._tree.blockSignals(False)
            self._update_approval_count()

    def _on_approve_all(self) -> None:
        """Check all artist nodes."""
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(
                COL_NAME, Qt.CheckState.Checked
            )
        self._tree.blockSignals(False)
        self._update_approval_count()

    def _on_approve_safe(self) -> None:
        """Check only artists where all tracks are auto-matched."""
        self._apply_smart_defaults()

    def _on_reject_all(self) -> None:
        """Uncheck all artist nodes."""
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(
                COL_NAME, Qt.CheckState.Unchecked
            )
        self._tree.blockSignals(False)
        self._update_approval_count()

    def _on_apply(self) -> None:
        """Collect approved tracks and emit the apply_approved signal."""
        if not self._result:
            return

        auto_tracks: list[Track] = []
        review_items: list[tuple[Track, MatchResult]] = []

        # Walk all artist-level items that are checked (fully or partially)
        for i in range(self._tree.topLevelItemCount()):
            artist_item = self._tree.topLevelItem(i)
            if artist_item.checkState(COL_NAME) == Qt.CheckState.Unchecked:
                continue

            artist_name = artist_item.data(COL_NAME, Qt.ItemDataRole.UserRole)
            if not artist_name or artist_name not in self._data:
                continue

            # Ensure children are loaded so we can check per-track states
            self._populate_children(artist_item)

            # Collect approved tracks from this artist
            for album_idx in range(artist_item.childCount()):
                album_item = artist_item.child(album_idx)
                if album_item.checkState(COL_NAME) == Qt.CheckState.Unchecked:
                    continue

                for track_idx in range(album_item.childCount()):
                    track_item = album_item.child(track_idx)
                    if track_item.checkState(COL_NAME) == Qt.CheckState.Unchecked:
                        continue

                    track = track_item.data(
                        COL_CHANGES, Qt.ItemDataRole.UserRole
                    )
                    match_result = track_item.data(
                        COL_CONFIDENCE, Qt.ItemDataRole.UserRole
                    )

                    if not isinstance(track, Track):
                        continue

                    if track.state == ProcessingState.AUTO_MATCHED:
                        auto_tracks.append(track)
                    elif track.state == ProcessingState.NEEDS_REVIEW:
                        if match_result:
                            review_items.append((track, match_result))
                    # UNMATCHED / ERROR tracks are skipped

        if not auto_tracks and not review_items:
            return

        logger.info(
            "Apply approved: %d auto-matched, %d need review",
            len(auto_tracks), len(review_items),
        )

        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Applying...")

        self.apply_approved.emit(auto_tracks, review_items, self._result)

    def on_apply_finished(self, applied: int, duplicates: int, errors: int) -> None:
        """Update UI after the apply worker completes.

        Args:
            applied: Successfully applied tracks.
            duplicates: Duplicate tracks skipped.
            errors: Failed tracks.
        """
        self._apply_btn.setEnabled(True)
        self._apply_btn.setText("Apply Approved")

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _update_approval_count(self) -> None:
        """Recalculate and display how many tracks are approved."""
        total_tracks = 0
        approved_tracks = 0

        for i in range(self._tree.topLevelItemCount()):
            artist_item = self._tree.topLevelItem(i)
            artist_name = artist_item.data(COL_NAME, Qt.ItemDataRole.UserRole)
            if not artist_name or artist_name not in self._data:
                continue

            albums = self._data[artist_name]
            artist_count = _artist_track_count(albums)
            total_tracks += artist_count

            state = artist_item.checkState(COL_NAME)
            if state == Qt.CheckState.Checked:
                approved_tracks += artist_count
            elif state == Qt.CheckState.PartiallyChecked:
                # Need to count individually -- but children may not
                # be loaded yet. For partially checked, estimate from
                # loaded children or load them.
                if id(artist_item) in self._lazy_loaded:
                    for album_idx in range(artist_item.childCount()):
                        album_item = artist_item.child(album_idx)
                        for track_idx in range(album_item.childCount()):
                            if (
                                album_item.child(track_idx).checkState(COL_NAME)
                                != Qt.CheckState.Unchecked
                            ):
                                approved_tracks += 1
                # If not loaded, partially checked is rare at this stage

        self._approval_label.setText(
            f"{approved_tracks:,} of {total_tracks:,} tracks approved"
        )
        self._apply_btn.setEnabled(approved_tracks > 0)
        if approved_tracks > 0:
            self._apply_btn.setText(f"Apply {approved_tracks:,} Approved")
        else:
            self._apply_btn.setText("Apply Approved")

"""Track card widget -- displays a single track's info with action buttons."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont

from src.models.track import Track
from src.models.match_result import MatchResult, MatchCandidate
from src.gui.widgets.match_selector import MatchSelector


class TrackCard(QFrame):
    """Card displaying a track's current info and match candidates for review.

    Shows the file's existing metadata on the left and match suggestions
    on the right. Emits signals when the user selects a match or skips.

    Signals:
        match_selected: (Track, MatchCandidate) - user picked a match.
        skip_requested: (Track) - user wants to keep the original.

    Args:
        track: The track being reviewed.
        match_result: Match result containing candidates.
        parent: Optional parent widget.
    """

    match_selected = pyqtSignal(object, object)  # track, candidate
    skip_requested = pyqtSignal(object)  # track

    def __init__(
        self,
        track: Track,
        match_result: MatchResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._track = track
        self._match_result = match_result
        self.setObjectName("trackCard")
        self.setFrameStyle(QFrame.Shape.StyledPanel)

        self.setStyleSheet("""
            #trackCard {
                background-color: #1e1e2e;
                border: 1px solid #313244;
                border-radius: 12px;
                padding: 16px;
                margin-bottom: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Current file info ---
        file_section = QHBoxLayout()

        file_info = QVBoxLayout()
        file_title = QLabel(f"Current: {track.display_title}")
        file_title_font = QFont()
        file_title_font.setPointSize(13)
        file_title_font.setBold(True)
        file_title.setFont(file_title_font)
        file_info.addWidget(file_title)

        file_artist = QLabel(f"Artist: {track.display_artist}")
        file_info.addWidget(file_artist)

        file_album = QLabel(f"Album: {track.display_album}")
        file_info.addWidget(file_album)

        file_path = QLabel(f"File: {track.file_path.name}")
        file_path.setObjectName("filePathLabel")
        file_info.addWidget(file_path)

        file_section.addLayout(file_info)
        file_section.addStretch()

        # Skip button
        skip_btn = QPushButton("Keep Original")
        skip_btn.clicked.connect(lambda: self.skip_requested.emit(self._track))
        file_section.addWidget(skip_btn)

        layout.addLayout(file_section)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #313244;")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        # --- Match candidates ---
        if match_result.top_candidates:
            candidates_label = QLabel("Suggested Matches:")
            candidates_label.setObjectName("candidatesLabel")
            candidates_font = QFont()
            candidates_font.setBold(True)
            candidates_label.setFont(candidates_font)
            layout.addWidget(candidates_label)

            self._selector = MatchSelector(match_result.top_candidates)
            self._selector.match_selected.connect(
                lambda c: self.match_selected.emit(self._track, c)
            )
            layout.addWidget(self._selector)
        else:
            no_match = QLabel("No suggestions available. Use manual search below.")
            no_match.setObjectName("noMatchLabel")
            layout.addWidget(no_match)

    @property
    def track(self) -> Track:
        """Return the track this card displays."""
        return self._track

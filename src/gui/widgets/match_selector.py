"""Match selector widget -- displays match candidates as selectable cards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.gui.widgets.confidence_badge import ConfidenceBadge

if TYPE_CHECKING:
    from src.models.match_result import MatchCandidate


class MatchCard(QFrame):
    """Displays a single match candidate as a selectable card.

    Shows title, artist, album (with year), confidence badge, and source.
    Emits ``selected`` signal when clicked.

    Args:
        candidate: The match candidate to display.
        parent: Optional parent widget.
    """

    selected = pyqtSignal(object)  # Emits the MatchCandidate

    def __init__(self, candidate: MatchCandidate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._candidate = candidate
        self.setObjectName("matchCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(
            f"Match candidate: {candidate.title or 'Unknown'} by {candidate.artist or 'Unknown'}"
        )
        self.setAccessibleDescription(
            f"Confidence {candidate.confidence:.0f}%. Press Enter or Space to select."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Title
        title = QLabel(candidate.title or "Unknown Title")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Artist
        artist = QLabel(candidate.artist or "Unknown Artist")
        layout.addWidget(artist)

        # Album + Year
        album_text = candidate.album or "Unknown Album"
        if candidate.year:
            album_text += f" ({candidate.year})"
        album = QLabel(album_text)
        album.setObjectName("albumLabel")
        layout.addWidget(album)

        # Confidence badge
        badge = ConfidenceBadge(candidate.confidence)
        layout.addWidget(badge)

        # Source
        if candidate.source:
            source_label = QLabel(f"Source: {candidate.source}")
            source_label.setObjectName("sourceLabel")
            layout.addWidget(source_label)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Emit the selected signal when clicked."""
        self.selected.emit(self._candidate)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Enter/Space to select the card via keyboard."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit(self._candidate)
        else:
            super().keyPressEvent(event)

    @property
    def candidate(self) -> MatchCandidate:
        """Return the candidate this card represents."""
        return self._candidate


class MatchSelector(QWidget):
    """Widget that displays multiple match candidates for selection.

    Lays out MatchCards horizontally and emits a signal when one is selected.

    Args:
        candidates: List of match candidates to display.
        parent: Optional parent widget.
    """

    match_selected = pyqtSignal(object)  # Emits the selected MatchCandidate

    def __init__(
        self,
        candidates: list[MatchCandidate] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cards: list[MatchCard] = []

        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(12)
        self._layout.addStretch()

        if candidates:
            self.set_candidates(candidates)

    def set_candidates(self, candidates: list[MatchCandidate]) -> None:
        """Replace the current candidates with a new list.

        Args:
            candidates: List of match candidates to display.
        """
        # Clear existing cards
        for card in self._cards:
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        # Add new cards (insert before the trailing stretch)
        for candidate in candidates:
            card = MatchCard(candidate)
            card.selected.connect(self.match_selected.emit)
            self._cards.append(card)
            self._layout.insertWidget(self._layout.count() - 1, card)

    def clear(self) -> None:
        """Remove all cards."""
        self.set_candidates([])

"""Review view -- review uncertain matches, queue selections, and batch apply."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.match_result import MatchCandidate, MatchResult
    from src.models.track import Track

logger = get_logger("gui.review_view")


class MatchCard(QFrame):
    """Displays a single match candidate as a selectable card.

    When clicked, visually marks itself as selected and emits a signal.
    Clicking again deselects. Only one card per track should be selected.
    """

    selected = pyqtSignal(object)  # Emits the MatchCandidate

    def __init__(self, candidate: MatchCandidate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._candidate = candidate
        self._is_selected = False
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
        conf = candidate.confidence
        conf_text = f"Confidence: {conf:.0f}%"
        if conf >= 90:
            color = "#a6e3a1"
        elif conf >= 70:
            color = "#f9e2af"
        else:
            color = "#f38ba8"

        conf_label = QLabel(conf_text)
        conf_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        layout.addWidget(conf_label)

        # Source
        if candidate.source:
            source_display = {
                "existing_tags": "Existing Tags",
                "musicbrainz": "MusicBrainz",
                "discogs": "Discogs",
            }.get(candidate.source, candidate.source)
            source_label = QLabel(f"Source: {source_display}")
            source_label.setObjectName("sourceLabel")
            if candidate.source == "existing_tags":
                source_label.setStyleSheet("color: #89b4fa; font-weight: bold;")
            layout.addWidget(source_label)

        # Selected indicator (hidden by default)
        self._check_label = QLabel("  Selected")
        self._check_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 12px;")
        self._check_label.setVisible(False)
        layout.addWidget(self._check_label)

    def mousePressEvent(self, event: object) -> None:
        """Emit the selected signal when clicked."""
        self.selected.emit(self._candidate)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Enter/Space to select the card via keyboard."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit(self._candidate)
        else:
            super().keyPressEvent(event)

    def set_selected(self, is_selected: bool) -> None:
        """Update the visual selected state of this card.

        Uses the ``selected`` dynamic property so the global theme QSS
        can style ``#matchCard[selected="true"]`` appropriately.

        Args:
            is_selected: Whether this card is the chosen match.
        """
        self._is_selected = is_selected
        self.setProperty("selected", str(is_selected).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        self._check_label.setVisible(is_selected)

    @property
    def is_selected(self) -> bool:
        """Return whether this card is currently selected."""
        return self._is_selected


class ReviewTrackCard(QFrame):
    """Card for a single track needing review, with its match candidates.

    Selecting a match card visually highlights it and stores the choice.
    The actual processing happens later when the user clicks Apply All.

    Signals:
        selection_changed: (track, candidate_or_None) -- emitted when the
            user picks a match or deselects. candidate is None if deselected.
        skip_requested: (track) -- emitted when Keep Original is clicked.
    """

    selection_changed = pyqtSignal(object, object)  # track, candidate or None
    skip_requested = pyqtSignal(object)  # track
    manual_search_requested = pyqtSignal(
        object, str, str, str, str
    )  # track, title, artist, album, source

    def __init__(
        self,
        track: Track,
        match_result: MatchResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._track = track
        self._match_result = match_result
        self._selected_candidate: MatchCandidate | None = None
        self._is_skipped = False
        self._match_cards: list[MatchCard] = []
        self.setObjectName("reviewCard")
        self.setFrameStyle(QFrame.Shape.StyledPanel)

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

        # Status label (shows "Selected: ..." or "Skipped")
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        file_section.addWidget(self._status_label)

        # Skip button
        self._skip_btn = QPushButton("Keep Original")
        self._skip_btn.clicked.connect(self._on_skip)
        file_section.addWidget(self._skip_btn)

        layout.addLayout(file_section)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("reviewSeparator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        # --- Match candidates ---
        if match_result.top_candidates:
            candidates_label = QLabel("Click a match to select it:")
            candidates_label.setObjectName("candidatesLabel")
            candidates_font = QFont()
            candidates_font.setBold(True)
            candidates_label.setFont(candidates_font)
            layout.addWidget(candidates_label)

            cards_layout = QHBoxLayout()
            cards_layout.setSpacing(12)

            for candidate in match_result.top_candidates:
                card = MatchCard(candidate)
                card.selected.connect(self._on_candidate_clicked)
                self._match_cards.append(card)
                cards_layout.addWidget(card)

            cards_layout.addStretch()
            layout.addLayout(cards_layout)
        else:
            # No candidates -- unmatched track
            unmatched_frame = QFrame()
            unmatched_frame.setObjectName("unmatchedBanner")
            # Styled by global theme QSS via #unmatchedBanner selector
            unmatched_layout = QVBoxLayout(unmatched_frame)
            unmatched_layout.setSpacing(4)

            unmatched_title = QLabel("No matches found")
            unmatched_title.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 13px;")
            unmatched_layout.addWidget(unmatched_title)

            unmatched_desc = QLabel(
                "Neither fingerprint nor metadata lookup returned results for this track. "
                "Click Keep Original to leave it as-is, or re-scan after fixing the filename/tags."
            )
            unmatched_desc.setWordWrap(True)
            unmatched_desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
            unmatched_layout.addWidget(unmatched_desc)

            layout.addWidget(unmatched_frame)

        # --- Collapsible manual search section ---
        self._search_toggle = QPushButton("Search manually")
        self._search_toggle.setFlat(True)
        self._search_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_toggle.setStyleSheet(
            "color: #cba6f7; font-size: 12px; text-align: left; padding: 4px 0;"
        )
        self._search_toggle.clicked.connect(self._toggle_search_panel)
        layout.addWidget(self._search_toggle)

        # Search panel (hidden by default)
        self._search_panel = QFrame()
        self._search_panel.setObjectName("searchPanel")
        # Styled by global theme QSS via #searchPanel selector
        self._search_panel.setVisible(False)
        search_panel_layout = QVBoxLayout(self._search_panel)
        search_panel_layout.setSpacing(8)

        # Row 1: Title + Artist
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        title_label = QLabel("Title:")
        title_label.setFixedWidth(45)
        row1.addWidget(title_label)
        self._search_title = QLineEdit(track.title or "")
        self._search_title.setPlaceholderText("Track title")
        row1.addWidget(self._search_title)

        artist_label = QLabel("Artist:")
        artist_label.setFixedWidth(45)
        row1.addWidget(artist_label)
        self._search_artist = QLineEdit(track.artist or "")
        self._search_artist.setPlaceholderText("Artist name")
        row1.addWidget(self._search_artist)

        search_panel_layout.addLayout(row1)

        # Row 2: Album + Source selector + Search button
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        album_label = QLabel("Album:")
        album_label.setFixedWidth(45)
        row2.addWidget(album_label)
        self._search_album = QLineEdit(track.album or "")
        self._search_album.setPlaceholderText("Album name (optional)")
        row2.addWidget(self._search_album)

        source_label = QLabel("Source:")
        source_label.setFixedWidth(45)
        row2.addWidget(source_label)
        self._search_source = QComboBox()
        self._search_source.addItem("All", "all")
        self._search_source.addItem("MusicBrainz", "musicbrainz")
        self._search_source.addItem("Discogs", "discogs")
        self._search_source.setFixedWidth(130)
        row2.addWidget(self._search_source)

        self._search_btn = QPushButton("Search")
        self._search_btn.setObjectName("primaryButton")
        self._search_btn.setFixedWidth(80)
        self._search_btn.clicked.connect(self._on_manual_search)
        row2.addWidget(self._search_btn)

        search_panel_layout.addLayout(row2)

        # Search status label
        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self._search_status.setVisible(False)
        search_panel_layout.addWidget(self._search_status)

        # Manual search results area
        self._manual_cards_layout = QHBoxLayout()
        self._manual_cards_layout.setSpacing(12)
        self._manual_cards_widget = QWidget()
        self._manual_cards_widget.setLayout(self._manual_cards_layout)
        self._manual_cards_widget.setVisible(False)
        search_panel_layout.addWidget(self._manual_cards_widget)

        layout.addWidget(self._search_panel)

        # Allow Enter key to trigger search
        self._search_title.returnPressed.connect(self._on_manual_search)
        self._search_artist.returnPressed.connect(self._on_manual_search)
        self._search_album.returnPressed.connect(self._on_manual_search)

    def _toggle_search_panel(self) -> None:
        """Show or hide the manual search panel."""
        visible = not self._search_panel.isVisible()
        self._search_panel.setVisible(visible)
        self._search_toggle.setText("Hide search" if visible else "Search manually")

    def _on_manual_search(self) -> None:
        """Emit the manual search signal with the current field values."""
        title = self._search_title.text().strip()
        artist = self._search_artist.text().strip()
        album = self._search_album.text().strip()
        if not title and not artist and not album:
            return
        source = self._search_source.currentData() or "all"

        self._search_btn.setEnabled(False)
        self._search_btn.setText("...")

        source_names = {
            "all": "MusicBrainz and Discogs",
            "musicbrainz": "MusicBrainz",
            "discogs": "Discogs",
        }
        self._search_status.setText(f"Searching {source_names.get(source, source)}...")
        self._search_status.setVisible(True)
        self._manual_cards_widget.setVisible(False)
        self.manual_search_requested.emit(self._track, title, artist, album, source)

    def add_manual_results(self, candidates: list[MatchCandidate]) -> None:
        """Display results from a manual search as selectable match cards.

        Deduplicates against existing candidates (both automatic and from
        previous manual searches) by comparing (source, source_id) or
        (title, artist, album) when source_id is absent.

        Args:
            candidates: List of MatchCandidate objects from the search.
        """
        # Re-enable the search button
        self._search_btn.setEnabled(True)
        self._search_btn.setText("Search")

        # Clear previous manual result widgets and remove them from _match_cards
        while self._manual_cards_layout.count():
            item = self._manual_cards_layout.takeAt(0)
            widget = item.widget()
            if widget and widget in self._match_cards:
                self._match_cards.remove(widget)
            if widget:
                widget.deleteLater()

        if not candidates:
            self._search_status.setText("No results found. Try different terms.")
            self._search_status.setVisible(True)
            self._manual_cards_widget.setVisible(False)
            return

        # Build a set of keys for existing candidates to detect duplicates
        existing_keys: set = set()
        for card in self._match_cards:
            c = card._candidate
            if c.source and c.source_id:
                existing_keys.add((c.source, c.source_id))
            else:
                existing_keys.add((c.title.lower(), c.artist.lower(), (c.album or "").lower()))

        # Deduplicate incoming candidates
        unique_candidates: list = []
        for c in candidates:
            if c.source and c.source_id:
                key = (c.source, c.source_id)
            else:
                key = (c.title.lower(), c.artist.lower(), (c.album or "").lower())  # type: ignore[assignment]
            if key not in existing_keys:
                existing_keys.add(key)
                unique_candidates.append(c)

        if not unique_candidates:
            self._search_status.setText(
                f"{len(candidates)} results (all duplicates of existing matches)."
            )
            self._search_status.setVisible(True)
            self._manual_cards_widget.setVisible(False)
            return

        self._search_status.setText(f"{len(unique_candidates)} new results:")
        self._search_status.setVisible(True)

        # Show up to 5 unique results as match cards
        for candidate in unique_candidates[:5]:
            card = MatchCard(candidate)
            card.selected.connect(self._on_candidate_clicked)
            self._match_cards.append(card)
            self._manual_cards_layout.addWidget(card)

        self._manual_cards_layout.addStretch()
        self._manual_cards_widget.setVisible(True)

    def _on_candidate_clicked(self, candidate: MatchCandidate) -> None:
        """Handle a match card being clicked -- toggle selection.

        Args:
            candidate: The candidate that was clicked.
        """
        # If clicking the already-selected candidate, deselect
        if self._selected_candidate is candidate:
            self._selected_candidate = None
            self._is_skipped = False
            for card in self._match_cards:
                card.set_selected(False)
            self._set_card_state("default")
            self._status_label.setText("")
            self._skip_btn.setText("Keep Original")
            self._skip_btn.setEnabled(True)
            self.selection_changed.emit(self._track, None)
            return

        # Select this candidate, deselect others
        self._selected_candidate = candidate
        self._is_skipped = False
        for card in self._match_cards:
            card.set_selected(card._candidate is candidate)
        self._set_card_state("decided")
        self._status_label.setText(f"Selected: {candidate.artist} - {candidate.title}")
        self._skip_btn.setText("Keep Original")
        self._skip_btn.setEnabled(True)
        self.selection_changed.emit(self._track, candidate)

    def _on_skip(self) -> None:
        """Handle the Keep Original button -- mark as skipped."""
        if self._is_skipped:
            # Un-skip -- restore match cards to interactive state
            self._is_skipped = False
            for card in self._match_cards:
                card.setEnabled(True)
            self._set_card_state("default")
            self._status_label.setText("")
            self._skip_btn.setText("Keep Original")
            self.skip_requested.emit(self._track)
            return

        # Clear any match selection and disable match cards
        self._selected_candidate = None
        self._is_skipped = True
        for card in self._match_cards:
            card.set_selected(False)
            card.setEnabled(False)
        self._set_card_state("skipped")
        self._status_label.setText("Skipped")
        self._skip_btn.setText("Undo Skip")
        self.skip_requested.emit(self._track)

    def _set_card_state(self, state: str) -> None:
        """Update the review card's visual state via a dynamic property.

        The global theme QSS defines ``#reviewCard[state="decided"]``
        and ``#reviewCard[state="skipped"]`` selectors.

        Args:
            state: One of "default", "decided", "skipped".
        """
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

    @property
    def selected_candidate(self) -> MatchCandidate | None:
        """Return the currently selected candidate, or None."""
        return self._selected_candidate

    @property
    def is_skipped(self) -> bool:
        """Return whether this track was marked as Keep Original."""
        return self._is_skipped

    @property
    def is_decided(self) -> bool:
        """Return whether the user has made any decision (selected or skipped)."""
        return self._selected_candidate is not None or self._is_skipped

    def select_top_candidate(self) -> bool:
        """Programmatically select the first (highest-confidence) match card.

        Used by the "Accept All Top Matches" bulk action.

        Returns:
            True if a candidate was selected, False if there are no candidates.
        """
        if self._is_skipped or self._selected_candidate is not None:
            return False  # Already decided
        if not self._match_cards:
            return False  # No candidates to select
        # Simulate clicking the first card (highest confidence)
        self._on_candidate_clicked(self._match_cards[0]._candidate)
        return True


class ReviewView(QWidget):
    """Review queue for uncertain matches.

    Users browse all cards, pick matches or skip tracks, then click
    "Apply All" to batch-process everything at once.

    Signals:
        batch_apply_requested: Emitted when Apply All is clicked.
            Carries a list of (Track, MatchCandidate) tuples.
        track_skipped: Emitted for each skipped track (for state tracking).
    """

    batch_apply_requested = pyqtSignal(list)  # List[(Track, MatchCandidate)]
    track_skipped = pyqtSignal(object)  # Track
    manual_search_requested = pyqtSignal(
        object, str, str, str, str
    )  # track, title, artist, album, source

    def __init__(self, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._review_cards: list[ReviewTrackCard] = []
        self._pending_selections: dict[int, tuple[Track, MatchCandidate]] = {}
        self._skipped_tracks: dict[int, Track] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the review view layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 20)
        layout.setSpacing(16)

        # Header row
        header_layout = QHBoxLayout()

        title = QLabel("Review Queue")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        header_layout.addStretch()

        self._count_label = QLabel("0 tracks to review")
        header_layout.addWidget(self._count_label)

        layout.addLayout(header_layout)

        # Instruction text
        self._instructions = QLabel(
            "Click a match for each track, then press Apply All when you're done. "
            "Tracks you don't select will be left as-is."
        )
        self._instructions.setWordWrap(True)
        self._instructions.setObjectName("subtitle")
        self._instructions.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self._instructions)

        # Scrollable area for review cards
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setSpacing(12)
        self._scroll_layout.addStretch()

        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll)

        # Empty state
        self._empty_label = QLabel("No tracks to review. Start a scan from the Import tab.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setObjectName("emptyLabel")
        empty_font = QFont()
        empty_font.setPointSize(14)
        self._empty_label.setFont(empty_font)
        self._scroll_layout.insertWidget(0, self._empty_label)

        # --- Bottom action bar ---
        action_bar = QFrame()
        action_bar.setObjectName("reviewActionBar")
        # Styled by global theme QSS via #reviewActionBar selector
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(16, 10, 16, 10)
        action_layout.setSpacing(12)

        self._selection_summary = QLabel("0 of 0 selected")
        self._selection_summary.setStyleSheet("color: #a6adc8; font-size: 13px;")
        action_layout.addWidget(self._selection_summary)

        action_layout.addStretch()

        self._accept_all_top_btn = QPushButton("Accept All Top Matches")
        self._accept_all_top_btn.setToolTip(
            "Select the highest-confidence candidate for every undecided track"
        )
        self._accept_all_top_btn.clicked.connect(self._on_accept_all_top)
        self._accept_all_top_btn.setVisible(False)
        action_layout.addWidget(self._accept_all_top_btn)

        self._skip_all_btn = QPushButton("Skip All Remaining")
        self._skip_all_btn.clicked.connect(self._on_skip_all_remaining)
        self._skip_all_btn.setVisible(False)
        action_layout.addWidget(self._skip_all_btn)

        self._apply_btn = QPushButton("Apply All Selected")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_all)
        action_layout.addWidget(self._apply_btn)

        layout.addWidget(action_bar)

    def set_review_items(
        self,
        items: list[tuple[Track, MatchResult]],
    ) -> None:
        """Populate the review queue with tracks and their match results.

        Args:
            items: List of (Track, MatchResult) tuples.
        """
        # Clear existing
        for card in self._review_cards:
            self._scroll_layout.removeWidget(card)
            card.deleteLater()
        self._review_cards.clear()
        self._pending_selections.clear()
        self._skipped_tracks.clear()

        self._empty_label.setVisible(len(items) == 0)
        self._instructions.setVisible(len(items) > 0)
        self._count_label.setText(f"{len(items)} tracks to review")

        # Sort so tracks WITH suggestions appear first, unmatched at the bottom
        sorted_items = sorted(
            items, key=lambda item: (len(item[1].candidates) == 0, item[0].display_title)
        )

        for track, match_result in sorted_items:
            card = ReviewTrackCard(track, match_result)
            card.selection_changed.connect(self._on_selection_changed)
            card.skip_requested.connect(self._on_skip_toggled)
            card.manual_search_requested.connect(self._on_manual_search)
            self._review_cards.append(card)
            # Insert before the stretch
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)

        self._update_action_bar()

    def _on_selection_changed(self, track: Track, candidate: MatchCandidate | None) -> None:
        """Handle a card's match selection changing.

        Args:
            track: The track whose selection changed.
            candidate: The selected candidate, or None if deselected.
        """
        track_key = id(track)
        if candidate is not None:
            self._pending_selections[track_key] = (track, candidate)
            # Remove from skipped if it was there
            self._skipped_tracks.pop(track_key, None)
        else:
            self._pending_selections.pop(track_key, None)

        self._update_action_bar()

    def _on_skip_toggled(self, track: Track) -> None:
        """Handle a track being toggled as skipped.

        Args:
            track: The track that was skipped or un-skipped.
        """
        track_key = id(track)
        # Find the card to check its state
        for card in self._review_cards:
            if card._track is track:
                if card.is_skipped:
                    self._skipped_tracks[track_key] = track
                    self._pending_selections.pop(track_key, None)
                else:
                    self._skipped_tracks.pop(track_key, None)
                break

        self._update_action_bar()

    def _on_manual_search(
        self, track: Track, title: str, artist: str, album: str, source: str
    ) -> None:
        """Bubble up manual search request from a card."""
        self.manual_search_requested.emit(track, title, artist, album, source)

    def on_manual_search_results(self, track_id: int, candidates: list[MatchCandidate]) -> None:
        """Route manual search results back to the correct card.

        Args:
            track_id: id(track) that requested the search.
            candidates: Search results.
        """
        for card in self._review_cards:
            if id(card._track) == track_id:
                card.add_manual_results(candidates)
                break

    def _on_accept_all_top(self) -> None:
        """Select the top-1 candidate for every undecided track that has candidates."""
        accepted = 0
        for card in self._review_cards:
            if card.select_top_candidate():
                accepted += 1
        logger.info("Accept All Top Matches: %d tracks selected", accepted)
        self._update_action_bar()

    def _on_skip_all_remaining(self) -> None:
        """Mark all undecided tracks as skipped."""
        for card in self._review_cards:
            if not card.is_decided:
                card._on_skip()

    def _on_apply_all(self) -> None:
        """Collect all selections and emit the batch apply signal."""
        if not self._pending_selections:
            return

        selections = list(self._pending_selections.values())
        logger.info("Batch apply requested: %d matches selected", len(selections))

        # Mark skipped tracks
        for track in self._skipped_tracks.values():
            self.track_skipped.emit(track)

        # Disable the button to prevent double-clicks
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Applying...")

        self.batch_apply_requested.emit(selections)

    def on_batch_apply_finished(self, applied: int, duplicates: int, errors: int) -> None:
        """Update the UI after batch apply completes.

        Called by the main window after the background worker finishes.

        Args:
            applied: Number of tracks successfully applied.
            duplicates: Number of duplicate tracks skipped.
            errors: Number of tracks that failed.
        """
        # Remove all decided cards from the view
        cards_to_remove = []
        for card in self._review_cards:
            if card.is_decided:
                cards_to_remove.append(card)

        for card in cards_to_remove:
            self._scroll_layout.removeWidget(card)
            card.deleteLater()
            self._review_cards.remove(card)

        self._pending_selections.clear()
        self._skipped_tracks.clear()

        # Update UI
        remaining = len(self._review_cards)
        self._count_label.setText(f"{remaining} tracks to review")
        self._empty_label.setVisible(remaining == 0)
        self._apply_btn.setText("Apply All Selected")
        self._update_action_bar()

    def _update_action_bar(self) -> None:
        """Update the selection count and button states."""
        total = len(self._review_cards)
        selected = len(self._pending_selections)
        skipped = len(self._skipped_tracks)
        decided = selected + skipped
        undecided = total - decided

        parts = []
        if selected:
            parts.append(f"{selected} selected")
        if skipped:
            parts.append(f"{skipped} skipped")

        summary = f"{', '.join(parts)} of {total} tracks" if parts else f"0 of {total} selected"

        self._selection_summary.setText(summary)
        self._apply_btn.setEnabled(selected > 0)
        self._apply_btn.setText(f"Apply {selected} Selected" if selected else "Apply All Selected")
        self._skip_all_btn.setVisible(undecided > 0 and decided > 0)
        # Show "Accept All Top Matches" when there are undecided cards with candidates
        has_undecided_with_candidates = any(
            not card.is_decided and card._match_cards for card in self._review_cards
        )
        self._accept_all_top_btn.setVisible(has_undecided_with_candidates)

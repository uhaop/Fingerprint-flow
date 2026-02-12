"""Search bar widget -- manual search input for MusicBrainz/Discogs queries."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)
from PyQt6.QtCore import pyqtSignal


class SearchBar(QWidget):
    """A search bar with text input and search button.

    Emits ``search_requested`` when the user presses Enter or clicks Search.

    Signals:
        search_requested: (query_text) - emitted when a search is triggered.

    Args:
        placeholder: Placeholder text for the input field.
        parent: Optional parent widget.
    """

    search_requested = pyqtSignal(str)

    def __init__(
        self,
        placeholder: str = "Search for artist, title, or album...",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.returnPressed.connect(self._on_search)
        layout.addWidget(self._input)

        self._search_btn = QPushButton("Search")
        self._search_btn.setObjectName("primaryButton")
        self._search_btn.clicked.connect(self._on_search)
        layout.addWidget(self._search_btn)

    def _on_search(self) -> None:
        """Emit search_requested with the current query text."""
        query = self._input.text().strip()
        if query:
            self.search_requested.emit(query)

    def clear(self) -> None:
        """Clear the input field."""
        self._input.clear()

    @property
    def text(self) -> str:
        """Return the current input text."""
        return self._input.text().strip()

    @text.setter
    def text(self, value: str) -> None:
        """Set the input text."""
        self._input.setText(value)

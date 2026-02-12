"""Confidence badge widget -- visual indicator of match quality."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QWidget

from src.utils.constants import DEFAULT_AUTO_APPLY_THRESHOLD, DEFAULT_REVIEW_THRESHOLD


class ConfidenceBadge(QLabel):
    """A styled label that shows a confidence score with color coding.

    Colors:
    - Green (>= auto_threshold): High confidence, auto-applied
    - Yellow (>= review_threshold): Medium confidence, needs review
    - Red (< review_threshold): Low confidence, manual review needed

    Args:
        confidence: Score from 0.0 to 100.0.
        auto_threshold: Threshold for green/auto-apply.
        review_threshold: Threshold for yellow/review.
        parent: Optional parent widget.
    """

    # Color palette (Catppuccin Mocha)
    COLOR_HIGH = "#a6e3a1"  # Green
    COLOR_MEDIUM = "#f9e2af"  # Yellow
    COLOR_LOW = "#f38ba8"  # Red

    def __init__(
        self,
        confidence: float = 0.0,
        auto_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._auto_threshold = auto_threshold
        self._review_threshold = review_threshold
        self.set_confidence(confidence)

    def set_confidence(self, confidence: float) -> None:
        """Update the displayed confidence score and color.

        Args:
            confidence: Score from 0.0 to 100.0.
        """
        self._confidence = confidence
        self.setText(f"{confidence:.0f}%")

        if confidence >= self._auto_threshold:
            color = self.COLOR_HIGH
        elif confidence >= self._review_threshold:
            color = self.COLOR_MEDIUM
        else:
            color = self.COLOR_LOW

        self.setStyleSheet(f"color: {color}; font-weight: bold;")

    @property
    def confidence(self) -> float:
        """Return the current confidence value."""
        return self._confidence

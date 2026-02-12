"""Album art viewer widget -- displays album cover art."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout, QFrame
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage


class AlbumArtViewer(QFrame):
    """Displays album cover art with a placeholder when no art is available.

    Args:
        size: Width and height of the viewer in pixels.
        parent: Optional parent widget.
    """

    def __init__(
        self,
        size: int = 200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setObjectName("albumArtViewer")
        self.setStyleSheet("""
            #albumArtViewer {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFixedSize(size, size)
        layout.addWidget(self._label)

        self.clear()

    def set_image_data(self, image_data: bytes) -> None:
        """Display album art from raw image bytes.

        Args:
            image_data: Raw image bytes (JPEG, PNG, etc.).
        """
        image = QImage()
        if image.loadFromData(image_data):
            pixmap = QPixmap.fromImage(image)
            scaled = pixmap.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._label.setPixmap(scaled)
        else:
            self.clear()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Display album art from a QPixmap.

        Args:
            pixmap: The pixmap to display.
        """
        scaled = pixmap.scaled(
            self._size, self._size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)

    def clear(self) -> None:
        """Show placeholder when no art is available."""
        self._label.setPixmap(QPixmap())
        self._label.setText("No Art")
        self._label.setStyleSheet("color: #6c7086; font-size: 14px;")

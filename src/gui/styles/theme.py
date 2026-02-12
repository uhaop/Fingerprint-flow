"""Color palette, spacing, fonts, and theme constants for Fingerprint Flow GUI.

Uses the Catppuccin color palette (Mocha for dark, Latte for light).
"""

from __future__ import annotations

from pathlib import Path


# --- Catppuccin Mocha (Dark Theme) ---
class DarkPalette:
    """Catppuccin Mocha dark theme colors."""

    BASE = "#1e1e2e"
    MANTLE = "#181825"
    CRUST = "#11111b"
    SURFACE0 = "#313244"
    SURFACE1 = "#45475a"
    SURFACE2 = "#585b70"
    OVERLAY0 = "#6c7086"
    OVERLAY1 = "#7f849c"
    OVERLAY2 = "#9399b2"
    SUBTEXT0 = "#a6adc8"
    SUBTEXT1 = "#bac2de"
    TEXT = "#cdd6f4"
    LAVENDER = "#b4befe"
    MAUVE = "#cba6f7"
    GREEN = "#a6e3a1"
    YELLOW = "#f9e2af"
    RED = "#f38ba8"
    PEACH = "#fab387"
    TEAL = "#94e2d5"
    BLUE = "#89b4fa"


# --- Catppuccin Latte (Light Theme) ---
class LightPalette:
    """Catppuccin Latte light theme colors."""

    BASE = "#eff1f5"
    MANTLE = "#e6e9ef"
    CRUST = "#dce0e8"
    SURFACE0 = "#ccd0da"
    SURFACE1 = "#bcc0cc"
    SURFACE2 = "#acb0be"
    OVERLAY0 = "#9ca0b0"
    OVERLAY1 = "#8c8fa1"
    OVERLAY2 = "#7c7f93"
    SUBTEXT0 = "#6c6f85"
    SUBTEXT1 = "#5c5f77"
    TEXT = "#4c4f69"
    LAVENDER = "#7287fd"
    MAUVE = "#8839ef"
    GREEN = "#40a02b"
    YELLOW = "#df8e1d"
    RED = "#d20f39"
    PEACH = "#fe640b"
    TEAL = "#179299"
    BLUE = "#1e66f5"
    WHITE = "#ffffff"


# --- Spacing and sizing ---
SIDEBAR_WIDTH = 200
CONTENT_PADDING = 40
SIDEBAR_PADDING_H = 12
SIDEBAR_PADDING_V = 16
BUTTON_BORDER_RADIUS = 8
CARD_BORDER_RADIUS = 10
INPUT_BORDER_RADIUS = 6
SCROLLBAR_WIDTH = 10
SLIDER_HANDLE_SIZE = 18

# --- Font sizes ---
FONT_SIZE_TITLE = 22
FONT_SIZE_SUBTITLE = 16
FONT_SIZE_BODY = 13
FONT_SIZE_SMALL = 11
FONT_SIZE_SIDEBAR = 13
FONT_SIZE_STATUS = 12
FONT_SIZE_STAT_NUMBER = 20


def get_stylesheet_path() -> Path:
    """Return the path to the shared stylesheets.qss file.

    Returns:
        Path to the QSS file.
    """
    return Path(__file__).parent / "stylesheets.qss"


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert a hex color to an rgba() CSS string.

    Args:
        hex_color: Hex color string (e.g. "#cba6f7").
        alpha: Alpha value between 0.0 and 1.0.

    Returns:
        CSS rgba() string.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _generate_theme_qss(p: type) -> str:
    """Generate a complete theme QSS string from a palette class.

    Args:
        p: A palette class (DarkPalette or LightPalette) with color constants.

    Returns:
        Complete QSS string for the theme.
    """
    white = getattr(p, "WHITE", "#ffffff")
    return f"""
QMainWindow {{
    background-color: {p.BASE};
    color: {p.TEXT};
}}

#sidebar {{
    background-color: {p.MANTLE};
    border-right: 1px solid {p.SURFACE0};
}}

#sidebarTitle {{
    color: {p.MAUVE};
    padding: 8px;
}}

#versionLabel {{
    color: {p.OVERLAY0};
    font-size: 11px;
}}

SidebarButton {{
    background-color: transparent;
    color: {p.SUBTEXT0};
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    text-align: left;
    font-size: 13px;
}}

SidebarButton:hover {{
    background-color: {p.SURFACE0};
    color: {p.TEXT};
}}

SidebarButton:checked {{
    background-color: {p.SURFACE1};
    color: {p.MAUVE};
    font-weight: bold;
}}

#contentStack {{
    background-color: {p.BASE};
}}

QStatusBar {{
    background-color: {p.MANTLE};
    color: {p.SUBTEXT0};
    border-top: 1px solid {p.SURFACE0};
    font-size: 12px;
    padding: 4px 12px;
}}

QLabel {{
    color: {p.TEXT};
}}

QPushButton {{
    background-color: {p.SURFACE1};
    color: {p.TEXT};
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
}}

QPushButton:hover {{
    background-color: {p.SURFACE2};
}}

QPushButton:pressed {{
    background-color: {p.SURFACE0};
}}

QPushButton#primaryButton {{
    background-color: {p.MAUVE};
    color: {p.BASE};
    font-weight: bold;
}}

QPushButton#primaryButton:hover {{
    background-color: {p.LAVENDER};
}}

QLineEdit, QTextEdit {{
    background-color: {p.SURFACE0};
    color: {p.TEXT};
    border: 1px solid {p.SURFACE1};
    border-radius: 6px;
    padding: 8px;
    font-size: 13px;
}}

QLineEdit:focus, QTextEdit:focus {{
    border-color: {p.MAUVE};
}}

QProgressBar {{
    background-color: {p.SURFACE0};
    border: none;
    border-radius: 6px;
    height: 18px;
}}

QProgressBar::chunk {{
    background-color: {p.GREEN};
    border-radius: 6px;
}}

QTreeWidget, QListWidget, QTableWidget {{
    background-color: {p.BASE};
    color: {p.TEXT};
    border: 1px solid {p.SURFACE0};
    border-radius: 6px;
    alternate-background-color: {p.MANTLE};
}}

QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {p.SURFACE1};
}}

QHeaderView::section {{
    background-color: {p.MANTLE};
    color: {p.SUBTEXT0};
    border: none;
    padding: 8px;
    font-weight: bold;
}}

QScrollBar:vertical {{
    background-color: {p.MANTLE};
    width: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background-color: {p.SURFACE1};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {p.SURFACE2};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QSlider::groove:horizontal {{
    background-color: {p.SURFACE0};
    height: 6px;
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background-color: {p.MAUVE};
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

QComboBox {{
    background-color: {p.SURFACE0};
    color: {p.TEXT};
    border: 1px solid {p.SURFACE1};
    border-radius: 6px;
    padding: 8px;
}}

QComboBox::drop-down {{
    border: none;
}}

QComboBox QAbstractItemView {{
    background-color: {p.SURFACE0};
    color: {p.TEXT};
    selection-background-color: {p.SURFACE1};
}}

/* --- Drop zone --- */
#dropZone {{
    border: 3px dashed {p.SURFACE1};
    border-radius: 16px;
    background-color: transparent;
}}

#dropZone[hovering="true"] {{
    border: 3px dashed {p.MAUVE};
    background-color: {_hex_to_rgba(p.MAUVE, 0.08)};
}}

/* --- Match cards (match_selector and review_view) --- */
#matchCard {{
    background-color: {p.SURFACE0};
    border: 2px solid {p.SURFACE1};
    border-radius: 10px;
    padding: 12px;
}}

#matchCard:hover {{
    border-color: {p.MAUVE};
}}

#matchCard[selected="true"] {{
    border: 2px solid {p.GREEN};
}}

/* --- Review track cards --- */
#reviewCard {{
    background-color: {p.BASE};
    border: 1px solid {p.SURFACE0};
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
}}

#reviewCard[state="decided"] {{
    border: 1px solid {p.GREEN};
}}

#reviewCard[state="skipped"] {{
    background-color: {p.MANTLE};
    border: 1px solid {p.SURFACE1};
}}

#reviewCard[state="skipped"] QLabel {{
    color: {p.OVERLAY0};
}}

/* --- Review action bar --- */
#reviewActionBar {{
    background-color: {p.MANTLE};
    border: 1px solid {p.SURFACE0};
    border-radius: 10px;
    padding: 8px;
}}

/* --- Import view retry banner --- */
#retryBanner {{
    background-color: {p.SURFACE0};
    border: 1px solid {p.YELLOW};
    border-radius: 10px;
    padding: 8px;
}}

/* --- Import view file list --- */
#fileListScroll {{
    border: 1px solid {p.SURFACE1};
    border-radius: 8px;
    background-color: {p.BASE};
}}

#fileListRow {{
    background-color: {p.SURFACE0};
    border-radius: 6px;
    padding: 4px;
}}

#fileListRow:hover {{
    background-color: {p.SURFACE1};
}}

/* --- Unmatched banner in review view --- */
#unmatchedBanner {{
    background-color: {p.MANTLE};
    border: 1px solid {p.SURFACE1};
    border-radius: 8px;
    padding: 12px;
}}

/* --- Search panel in review view --- */
#searchPanel {{
    background-color: {p.MANTLE};
    border: 1px solid {p.SURFACE1};
    border-radius: 8px;
    padding: 12px;
}}

/* --- Import view fine-grained labels --- */
#retryInfoLabel {{
    color: {p.YELLOW};
    font-size: 12pt;
}}

#fileListName {{
    color: {p.TEXT};
}}

#fileListPath {{
    color: {p.OVERLAY0};
    font-size: 9pt;
}}

#fileListRemoveBtn {{
    background-color: transparent;
    color: {p.OVERLAY0};
    border: none;
    font-size: 14px;
    font-weight: bold;
}}

#fileListRemoveBtn:hover {{
    color: {p.RED};
}}

/* --- Review view separator --- */
#reviewSeparator {{
    background-color: {p.SURFACE0};
}}

/* ============================================================ */
/* --- Preview Report view ---                                  */
/* ============================================================ */

/* Stat cards */
#previewStatCard {{
    background-color: {p.SURFACE0};
    border: 1px solid {p.SURFACE1};
    border-radius: 10px;
    min-width: 120px;
}}

#previewStatCard[statColor="green"] {{
    border-color: {p.GREEN};
}}

#previewStatCard[statColor="yellow"] {{
    border-color: {p.YELLOW};
}}

#previewStatCard[statColor="red"] {{
    border-color: {p.RED};
}}

#previewStatCard QLabel {{
    color: {p.TEXT};
}}

#statCardLabel {{
    color: {p.SUBTEXT0};
    font-size: 11px;
}}

/* Artist summary line */
#previewArtistSummary {{
    color: {p.SUBTEXT0};
    font-size: 12px;
    padding: 4px 0;
}}

/* Search input */
#previewSearch {{
    background-color: {p.SURFACE0};
    color: {p.TEXT};
    border: 1px solid {p.SURFACE1};
    border-radius: 6px;
    padding: 8px;
    font-size: 13px;
}}

#previewSearch:focus {{
    border-color: {p.MAUVE};
}}

/* Action bar */
#previewActionBar {{
    background-color: {p.MANTLE};
    border: 1px solid {p.SURFACE0};
    border-radius: 10px;
    padding: 8px;
}}

#previewApprovalLabel {{
    color: {p.SUBTEXT0};
    font-size: 13px;
}}
"""


def get_dark_theme_qss() -> str:
    """Return the complete dark theme QSS."""
    return _generate_theme_qss(DarkPalette)


def get_light_theme_qss() -> str:
    """Return the complete light theme QSS."""
    return _generate_theme_qss(LightPalette)

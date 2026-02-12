"""Fingerprint Flow -- Entry point and application initialization."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

from src.utils.constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_AUTO_APPLY_THRESHOLD,
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_REVIEW_THRESHOLD,
)
from src.utils.logger import get_logger, setup_logger

# Directories that should never be used as a library path (exact matches).
_DANGEROUS_PATHS = frozenset(
    {
        "/",
        "C:\\",
        "C:\\Windows",
        "C:\\Windows\\System32",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        "/usr",
        "/usr/bin",
        "/etc",
        "/var",
        "/tmp",
        "/System",
        "/Library",
        "/Applications",
        "/bin",
        "/sbin",
        "/lib",
        "/opt",
    }
)

# Minimum number of path components (after the drive/root) for a library path.
# E.g. "D:\Music" has 1 component after the root -- that's dangerously shallow.
# "D:\Users\Me\Music Library" has 3 -- that's fine.
_MIN_PATH_DEPTH = 2


def _check_raw_windows_path(raw: str) -> str | None:
    """Check raw path string for dangerous Windows patterns.

    Use this when Path.resolve() would misbehave on non-Windows (e.g. CI on Linux
    treating C:\\Windows as a relative path). Validates the input string directly.
    """
    if not raw or ":" not in raw:
        return None
    # Normalize: backslash to forward slash, strip trailing sep
    normalized = raw.replace("\\", "/").rstrip("/")
    if not normalized:
        return None
    # Must look like Windows (drive letter)
    if len(normalized) < 2 or normalized[1] != ":":
        return None
    norm_lower = normalized.lower()
    # Drive root: D:, D:\, D:/
    if len(norm_lower) <= 3 and norm_lower.endswith(":"):
        return (
            f"is only 0 level(s) deep from the filesystem root. "
            f"Library paths should be at least {_MIN_PATH_DEPTH} levels "
            f"deep to prevent accidental damage (e.g. "
            f"'D:\\Users\\Me\\Music Library')."
        )
    # Blocklist (normalize Windows paths for comparison)
    for dangerous in _DANGEROUS_PATHS:
        if ":" in dangerous:
            d_norm = dangerous.replace("\\", "/").rstrip("/").lower()
            if norm_lower == d_norm:
                return (
                    f"resolves to a known system directory ({raw}). "
                    f"This could overwrite critical files."
                )
    # Depth: D:/Music = 1 component; D:/Users/Me/Music = 3
    parts = [p for p in normalized.split("/") if p]
    if len(parts) < 2:  # ["d:"] or ["d:", "music"] -> need at least 2 after drive
        return None  # Already handled drive root above
    # parts[0] is "D:", rest are path components
    depth = len(parts) - 1
    if depth < _MIN_PATH_DEPTH:
        return (
            f"is only {depth} level(s) deep from the filesystem root. "
            f"Library paths should be at least {_MIN_PATH_DEPTH} levels "
            f"deep to prevent accidental damage (e.g. "
            f"'D:\\Users\\Me\\Music Library')."
        )
    return None


def _is_dangerous_path(resolved: str) -> str | None:
    """Check if a resolved path is too dangerous to use as a library root.

    Uses two strategies:
    1. Exact blocklist for known system directories.
    2. Depth check -- paths with fewer than ``_MIN_PATH_DEPTH`` components
       after the filesystem root are considered dangerous (e.g. ``D:\\``
       or ``/home``).

    Args:
        resolved: Resolved, normalized path string.

    Returns:
        A human-readable reason string if the path is dangerous, or None
        if it's safe.
    """
    normalized = resolved.rstrip("/\\")

    # Exact blocklist
    for dangerous in _DANGEROUS_PATHS:
        if normalized.lower() == dangerous.lower():
            return (
                f"resolves to a known system directory ({normalized}). "
                f"This could overwrite critical files."
            )

    # Drive-root check (covers D:\, E:\, etc. on Windows and / on Unix)
    resolved_path = Path(resolved)
    try:
        # On Windows: Path("D:\\").parts == ("D:\\",)
        # On Unix: Path("/").parts == ("/",)
        # Path("D:\\Music").parts == ("D:\\", "Music")
        parts = resolved_path.parts
        root_parts = 1  # The root itself (e.g. "D:\\" or "/")
        depth = len(parts) - root_parts
        if depth < _MIN_PATH_DEPTH:
            return (
                f"is only {depth} level(s) deep from the filesystem root. "
                f"Library paths should be at least {_MIN_PATH_DEPTH} levels "
                f"deep to prevent accidental damage (e.g. "
                f"'D:\\Users\\Me\\Music Library')."
            )
    except (ValueError, OSError):
        pass

    return None


def validate_config(config: dict) -> list[str]:
    """Validate configuration values and return a list of warnings.

    Checks:
    - library_path is not a dangerous system directory or too shallow
    - Thresholds are within 0-100 and auto >= review
    - Templates contain at least {title}

    Args:
        config: Configuration dictionary.

    Returns:
        List of human-readable warning strings. Empty if all checks pass.
    """
    warnings: list[str] = []

    # Validate library_path
    lib_path = config.get("library_path", "")
    if lib_path:
        # Check raw path first for Windows patterns (Path.resolve() on Linux
        # misinterprets C:\Windows as relative, so blocklist/depth checks fail)
        reason = _check_raw_windows_path(lib_path)
        if reason is None:
            resolved = str(Path(lib_path).resolve())
            reason = _is_dangerous_path(resolved)
        if reason:
            warnings.append(f"library_path '{lib_path}' {reason}")

    # Validate thresholds
    auto_threshold = config.get("auto_apply_threshold", DEFAULT_AUTO_APPLY_THRESHOLD)
    review_threshold = config.get("review_threshold", DEFAULT_REVIEW_THRESHOLD)

    if not isinstance(auto_threshold, (int, float)) or not (0 <= auto_threshold <= 100):
        warnings.append(
            f"auto_apply_threshold must be 0-100, got {auto_threshold!r}. "
            f"Using default ({DEFAULT_AUTO_APPLY_THRESHOLD})."
        )
        config["auto_apply_threshold"] = DEFAULT_AUTO_APPLY_THRESHOLD

    if not isinstance(review_threshold, (int, float)) or not (0 <= review_threshold <= 100):
        warnings.append(
            f"review_threshold must be 0-100, got {review_threshold!r}. "
            f"Using default ({DEFAULT_REVIEW_THRESHOLD})."
        )
        config["review_threshold"] = DEFAULT_REVIEW_THRESHOLD

    auto_threshold = config.get("auto_apply_threshold", DEFAULT_AUTO_APPLY_THRESHOLD)
    review_threshold = config.get("review_threshold", DEFAULT_REVIEW_THRESHOLD)
    if auto_threshold < review_threshold:
        warnings.append(
            f"auto_apply_threshold ({auto_threshold}) must be >= review_threshold "
            f"({review_threshold}). Swapping them."
        )
        config["auto_apply_threshold"] = review_threshold
        config["review_threshold"] = auto_threshold

    # Validate templates contain {title}
    file_template = config.get("file_template", "")
    if file_template and "{title}" not in file_template:
        warnings.append(
            f"file_template '{file_template}' does not contain {{title}}. "
            f"Filenames may be unrecognizable."
        )

    return warnings


def load_config() -> dict:
    """Load configuration from config.yaml.

    Returns:
        Configuration dictionary (suitable for ``AppConfig.from_dict()``).
    """
    config: dict = {}

    # Load from config.yaml
    config_path = Path(__file__).parent.parent / "config" / DEFAULT_CONFIG_FILENAME
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    return config


def main() -> None:
    """Application entry point. Loads config, sets up logging, and launches the GUI."""
    from src.models.config import AppConfig

    raw_config = load_config()

    # Validate the raw dict first (mutates to fix invalid values)
    config_warnings = validate_config(raw_config)

    # Build typed config from the validated dict
    config = AppConfig.from_dict(raw_config)

    # Setup logging
    setup_logger(log_level=config.log_level, log_file=config.log_file)
    logger = get_logger("main")

    logger.info("%s v%s starting", APP_NAME, APP_VERSION)

    for warning in config_warnings:
        logger.warning("Config: %s", warning)

    # Check for Chromaprint (fpcalc)
    fpcalc_path = shutil.which("fpcalc")
    if fpcalc_path:
        logger.info("Chromaprint found: %s", fpcalc_path)
        config.fpcalc_available = True
    else:
        logger.warning(
            "Chromaprint (fpcalc) NOT FOUND on PATH. "
            "Audio fingerprinting will be disabled. "
            "The app will fall back to tag-based fuzzy matching only.\n"
            "To enable fingerprinting, download fpcalc from:\n"
            "  https://acoustid.org/chromaprint\n"
            "Download the PRE-BUILT BINARY (not source code), extract fpcalc.exe,\n"
            "and add its folder to your system PATH."
        )
        config.fpcalc_available = False

    # Validate API keys
    if not config.acoustid_api_key:
        logger.warning(
            "AcoustID API key not configured. Audio fingerprinting will not work. "
            "Set acoustid_api_key in config/config.yaml."
        )

    if not config.discogs_token:
        logger.info(
            "Discogs token not configured. Discogs lookups will be disabled. "
            "Set discogs_token in config/config.yaml."
        )

    # Initialize database
    from src.db.database import Database
    from src.db.repositories import ApiCacheRepository, MoveHistoryRepository, TrackRepository

    db = Database()
    db.connect()
    move_repo = MoveHistoryRepository(db.connection)
    track_repo = TrackRepository(db.connection)
    api_cache = ApiCacheRepository(db.connection)
    api_cache.prune()  # Clean up expired cache entries on startup
    logger.info("Database initialized: %s", db._db_path)

    # Launch GUI
    # NOTE: The GUI still receives the raw dict (config.to_dict()) plus the
    # runtime objects because the GUI modules have not been migrated to
    # AppConfig yet.  That migration is tracked separately.
    gui_config = config.to_dict()
    gui_config["_db"] = db
    gui_config["_move_repo"] = move_repo
    gui_config["_track_repo"] = track_repo
    gui_config["_api_cache"] = api_cache
    gui_config["_fpcalc_available"] = config.fpcalc_available

    # Windows: set AppUserModelID so the taskbar / window-corner shows
    # *our* icon instead of the generic Python interpreter icon.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "fingerprintflow.app." + APP_VERSION
        )

    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtWidgets import QApplication, QMessageBox

        from src.gui.app import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(APP_VERSION)

        # Build a multi-size icon from the high-res PNG so that Windows
        # picks the best resolution for the taskbar (24 px), title bar
        # (16 px), Alt-Tab (32-48 px), and desktop shortcuts (256 px).
        logo_path = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
        if logo_path.exists():
            icon = QIcon()
            source = QPixmap(str(logo_path))
            if not source.isNull():
                for size in (16, 24, 32, 48, 64, 128, 256):
                    icon.addPixmap(
                        source.scaled(
                            size,
                            size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            app.setWindowIcon(icon)

        # Show warning dialog if fpcalc is missing
        if not config.fpcalc_available:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Chromaprint Not Found")
            msg.setText(
                "Chromaprint (fpcalc) was not found on your system PATH.\n\n"
                "Without it, audio fingerprinting is disabled. The app will "
                "still work using tag-based fuzzy matching, but results will "
                "be less accurate.\n\n"
                "To install Chromaprint:\n"
                "1. Go to https://acoustid.org/chromaprint\n"
                "2. Download the PRE-BUILT BINARY for Windows\n"
                "   (NOT the source code .tar.gz)\n"
                "3. Extract fpcalc.exe from the zip\n"
                "4. Add its folder to your system PATH\n"
                "5. Restart this app"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()

        window = MainWindow(gui_config)
        window.show()

        exit_code = app.exec()
        db.close()
        sys.exit(exit_code)

    except ImportError as e:
        logger.error("PyQt6 is required for the GUI: %s", e)
        logger.info("Install with: pip install PyQt6")
        db.close()
        sys.exit(1)


if __name__ == "__main__":
    main()

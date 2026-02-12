"""Path helpers and safe file operations for Fingerprint Flow."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.utils.logger import get_logger
from src.utils.constants import SUPPORTED_EXTENSIONS, MAX_TOTAL_PATH_LENGTH

logger = get_logger("utils.file_utils")

# Words that stay lowercase in title case (unless they're the first word)
_SMALL_WORDS = frozenset({
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "at", "by", "in", "of", "on", "to", "up", "as", "if", "is",
    "it", "vs", "da", "tha",
})

# Words/abbreviations that should stay ALL CAPS
_UPPERCASE_WORDS = frozenset({
    "dj", "mc", "ii", "iii", "iv", "vi", "vii", "viii", "ix", "xl",
    "ep", "lp", "cd", "uk", "us", "usa", "nyc", "la", "og", "aka",
    "ft", "feat", "vs",
})

# Known artist names that use specific capitalization
_ARTIST_OVERRIDES = {
    # Major artists
    "2pac": "2Pac",
    "outkast": "OutKast",
    "dmx": "DMX",
    "eminem": "Eminem",
    "nas": "Nas",
    "jay-z": "Jay-Z",
    "jay z": "Jay-Z",
    "dr. dre": "Dr. Dre",
    "dr dre": "Dr. Dre",
    "ice cube": "Ice Cube",
    "snoop dogg": "Snoop Dogg",
    "notorious b.i.g.": "The Notorious B.I.G.",
    "biggie": "The Notorious B.I.G.",
    "nwa": "N.W.A",
    "n.w.a": "N.W.A",
    "tlc": "TLC",
    "run dmc": "Run-DMC",
    "run-dmc": "Run-DMC",
    # DJ / Screw scene
    "dj screw": "DJ Screw",
    "djscrew": "DJ Screw",
    "dj_screw": "DJ Screw",
    "dj drama": "DJ Drama",
    "dj khaled": "DJ Khaled",
    "dj clue": "DJ Clue",
    "dj kay slay": "DJ Kay Slay",
    # Houston / SUC artists common in DJ Screw tapes
    "e.s.g.": "E.S.G.",
    "e.s.g": "E.S.G.",
    "esg": "E.S.G.",
    "lil keke": "Lil' Keke",
    "lil' keke": "Lil' Keke",
    "big moe": "Big Moe",
    "fat pat": "Fat Pat",
    "big pokey": "Big Pokey",
    "lil flip": "Lil' Flip",
    "lil' flip": "Lil' Flip",
    "z-ro": "Z-Ro",
    "zro": "Z-Ro",
    "suc": "S.U.C.",
    "s.u.c.": "S.U.C.",
    "al d": "Al-D",
    "al-d": "Al-D",
    "botany boyz": "Botany Boyz",
    "point blank": "Point Blank",
    "too $hort": "Too $hort",
    "too short": "Too $hort",
    "spice 1": "Spice 1",
    "bone thugs-n-harmony": "Bone Thugs-N-Harmony",
    "bone thugs n harmony": "Bone Thugs-N-Harmony",
}


def smart_title_case(text: str) -> str:
    """Apply intelligent title case to a string.

    Rules:
    - First word is always capitalized
    - Small words (a, the, of, in, etc.) stay lowercase unless first
    - Known abbreviations (DJ, MC, etc.) stay ALL CAPS
    - Known artist names use their official capitalization
    - Words already in ALL CAPS with 2+ chars are left alone (intentional)

    Args:
        text: Raw string to title-case.

    Returns:
        Title-cased string.
    """
    if not text:
        return text

    # Check for known artist name overrides first (exact match)
    lower = text.strip().lower()
    if lower in _ARTIST_OVERRIDES:
        return _ARTIST_OVERRIDES[lower]

    words = text.split()
    result = []
    last_idx = len(words) - 1

    for i, word in enumerate(words):
        word_lower = word.lower()
        word_stripped = word.strip("()[].,!?'\"")
        stripped_lower = word_stripped.lower()

        if stripped_lower in _UPPERCASE_WORDS:
            # Known abbreviation -> ALL CAPS
            result.append(word.replace(word_stripped, word_stripped.upper()))
        elif i == 0 or i == last_idx:
            # First and last word always capitalized
            result.append(word.capitalize())
        elif stripped_lower in _SMALL_WORDS:
            # Small words stay lowercase (unless first/last)
            result.append(word.lower())
        elif word_stripped.isupper() and len(word_stripped) >= 2:
            # Already ALL CAPS and 2+ chars -- leave it (could be intentional)
            result.append(word)
        else:
            # Standard title case
            result.append(word.capitalize())

    return " ".join(result)


def normalize_artist_name(name: str) -> str:
    """Normalize an artist name with proper capitalization.

    Checks known artist overrides first, then applies smart title case.

    Args:
        name: Raw artist name.

    Returns:
        Normalized artist name.
    """
    if not name:
        return name

    lower = name.strip().lower()
    if lower in _ARTIST_OVERRIDES:
        return _ARTIST_OVERRIDES[lower]

    return smart_title_case(name)


def is_audio_file(path: Path) -> bool:
    """Check if a file has a supported audio extension.

    Args:
        path: Path to check.

    Returns:
        True if the file extension is a supported audio format.
    """
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def safe_copy(src: Path, dst: Path) -> Path:
    """Copy a file, creating parent directories as needed.

    Args:
        src: Source file path.
        dst: Destination file path.

    Returns:
        The destination path.

    Raises:
        FileNotFoundError: If source does not exist.
        OSError: If copy fails.
    """
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    logger.debug("Copied: %s -> %s", src, dst)
    return dst


def safe_move(src: Path, dst: Path) -> Path:
    """Move a file, creating parent directories as needed.

    For cross-device moves (where ``rename()`` fails), the file is copied
    first and then the source is deleted -- but only after verifying that
    the destination file exists and has the correct size.  This prevents
    data loss if the copy is interrupted.

    Args:
        src: Source file path.
        dst: Destination file path.

    Returns:
        The destination path.

    Raises:
        FileNotFoundError: If source does not exist.
        OSError: If move fails or integrity check fails after copy.
    """
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Handle cross-device moves (copy + delete)
    try:
        src.rename(dst)
    except OSError:
        src_size = src.stat().st_size
        shutil.copy2(src, dst)

        # Verify the copy succeeded before removing the source.
        if not dst.exists():
            raise OSError(
                f"Cross-device move failed: destination not created: {dst}"
            )
        dst_size = dst.stat().st_size
        if dst_size != src_size:
            # Remove the partial copy to avoid confusion
            try:
                dst.unlink()
            except OSError:
                pass
            raise OSError(
                f"Cross-device move failed: size mismatch "
                f"(src={src_size}, dst={dst_size}): {dst}"
            )
        src.unlink()

    logger.debug("Moved: %s -> %s", src, dst)
    return dst


# Windows reserved device names that cannot be used as filenames.
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Maximum length for a single path component (filename or directory name).
# NTFS allows 255 characters per component; we use a slightly lower value
# to leave room for a file extension and deduplication suffix like " (1)".
MAX_COMPONENT_LENGTH = 240


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in filenames.

    Also guards against Windows reserved device names (CON, PRN, AUX, NUL,
    COM1-COM9, LPT1-LPT9) and enforces a maximum component length.

    Args:
        name: Raw filename string.

    Returns:
        Sanitized filename safe for all major operating systems.
    """
    # Characters invalid on Windows
    invalid_chars = '<>:"/\\|?*'
    sanitized = name
    for char in invalid_chars:
        sanitized = sanitized.replace(char, "_")

    # Remove leading/trailing dots and spaces (Windows issue)
    sanitized = sanitized.strip(". ")

    # Collapse multiple underscores
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")

    # Guard against Windows reserved device names.
    # "CON", "CON.txt", "con.mp3" are all invalid on Windows.
    stem = sanitized.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"

    # Enforce a maximum component length so we don't hit path limits.
    if len(sanitized) > MAX_COMPONENT_LENGTH:
        sanitized = sanitized[:MAX_COMPONENT_LENGTH].rstrip(". ")

    return sanitized or "Unknown"


def unique_path(path: Path) -> Path:
    """Return a unique path by appending a counter if the file already exists.

    Args:
        path: Desired file path.

    Returns:
        A path that does not collide with existing files.
    """
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1

    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def enforce_path_length(path: Path, max_length: int = MAX_TOTAL_PATH_LENGTH) -> Path:
    """Shorten a file path if it exceeds *max_length* characters.

    The filename stem (not the extension) is truncated first.  If that is
    not enough, parent directory names are shortened as well, starting from
    the deepest.

    Args:
        path: Desired file path.
        max_length: Maximum allowed total path length in characters.

    Returns:
        A path that fits within *max_length*.
    """
    path_str = str(path)
    if len(path_str) <= max_length:
        return path

    overflow = len(path_str) - max_length
    stem = path.stem
    suffix = path.suffix

    # Try truncating the filename stem first
    if len(stem) > overflow + 3:
        truncated_stem = stem[: len(stem) - overflow - 3] + "..."
        shortened = path.parent / f"{truncated_stem}{suffix}"
        if len(str(shortened)) <= max_length:
            return shortened

    # If the filename alone is not enough, truncate parent folder names
    # starting from the deepest (rightmost) part.
    parts = list(path.parts)
    # Parts: [root, ..., grandparent, parent, filename]
    # Truncate from len-2 (parent) upward, skip root (index 0) and filename (last).
    for i in range(len(parts) - 2, 0, -1):
        if len(parts[i]) > 20:
            parts[i] = parts[i][:17] + "..."
        path = Path(*parts)
        if len(str(path)) <= max_length:
            return path

    # Last resort: hard-truncate the stem
    max_stem = max_length - len(str(path.parent)) - len(suffix) - 5
    if max_stem > 0:
        return path.parent / f"{stem[:max_stem]}...{suffix}"

    return path


def get_file_size_mb(path: Path) -> float:
    """Get file size in megabytes.

    Args:
        path: Path to the file.

    Returns:
        File size in MB, or 0.0 if the file doesn't exist.
    """
    try:
        return path.stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0

"""Compilation and DJ mix album detection logic.

Extracted from BatchProcessor to improve separation of concerns.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.models.track import Track
from src.utils.file_utils import normalize_artist_name
from src.utils.logger import get_logger
from src.utils.constants import (
    COMPILATION_INDICATORS,
    KNOWN_DJS,
    SCREW_ALBUM_KEYWORDS,
    DJ_SCREW_FOLDER_VARIANTS,
    DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST,
)

if TYPE_CHECKING:
    from src.core.dj_screw_handler import DJScrewHandler

logger = get_logger("core.compilation_detector")


class CompilationDetector:
    """Detects whether a track belongs to a compilation, DJ mix, or similar."""

    def __init__(self, screw_handler: DJScrewHandler) -> None:
        self._screw_handler = screw_handler

    def detect(self, track: Track) -> None:
        """Detect if a track belongs to a compilation / DJ mix album.

        Sets track.is_compilation = True and ensures album_artist is set when:
        - album_artist is a known DJ or compilation indicator
        - album_artist differs from track artist and starts with 'DJ'
        - album name contains compilation keywords
        - The source folder structure indicates a DJ/compilation release
        """
        aa_lower = (track.album_artist or "").strip().lower()
        album_lower = (track.album or "").strip().lower()
        artist_lower = (track.artist or "").strip().lower()

        # Check if album_artist is a known DJ/compiler
        if aa_lower in KNOWN_DJS:
            track.is_compilation = True
            track.album_artist = normalize_artist_name(track.album_artist)
            if "dj screw" in aa_lower:
                self._screw_handler.normalize_screw_album(track)
            logger.debug("Compilation detected (known DJ): %s", track.album_artist)
            return

        # Check if album_artist is a generic compilation indicator
        if aa_lower in COMPILATION_INDICATORS:
            track.is_compilation = True
            if aa_lower in ("various artists", "various", "va"):
                track.album_artist = "Various Artists"
            logger.debug("Compilation detected (indicator): %s", track.album_artist)
            return

        # Check if album_artist starts with DJ and differs from track artist
        if aa_lower.startswith("dj ") and aa_lower != artist_lower:
            track.is_compilation = True
            track.album_artist = normalize_artist_name(track.album_artist)
            logger.debug("Compilation detected (DJ album artist): %s", track.album_artist)
            return

        # Check if album name contains compilation indicators
        for indicator in ("compilation", "soundtrack", "ost", "mixed by"):
            if indicator in album_lower:
                track.is_compilation = True
                if not track.album_artist:
                    track.album_artist = "Various Artists"
                logger.debug("Compilation detected (album name): %s", track.album)
                return

        # Check if album name matches a DJ Screw pattern and normalize it
        self._screw_handler.normalize_screw_album(track)
        if track.album_artist and "dj screw" in (track.album_artist or "").lower():
            track.is_compilation = True
            return

        # Check for "D.O.T.O." without chapter detail
        if album_lower.startswith("d.o.t.o") or album_lower.startswith("doto"):
            track.is_compilation = True
            if not track.album_artist:
                track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
            logger.debug("D.O.T.O. album detected: %s", track.album)
            return

        # Check for known DJ Screw album keywords
        for keyword in SCREW_ALBUM_KEYWORDS:
            if keyword in album_lower:
                track.is_compilation = True
                if not track.album_artist:
                    track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
                logger.debug(
                    "Compilation detected (Screw album keyword '%s'): %s",
                    keyword, track.album,
                )
                return

        # Check if album_artist tag is "DJ Screw"
        if "dj screw" in aa_lower or "djscrew" in aa_lower or "dj_screw" in aa_lower:
            track.is_compilation = True
            track.album_artist = "DJ Screw"
            self._screw_handler.normalize_screw_album(track)
            logger.debug("Compilation detected (DJ Screw in album_artist): %s", track.album)
            return

        # Check source folder structure for DJ patterns
        if track.original_path:
            self._detect_from_path(track)

    def _detect_from_path(self, track: Track) -> None:
        """Detect compilation from the original folder structure."""
        if not track.original_path:
            return

        parts = track.original_path.parts
        for part in parts:
            part_lower = part.lower().replace("_", " ").replace("-", " ").strip()
            for variant in DJ_SCREW_FOLDER_VARIANTS:
                if variant in part_lower or part_lower.startswith(variant):
                    track.is_compilation = True
                    if not track.album_artist:
                        track.album_artist = "DJ Screw"
                    logger.debug(
                        "Compilation detected from folder: '%s' -> album_artist='%s'",
                        part, track.album_artist,
                    )
                    return

            if part_lower.startswith("dj ") and part_lower != (track.artist or "").lower():
                track.is_compilation = True
                if not track.album_artist:
                    track.album_artist = normalize_artist_name(part)
                logger.debug(
                    "Compilation detected from DJ folder: '%s' -> album_artist='%s'",
                    part, track.album_artist,
                )
                return

    @staticmethod
    def album_looks_like_compilation(album: str) -> bool:
        """Quick check whether an album name looks like a compilation or mixtape.

        Used BEFORE the fuzzy search to decide whether to include the album
        in the API query.
        """
        if not album:
            return False
        album_lower = album.strip().lower()

        for dj in KNOWN_DJS:
            if dj in album_lower:
                return True

        if re.match(r"chapter\s*\d", album_lower):
            return True

        for keyword in SCREW_ALBUM_KEYWORDS:
            if keyword in album_lower:
                return True

        for indicator in (
            "bootleg", "mixtape", "mix tape", "compilation",
            "best of", "greatest hits", "soundtrack", "ost",
        ):
            if indicator in album_lower:
                return True

        if album_lower.startswith("dj "):
            return True

        return False

"""DJ Screw-specific track detection, normalization, and processing logic.

Extracted from BatchProcessor to improve separation of concerns.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.models.track import Track
from src.models.match_result import MatchCandidate
from src.models.processing_state import ProcessingState
from src.utils.file_utils import smart_title_case
from src.utils.logger import get_logger
from src.utils.constants import (
    SCREW_ALBUM_KEYWORDS,
    DJ_SCREW_FOLDER_VARIANTS,
    DJ_SCREW_CHAPTER_FORMAT,
    DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST,
)

if TYPE_CHECKING:
    from src.core.archive_org_fetcher import ArchiveOrgFetcher
    from src.core.fuzzy_matcher import FuzzyMatcher

logger = get_logger("core.dj_screw_handler")

# Regex separator for chapter patterns: "Chapter 051-Title", "Chapter 051. Title", etc.
_CHAPTER_SEP = r"[-–—:.\s]\s*"


class DJScrewHandler:
    """Handles DJ Screw track detection, album normalization, and IA matching."""

    def __init__(
        self,
        archive_org: ArchiveOrgFetcher,
        fuzzy: FuzzyMatcher,
    ) -> None:
        self._archive_org = archive_org
        self._fuzzy = fuzzy

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_dj_screw_track(track: Track) -> bool:
        """Check if a track belongs to a DJ Screw release.

        Returns True when any of these indicators are present:
        - album_artist contains "dj screw"
        - album matches a chapter pattern or known screw keyword
        - folder path contains DJ Screw indicators
        """
        aa = (track.album_artist or "").strip().lower()
        if "dj screw" in aa or "djscrew" in aa:
            return True

        album_lower = (track.album or "").strip().lower()
        if re.match(r"^chapter\s*\d{1,3}", album_lower):
            return True
        if album_lower.startswith("dj screw"):
            return True
        for keyword in SCREW_ALBUM_KEYWORDS:
            if keyword in album_lower:
                return True

        # Check folder path
        if track.original_path or track.file_path:
            path = track.original_path or track.file_path
            for part in path.parts:
                part_lower = part.lower().replace("_", " ").replace("-", " ").strip()
                for variant in DJ_SCREW_FOLDER_VARIANTS:
                    if variant in part_lower:
                        return True

        return False

    # ------------------------------------------------------------------
    # Chapter extraction
    # ------------------------------------------------------------------

    def extract_screw_chapter_info(
        self, track: Track,
    ) -> tuple[int, str | None] | None:
        """Extract DJ Screw chapter number and title from a track's metadata.

        Returns:
            Tuple of (chapter_num: int, chapter_title: str | None), or None
            if the track is not a DJ Screw chapter.
        """
        album = (track.album or "").strip()
        album_lower = album.lower()

        # Already-normalized format: "Chapter 051 - 9 Fo Shit"
        m = re.search(r"chapter\s*(\d{1,3})\s*[-–—:.]\s*(.+?)$", album_lower)
        if m:
            return int(m.group(1)), m.group(2).strip()

        # Raw "Chapter NNN" without separator (edge case)
        m = re.match(r"^chapter\s*(\d{1,3})$", album_lower)
        if m:
            return int(m.group(1)), None

        # Check album_artist to confirm it's DJ Screw even if album lacks "chapter"
        aa = (track.album_artist or "").strip().lower()
        if "dj screw" not in aa and "djscrew" not in aa:
            return None

        # DJ Screw is album_artist but album doesn't have "chapter".
        # Try the original folder name for a chapter pattern.
        if track.original_path:
            for part in track.original_path.parts:
                part_lower = part.lower().replace("_", " ").replace("-", " ").strip()
                m = re.match(r"chapter\s*(\d{1,3})\s+(.+)", part_lower)
                if m:
                    return int(m.group(1)), m.group(2).strip()

        # Reverse lookup by tape title via archive.org index
        tape_title = album
        screw_prefix = re.match(
            r"^dj\s*screw\s*[-–—:]\s*(.+)$", album_lower,
        )
        if screw_prefix:
            tape_title = screw_prefix.group(1).strip()

        if tape_title and self._archive_org:
            chapter_num = self._archive_org.lookup_chapter_by_title(tape_title)
            if chapter_num is not None:
                return chapter_num, tape_title

        return None

    # ------------------------------------------------------------------
    # Album normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_chapter_title(raw_title: str) -> str:
        """Clean up a chapter title extracted from a regex match."""
        title = raw_title.strip()
        title = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()
        title = re.sub(r"\s*bootleg\s*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"^\((.+)\)$", r"\1", title)
        return title

    def normalize_screw_album(self, track: Track) -> None:
        """Normalize a DJ Screw album name to the canonical chapter format.

        Sets track.album to the canonical format and ensures album_artist is
        set. Does nothing if the album doesn't match any DJ Screw pattern.
        """
        album_lower = (track.album or "").strip().lower()
        if not album_lower:
            return

        sep = _CHAPTER_SEP

        # 1. "Diary of the Originator: Chapter NNN - Title" or "D.O.T.O."
        diary_chapter = re.match(
            r"^(?:diary\s+of\s+the\s+originator|d\.?o\.?t\.?o\.?)\s*[:_]?\s*"
            rf"chapter\s*(\d{{1,3}})\s*{sep}(.+)$",
            album_lower,
        )
        if diary_chapter:
            chapter_num = int(diary_chapter.group(1))
            chapter_title = smart_title_case(
                self._clean_chapter_title(diary_chapter.group(2))
            )
            track.album = DJ_SCREW_CHAPTER_FORMAT.format(
                chapter=chapter_num, title=chapter_title,
            )
            track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
            logger.debug(
                "Screw album normalized (legacy prefix): '%s' -> '%s'",
                album_lower, track.album,
            )
            return

        # 2. "D.O.T.O. (Chapter NNN - Title) (Bootleg)"
        doto_match = re.match(
            r"^d\.?o\.?t\.?o\.?\s*[(\[]\s*chapter\s*(\d{1,3})\s*[-–—:.]\s*"
            r"(.+?)\s*[)\]](?:\s*[(\[]?\s*bootleg\s*[)\]]?)?\s*$",
            album_lower,
        )
        if doto_match:
            chapter_num = int(doto_match.group(1))
            chapter_title = smart_title_case(doto_match.group(2).strip())
            track.album = DJ_SCREW_CHAPTER_FORMAT.format(
                chapter=chapter_num, title=chapter_title,
            )
            track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
            logger.debug(
                "Screw album normalized (D.O.T.O.): '%s' -> '%s'",
                album_lower, track.album,
            )
            return

        # 3. "DJ Screw - Chapter NNN - Title" or "DJ Screw - Some Tape Name"
        screw_prefix = re.match(
            r"^dj\s*screw\s*[-–—:]\s*(.+)$", album_lower,
        )
        if screw_prefix:
            track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
            inner = screw_prefix.group(1).strip()
            inner_chapter = re.match(
                rf"^chapter\s*(\d{{1,3}})\s*{sep}(.+?)(?:\s*bootleg)?\s*$",
                inner,
            )
            if inner_chapter:
                chapter_num = int(inner_chapter.group(1))
                chapter_title = smart_title_case(
                    self._clean_chapter_title(inner_chapter.group(2))
                )
                track.album = DJ_SCREW_CHAPTER_FORMAT.format(
                    chapter=chapter_num, title=chapter_title,
                )
            else:
                tape_title = smart_title_case(inner)
                tape_title = re.sub(r"\s*\(\d{4}\)\s*$", "", tape_title).strip()
                track.album = f"DJ Screw - {tape_title}"
            logger.debug(
                "Screw album normalized (dj screw prefix): '%s' -> '%s'",
                album_lower, track.album,
            )
            return

        # 4. "Chapter NNN - Title" (bare chapter, no prefix)
        screw_chapter = re.match(
            rf"^chapter\s*(\d{{1,3}})\s*{sep}(.+?)(?:\s*bootleg)?\s*$",
            album_lower,
        )
        if screw_chapter:
            chapter_num = int(screw_chapter.group(1))
            chapter_title = smart_title_case(
                self._clean_chapter_title(screw_chapter.group(2))
            )
            track.album = DJ_SCREW_CHAPTER_FORMAT.format(
                chapter=chapter_num, title=chapter_title,
            )
            track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
            logger.debug(
                "Screw album normalized (chapter): '%s' -> '%s'",
                album_lower, track.album,
            )
            return

    # ------------------------------------------------------------------
    # Track-level matching against archive.org candidates
    # ------------------------------------------------------------------

    def match_track_to_ia_candidates(
        self,
        track: Track,
        candidates: list[MatchCandidate],
    ) -> MatchCandidate | None:
        """Find the best archive.org candidate matching this specific track.

        Uses fuzzy title matching and duration comparison to pick the right
        track from the chapter's candidate list.
        """
        track_title = (track.title or "").strip().lower()
        track_artist = (track.artist or "").strip().lower()
        track_duration = track.duration

        if not track_title and not track_artist:
            return None

        best: MatchCandidate | None = None
        best_score = 0.0

        for candidate in candidates:
            cand_title = (candidate.title or "").strip().lower()
            cand_artist = (candidate.artist or "").strip().lower()

            title_sim = self._fuzzy.similarity(track_title, cand_title)
            artist_sim = (
                self._fuzzy.similarity(track_artist, cand_artist)
                if track_artist
                else 50.0
            )

            dur_sim = 50.0
            if track_duration and candidate.duration:
                diff = abs(track_duration - candidate.duration)
                if diff <= 2.0:
                    dur_sim = 100.0
                elif diff <= 10.0:
                    dur_sim = 80.0
                elif diff <= 30.0:
                    dur_sim = 50.0
                else:
                    dur_sim = 10.0

            track_num_bonus = 0.0
            if (track.track_number and candidate.track_number
                    and track.track_number == candidate.track_number):
                track_num_bonus = 15.0

            score = (title_sim * 0.5) + (artist_sim * 0.2) + (dur_sim * 0.2) + track_num_bonus

            if score > best_score:
                best_score = score
                best = candidate

        if best and best_score >= 45.0:
            logger.debug(
                "Track-level match: '%s' -> '%s - %s' (score=%.1f)",
                track_title, best.artist, best.title, best_score,
            )
            return best

        logger.debug(
            "No track-level match for '%s' (best_score=%.1f)",
            track_title, best_score,
        )
        return None

"""Internet Archive metadata fetcher for Fingerprint Flow.

Provides track-level metadata from archive.org collections.  Primary use
case is the DJ Screw discography (380+ chapter tapes), but the design is
generic enough for any well-cataloged archive.org audio collection.

Two APIs are used:
- **Advanced Search** -- discover items in a collection.
- **Item Metadata** -- fetch per-file metadata (artist, title, duration, etc.).

No API key or authentication is required.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.models.match_result import MatchCandidate
from src.utils.logger import get_logger
from src.utils.rate_limiter import rate_limiter
from src.utils.constants import (
    ARCHIVE_ORG_RATE_LIMIT,
    ARCHIVE_ORG_TIMEOUT_SECONDS,
    ARCHIVE_ORG_DJ_SCREW_COLLECTION,
    ARCHIVE_ORG_SEARCH_URL,
    ARCHIVE_ORG_METADATA_URL,
    ARCHIVE_ORG_DOWNLOAD_URL,
    ARCHIVE_ORG_CACHE_FILENAME,
    ARCHIVE_ORG_CACHE_MAX_AGE_DAYS,
    MIN_API_RATE_INTERVAL,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_SECONDS,
    APP_NAME,
    APP_VERSION,
    DJ_SCREW_CHAPTER_FORMAT,
    DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST,
)

logger = get_logger("core.archive_org_fetcher")

_IA_RATE = max(ARCHIVE_ORG_RATE_LIMIT, MIN_API_RATE_INTERVAL)

# Files with these formats in archive.org are the original uploaded MP3s.
_AUDIO_FORMATS = frozenset({
    "VBR MP3", "128Kbps MP3", "64Kbps MP3", "256Kbps MP3", "320Kbps MP3",
    "Flac", "Ogg Vorbis", "24bit Flac",
})

# Regex to extract chapter number from archive.org item titles.
# Examples:
#   "DJ Screw - Chapter 051. 9 Fo Shit (1994)"
#   "DJ Screw - Chapter 001. Syrup Sippers (1993)"
_CHAPTER_TITLE_RE = re.compile(
    r"Chapter\s*(\d{1,3})\.\s*(.+?)(?:\s*\(\d{4}\))?\s*$",
    re.IGNORECASE,
)


def _retry_request(
    method: str,
    url: str,
    params: dict | None = None,
    max_retries: int = API_MAX_RETRIES,
    session: requests.Session | None = None,
) -> requests.Response | None:
    """Make an HTTP request with exponential-backoff retries.

    Args:
        method: HTTP method ("GET").
        url: Request URL.
        params: Query parameters.
        max_retries: Maximum number of attempts.
        session: Optional ``requests.Session`` for connection pooling.
            Falls back to a bare ``requests.request()`` if not provided.

    Returns:
        Response object, or None if all retries failed.
    """
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    requester = session or requests
    for attempt in range(1, max_retries + 1):
        try:
            resp = requester.request(
                method, url,
                params=params,
                headers=headers,
                timeout=ARCHIVE_ORG_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return resp
        except Exception as exc:
            wait_time = API_RETRY_BACKOFF_SECONDS * attempt
            if attempt < max_retries:
                logger.warning(
                    "archive.org request failed (attempt %d/%d): %s -- retrying in %.0fs",
                    attempt, max_retries, exc, wait_time,
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "archive.org request failed after %d attempts: %s",
                    max_retries, exc,
                )
    return None


class ArchiveOrgFetcher:
    """Fetches track metadata from Internet Archive collections.

    Typical usage::

        fetcher = ArchiveOrgFetcher(cache_dir=Path("./cache"))
        candidates = fetcher.fetch_dj_screw_chapter(51, "9 Fo Shit")
    """

    def __init__(self, cache_dir: Path | None = None, enabled: bool = True) -> None:
        """Initialize the archive.org fetcher.

        Args:
            cache_dir: Directory for the collection index cache file.
                Defaults to the current working directory.
            enabled: If False, all methods return empty results immediately.
        """
        self._enabled = enabled
        self._cache_dir = cache_dir or Path(".")
        # In-memory collection index: {chapter_num: {identifier, title, year}}
        self._screw_index: dict[int, dict[str, str]] | None = None
        # Persistent HTTP session for connection pooling
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"{APP_NAME}/{APP_VERSION}"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_dj_screw_chapter(
        self,
        chapter_num: int,
        chapter_title: str | None = None,
    ) -> list[MatchCandidate]:
        """Fetch all track candidates for a DJ Screw chapter.

        Looks up the chapter in the collection index, then fetches full
        item metadata to produce per-track MatchCandidates.

        Args:
            chapter_num: Chapter number (e.g. 51).
            chapter_title: Optional chapter title for logging/fallback search.

        Returns:
            List of MatchCandidate objects (one per track in the chapter).
        """
        if not self._enabled:
            return []

        logger.info(
            "archive.org: looking up DJ Screw Chapter %03d (%s)",
            chapter_num, chapter_title or "?",
        )

        index = self._get_screw_index()
        entry = index.get(chapter_num)

        if not entry:
            logger.info(
                "archive.org: Chapter %03d not found in collection index "
                "(%d chapters cached). Trying search fallback.",
                chapter_num, len(index),
            )
            # Fallback: search by title text
            entry = self._search_chapter_fallback(chapter_num, chapter_title)

        if not entry:
            logger.warning(
                "archive.org: Could not find Chapter %03d in DJ Screw discography",
                chapter_num,
            )
            return []

        identifier = entry["identifier"]
        return self.fetch_item_tracks(
            identifier,
            album_override=entry.get("title"),
            year_override=entry.get("year"),
        )

    def fetch_item_tracks(
        self,
        identifier: str,
        album_override: str | None = None,
        year_override: str | None = None,
    ) -> list[MatchCandidate]:
        """Fetch per-track metadata for an archive.org item.

        Args:
            identifier: Archive.org item identifier (e.g. "DJScrewChapter0519FoShit1994").
            album_override: Override album name (parsed from collection index).
            year_override: Override year (from collection index).

        Returns:
            List of MatchCandidate objects for original audio files in the item.
        """
        if not self._enabled:
            return []

        rate_limiter.wait("archive_org", _IA_RATE)
        url = f"{ARCHIVE_ORG_METADATA_URL}/{identifier}"
        resp = _retry_request("GET", url, session=self._session)
        if resp is None:
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("archive.org: failed to parse metadata JSON: %s", exc)
            return []

        if not data or isinstance(data, list):
            # Empty array means item not found
            logger.warning("archive.org: item '%s' not found", identifier)
            return []

        metadata = data.get("metadata", {})
        files = data.get("files", [])

        # Extract album-level info
        item_title = album_override or metadata.get("title", "")
        item_year = year_override or metadata.get("year")
        item_creator = metadata.get("creator", "")

        # Parse year to int
        year_int: int | None = None
        if item_year:
            try:
                year_int = int(str(item_year)[:4])
            except (ValueError, TypeError):
                pass

        # Build normalized album name from item title.
        # Archive.org titles look like "DJ Screw - Chapter 051. 9 Fo Shit (1994)".
        # We normalize to "Diary of the Originator: Chapter 051 - 9 Fo Shit".
        album_name = self._normalize_album_title(item_title)

        # Determine cover art URL
        cover_art_url = self._find_cover_art_url(identifier, files)

        # Filter to original audio files and build candidates
        candidates: list[MatchCandidate] = []
        for file_entry in files:
            if file_entry.get("source") != "original":
                continue
            file_format = file_entry.get("format", "")
            if file_format not in _AUDIO_FORMATS:
                continue

            candidate = self._parse_track_file(
                file_entry,
                album=album_name,
                album_artist=item_creator or DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST,
                year=year_int,
                cover_art_url=cover_art_url,
                identifier=identifier,
            )
            if candidate:
                candidates.append(candidate)

        # Sort by track number
        candidates.sort(key=lambda c: (c.track_number or 999, c.title))

        logger.info(
            "archive.org: fetched %d tracks for '%s'",
            len(candidates), identifier,
        )
        return candidates

    def search_collection(
        self,
        collection: str,
        query: str | None = None,
        max_results: int = 500,
    ) -> list[dict[str, Any]]:
        """Search for items in an archive.org collection.

        Args:
            collection: Collection identifier (e.g. "dj-screw-discography").
            query: Optional additional search terms.
            max_results: Maximum results to return.

        Returns:
            List of dicts with keys: identifier, title, year.
        """
        if not self._enabled:
            return []

        rate_limiter.wait("archive_org", _IA_RATE)

        q = f"collection:{collection}"
        if query:
            q += f" AND ({query})"

        params = {
            "q": q,
            "output": "json",
            "rows": max_results,
            "sort[]": "title asc",
            "fl[]": ["identifier", "title", "year"],
        }

        resp = _retry_request("GET", ARCHIVE_ORG_SEARCH_URL, params=params, session=self._session)
        if resp is None:
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("archive.org: failed to parse search JSON: %s", exc)
            return []

        docs = data.get("response", {}).get("docs", [])
        logger.debug("archive.org: search returned %d items for '%s'", len(docs), q)
        return docs

    def search_by_text(
        self,
        title: str | None = None,
        artist: str | None = None,
        max_results: int = 5,
    ) -> list[MatchCandidate]:
        """Fallback search across all of archive.org for audio items.

        Used when MusicBrainz/Discogs confidence is low.  This is NOT
        limited to a specific collection -- it searches all audio on archive.org.

        Args:
            title: Track or album title.
            artist: Artist name.
            max_results: Maximum results.

        Returns:
            List of MatchCandidate objects (album-level, not per-track).
        """
        if not self._enabled:
            return []

        if not any([title, artist]):
            return []

        rate_limiter.wait("archive_org", _IA_RATE)

        query_parts = []
        if title:
            query_parts.append(title)
        if artist:
            query_parts.append(f"creator:{artist}")
        query_parts.append("mediatype:audio")

        params = {
            "q": " AND ".join(query_parts),
            "output": "json",
            "rows": max_results,
            "fl[]": ["identifier", "title", "year", "creator", "description"],
        }

        resp = _retry_request("GET", ARCHIVE_ORG_SEARCH_URL, params=params, session=self._session)
        if resp is None:
            return []

        try:
            data = resp.json()
        except Exception as exc:
            logger.error("archive.org: failed to parse search JSON: %s", exc)
            return []

        candidates: list[MatchCandidate] = []
        for doc in data.get("response", {}).get("docs", [])[:max_results]:
            # Parse "Artist - Album (Year)" from title if possible
            ia_title = doc.get("title", "")
            ia_creator = doc.get("creator", "")
            ia_year = doc.get("year")

            year_int: int | None = None
            if ia_year:
                try:
                    year_int = int(str(ia_year)[:4])
                except (ValueError, TypeError):
                    pass

            candidate = MatchCandidate(
                title=ia_title,
                artist=ia_creator if isinstance(ia_creator, str) else "",
                album=ia_title,
                album_artist=ia_creator if isinstance(ia_creator, str) else "",
                year=year_int,
                source="archive_org",
                source_id=doc.get("identifier", ""),
            )
            candidates.append(candidate)

        logger.debug("archive.org: text search returned %d results", len(candidates))
        return candidates

    # ------------------------------------------------------------------
    # Collection index cache
    # ------------------------------------------------------------------

    def _get_screw_index(self) -> dict[int, dict[str, str]]:
        """Get or build the DJ Screw chapter index.

        Returns the cached in-memory index, loading from disk or fetching
        from archive.org as needed.
        """
        if self._screw_index is not None:
            return self._screw_index

        # Try loading from disk cache
        cache_path = self._cache_dir / ARCHIVE_ORG_CACHE_FILENAME
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                cached_at = raw.get("cached_at", "")
                entries = raw.get("entries", {})

                # Check age
                if cached_at:
                    cached_dt = datetime.fromisoformat(cached_at)
                    age_days = (datetime.now(timezone.utc) - cached_dt).days
                    if age_days <= ARCHIVE_ORG_CACHE_MAX_AGE_DAYS:
                        self._screw_index = {int(k): v for k, v in entries.items()}
                        logger.info(
                            "archive.org: loaded DJ Screw index from cache "
                            "(%d chapters, %d days old)",
                            len(self._screw_index), age_days,
                        )
                        return self._screw_index
                    else:
                        logger.info(
                            "archive.org: cache expired (%d days old), refreshing",
                            age_days,
                        )
            except Exception as exc:
                logger.warning("archive.org: failed to load cache: %s", exc)

        # Fetch from archive.org
        self._screw_index = self._build_screw_index()

        # Save to disk
        self._save_screw_index(cache_path)

        return self._screw_index

    def _build_screw_index(self) -> dict[int, dict[str, str]]:
        """Fetch the full DJ Screw collection and build a chapter-number index."""
        logger.info("archive.org: building DJ Screw collection index (one-time fetch)...")

        docs = self.search_collection(
            collection=ARCHIVE_ORG_DJ_SCREW_COLLECTION,
            max_results=500,
        )

        index: dict[int, dict[str, str]] = {}
        for doc in docs:
            title = doc.get("title", "")
            identifier = doc.get("identifier", "")
            year = str(doc.get("year", ""))

            # Extract chapter number from title
            match = _CHAPTER_TITLE_RE.search(title)
            if match:
                chapter_num = int(match.group(1))
                chapter_title = match.group(2).strip()
                index[chapter_num] = {
                    "identifier": identifier,
                    "title": title,
                    "chapter_title": chapter_title,
                    "year": year,
                }

        logger.info(
            "archive.org: indexed %d chapters from %d items",
            len(index), len(docs),
        )
        return index

    def lookup_chapter_by_title(self, tape_title: str) -> int | None:
        """Reverse-lookup a DJ Screw chapter number by tape title.

        Useful when the user's folder is named "DJ Screw - Only Rollin Red"
        (no chapter number).  Fuzzy-matches the title against the cached
        screw index's chapter_title values.

        Args:
            tape_title: The tape title to search for (e.g. "Only Rollin Red").

        Returns:
            Chapter number if a good match is found, or None.
        """
        if not self._enabled or not tape_title:
            return None

        from rapidfuzz import fuzz

        index = self._get_screw_index()
        if not index:
            return None

        needle = tape_title.lower().strip()
        best_chapter: int | None = None
        best_score = 0.0

        for chapter_num, entry in index.items():
            ct = (entry.get("chapter_title") or "").lower().strip()
            if not ct:
                continue

            # Weighted fuzzy comparison
            score = max(
                fuzz.ratio(needle, ct),
                fuzz.token_sort_ratio(needle, ct),
                fuzz.partial_ratio(needle, ct),
            )
            if score > best_score:
                best_score = score
                best_chapter = chapter_num

        if best_chapter is not None and best_score >= 75:
            logger.info(
                "archive.org: reverse-matched tape title '%s' to Chapter %03d "
                "(score=%.0f%%)",
                tape_title, best_chapter, best_score,
            )
            return best_chapter

        logger.debug(
            "archive.org: no good title match for '%s' (best score=%.0f%%)",
            tape_title, best_score,
        )
        return None

    def _save_screw_index(self, cache_path: Path) -> None:
        """Save the DJ Screw chapter index to disk."""
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "collection": ARCHIVE_ORG_DJ_SCREW_COLLECTION,
                "entries": {str(k): v for k, v in self._screw_index.items()},
            }
            cache_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("archive.org: saved index cache to %s", cache_path)
        except Exception as exc:
            logger.warning("archive.org: failed to save cache: %s", exc)

    def _search_chapter_fallback(
        self,
        chapter_num: int,
        chapter_title: str | None,
    ) -> dict[str, str] | None:
        """Search archive.org for a chapter not in the cached index."""
        query = f"chapter {chapter_num:03d}"
        if chapter_title:
            query += f" {chapter_title}"

        docs = self.search_collection(
            collection=ARCHIVE_ORG_DJ_SCREW_COLLECTION,
            query=query,
            max_results=5,
        )

        # Try to find the right chapter in results
        for doc in docs:
            title = doc.get("title", "")
            match = _CHAPTER_TITLE_RE.search(title)
            if match and int(match.group(1)) == chapter_num:
                return {
                    "identifier": doc.get("identifier", ""),
                    "title": title,
                    "year": str(doc.get("year", "")),
                }

        # No exact chapter match; return first result if any
        if docs:
            doc = docs[0]
            return {
                "identifier": doc.get("identifier", ""),
                "title": doc.get("title", ""),
                "year": str(doc.get("year", "")),
            }
        return None

    # ------------------------------------------------------------------
    # Track parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_track_file(
        file_entry: dict[str, Any],
        album: str,
        album_artist: str,
        year: int | None,
        cover_art_url: str | None,
        identifier: str,
    ) -> MatchCandidate | None:
        """Parse a single archive.org file entry into a MatchCandidate.

        Archive.org file entries for MP3s look like:
            {
                "name": "101. Champ # Mike - Keep # Get.mp3",
                "title": "Keep # Get",
                "artist": "Champ # Mike",
                "album": "Chapter 051. 9 Fo Shit",
                "track": "101/107",
                "length": "737.15",
                "format": "VBR MP3",
                ...
            }

        Args:
            file_entry: Raw file dict from the archive.org metadata API.
            album: Normalized album name to use.
            album_artist: Album artist name.
            year: Release year.
            cover_art_url: URL to album cover art.
            identifier: Archive.org item identifier.

        Returns:
            MatchCandidate, or None if the entry lacks essential data.
        """
        title = file_entry.get("title", "")
        artist = file_entry.get("artist") or file_entry.get("creator", "")
        track_str = file_entry.get("track", "")
        length_str = file_entry.get("length", "")
        genre = file_entry.get("genre", "")

        # Normalize backticks to apostrophes (common in archive.org data)
        title = title.replace("`", "'")
        artist = artist.replace("`", "'")

        if not title and not artist:
            # Try to parse from filename: "101. Artist - Title.mp3"
            name = file_entry.get("name", "")
            parsed = _parse_ia_filename(name)
            if parsed:
                title = parsed.get("title", "")
                artist = parsed.get("artist", "")
                if not track_str:
                    track_str = parsed.get("track", "")

        if not title:
            return None

        # Parse track number from "101/107" or "1/19" format.
        # Archive.org sometimes uses disc-prefixed numbering: 101 = disc 1, track 1.
        track_number: int | None = None
        total_tracks: int | None = None
        disc_number: int | None = None
        if track_str:
            parts = track_str.split("/")
            try:
                raw_num = int(parts[0])
                # If track number > 100, strip the disc prefix: 101 -> 1, 212 -> 12
                if raw_num > 100:
                    disc_number = raw_num // 100
                    track_number = raw_num % 100
                else:
                    track_number = raw_num
            except (ValueError, TypeError):
                pass
            if len(parts) > 1:
                try:
                    raw_total = int(parts[1])
                    if raw_total > 100:
                        total_tracks = raw_total % 100
                    else:
                        total_tracks = raw_total
                except (ValueError, TypeError):
                    pass

        # Parse duration
        duration: float | None = None
        if length_str:
            try:
                duration = float(length_str)
            except (ValueError, TypeError):
                pass

        return MatchCandidate(
            title=title,
            artist=artist,
            album=album,
            album_artist=album_artist,
            track_number=track_number,
            total_tracks=total_tracks,
            disc_number=disc_number,
            year=year,
            genre=genre if genre else None,
            duration=duration,
            cover_art_url=cover_art_url,
            source="archive_org",
            source_id=f"{identifier}/{file_entry.get('name', '')}",
        )

    @staticmethod
    def _normalize_album_title(ia_title: str) -> str:
        """Normalize an archive.org item title to the project's album format.

        Input:  "DJ Screw - Chapter 051. 9 Fo Shit (1994)"
        Output: "Chapter 051 - 9 Fo Shit"

        Falls back to the raw title if it doesn't match the expected pattern.

        Args:
            ia_title: Raw title from archive.org metadata.

        Returns:
            Normalized album name string.
        """
        match = _CHAPTER_TITLE_RE.search(ia_title)
        if match:
            chapter_num = int(match.group(1))
            chapter_title = match.group(2).strip()
            return DJ_SCREW_CHAPTER_FORMAT.format(
                chapter=chapter_num,
                title=chapter_title,
            )

        # Strip "DJ Screw - " prefix and trailing "(YYYY)" if present
        cleaned = re.sub(r"^DJ\s+Screw\s*[-–—:]\s*", "", ia_title, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*\(\d{4}\)\s*$", "", cleaned)
        return cleaned.strip() or ia_title

    @staticmethod
    def _find_cover_art_url(identifier: str, files: list[dict[str, Any]]) -> str | None:
        """Find the best cover art URL from an item's file list.

        Looks for files named Front.jpg, cover.jpg, folder.jpg, etc.

        Args:
            identifier: Archive.org item identifier.
            files: File list from item metadata.

        Returns:
            Direct download URL for the cover image, or None.
        """
        # Priority order for cover art filenames
        cover_names = {"front.jpg", "front.png", "cover.jpg", "cover.png",
                       "folder.jpg", "folder.png", "albumartsmall.jpg"}

        for file_entry in files:
            name_lower = file_entry.get("name", "").lower()
            if name_lower in cover_names:
                return f"{ARCHIVE_ORG_DOWNLOAD_URL}/{identifier}/{file_entry['name']}"

        # Fallback: look for any Item Image format
        for file_entry in files:
            if file_entry.get("format") == "Item Image":
                return f"{ARCHIVE_ORG_DOWNLOAD_URL}/{identifier}/{file_entry['name']}"

        return None


def _parse_ia_filename(filename: str) -> dict[str, str] | None:
    """Parse an archive.org audio filename into components.

    Expected patterns:
        "101. Champ # Mike - Keep # Get.mp3"
        "01 - Artist Name - Track Title.mp3"

    Args:
        filename: Raw filename string.

    Returns:
        Dict with keys: track, artist, title. Or None if unparseable.
    """
    # Strip extension
    stem = re.sub(r"\.[^.]+$", "", filename)
    if not stem:
        return None

    # Pattern: "NNN. Artist - Title"
    match = re.match(r"^(\d+)\.\s*(.+?)\s*-\s*(.+)$", stem)
    if match:
        return {
            "track": match.group(1),
            "artist": match.group(2).strip().replace("`", "'"),
            "title": match.group(3).strip().replace("`", "'"),
        }

    # Pattern: "NN - Artist - Title"
    match = re.match(r"^(\d+)\s*-\s*(.+?)\s*-\s*(.+)$", stem)
    if match:
        return {
            "track": match.group(1),
            "artist": match.group(2).strip().replace("`", "'"),
            "title": match.group(3).strip().replace("`", "'"),
        }

    return None

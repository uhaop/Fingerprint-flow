"""Metadata fetcher -- multi-source lookup from MusicBrainz, Discogs, and Cover Art Archive."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Callable, TypeVar

import musicbrainzngs
import requests

from src.models.match_result import MatchCandidate
from src.utils.logger import get_logger
from src.utils.rate_limiter import rate_limiter
from src.utils.constants import (
    MUSICBRAINZ_APP_NAME,
    MUSICBRAINZ_APP_VERSION,
    MUSICBRAINZ_CONTACT,
    MUSICBRAINZ_RATE_LIMIT,
    DISCOGS_RATE_LIMIT,
    MIN_API_RATE_INTERVAL,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_SECONDS,
    API_TIMEOUT_SECONDS,
    COVER_ART_TIMEOUT_SECONDS,
)

logger = get_logger("core.metadata_fetcher")

T = TypeVar("T")

# More conservative rate limits to avoid getting blocked
_MB_RATE = max(MUSICBRAINZ_RATE_LIMIT, MIN_API_RATE_INTERVAL)
_DISCOGS_RATE = max(DISCOGS_RATE_LIMIT, MIN_API_RATE_INTERVAL)


def _retry(
    func: Callable[[], T],
    service_name: str,
    max_retries: int = API_MAX_RETRIES,
) -> T | None:
    """Retry a function call with exponential backoff on failure.

    Args:
        func: Callable to execute.
        service_name: Name of the service (for logging).
        max_retries: Maximum number of attempts.

    Returns:
        The function's return value, or None if all retries failed.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as e:
            wait_time = API_RETRY_BACKOFF_SECONDS * attempt
            if attempt < max_retries:
                logger.warning(
                    "%s request failed (attempt %d/%d): %s -- retrying in %.0fs",
                    service_name, attempt, max_retries, e, wait_time,
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "%s request failed after %d attempts: %s",
                    service_name, max_retries, e,
                )
    return None


class MetadataFetcher:
    """Fetches full track metadata from MusicBrainz, Discogs, and Cover Art Archive.

    All APIs used are free. MusicBrainz requires a user-agent; Discogs requires
    a personal access token.
    """

    # Sentinel to distinguish "not cached" from "cached as None (404)"
    _NOT_CACHED = object()

    def __init__(
        self,
        discogs_token: str | None = None,
        api_cache: object | None = None,
    ) -> None:
        """Initialize the metadata fetcher.

        Args:
            discogs_token: Optional Discogs personal access token.
            api_cache: Optional ``ApiCacheRepository`` for caching API
                responses across runs.
        """
        self._discogs_token = discogs_token
        self._api_cache = api_cache
        # Per-release cover art cache: release_id -> bytes | None
        self._cover_art_cache: dict[str, bytes | None] = {}

        # Persistent HTTP session -- reuses TCP/TLS connections across requests
        # to Discogs and Cover Art Archive, saving ~100-200ms per request.
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": f"{MUSICBRAINZ_APP_NAME}/{MUSICBRAINZ_APP_VERSION}",
        })

        # Configure MusicBrainz user agent (required by their TOS)
        musicbrainzngs.set_useragent(
            MUSICBRAINZ_APP_NAME,
            MUSICBRAINZ_APP_VERSION,
            MUSICBRAINZ_CONTACT,
        )

    # --- MusicBrainz ---

    def fetch_recording(self, recording_id: str) -> MatchCandidate | None:
        """Fetch full recording metadata from MusicBrainz by recording MBID.

        Args:
            recording_id: MusicBrainz recording MBID.

        Returns:
            A MatchCandidate populated with metadata, or None on failure.
        """
        if not recording_id:
            return None

        # --- Cache check ---
        cache_key = f"mb_recording:{recording_id}"
        if self._api_cache is not None:
            cached = self._api_cache.get(cache_key)
            if cached is not None:
                logger.debug("API cache hit: %s", cache_key)
                return self._parse_mb_recording(recording_id, cached)

        try:

            def _do_fetch():
                rate_limiter.wait("musicbrainz", _MB_RATE)
                return musicbrainzngs.get_recording_by_id(
                    recording_id,
                    includes=["artists", "releases"],
                )

            result = _retry(_do_fetch, "MusicBrainz")
            if result is None:
                return None

            # --- Cache store ---
            if self._api_cache is not None:
                try:
                    self._api_cache.put(cache_key, result)
                except Exception:
                    pass  # Cache write failure is non-fatal

            return self._parse_mb_recording(recording_id, result)

        except musicbrainzngs.ResponseError as e:
            logger.error("MusicBrainz recording lookup failed: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected MusicBrainz error: %s", e)
            return None

    def _parse_mb_recording(self, recording_id: str, result: dict) -> MatchCandidate | None:
        """Parse a MusicBrainz get_recording_by_id result into a MatchCandidate.

        Shared by both the live API path and the cache-hit path.

        Args:
            recording_id: MusicBrainz recording MBID.
            result: Raw API response dict.

        Returns:
            A MatchCandidate, or None if essential data is missing.
        """
        recording = result.get("recording", {})
        candidate = MatchCandidate(
            title=recording.get("title", ""),
            musicbrainz_recording_id=recording_id,
            source="musicbrainz",
            source_id=recording_id,
        )

        # Duration (MusicBrainz stores in milliseconds)
        length_ms = recording.get("length")
        if length_ms:
            candidate.duration = int(length_ms) / 1000.0

        # Artist
        artist_credit = recording.get("artist-credit", [])
        if artist_credit:
            candidate.artist = self._format_artist_credit(artist_credit)

        # Release info (pick first release)
        releases = recording.get("release-list", [])
        if releases:
            release = releases[0]
            candidate.album = release.get("title", "")
            candidate.musicbrainz_release_id = release.get("id")

            # Year from release date
            date_str = release.get("date", "")
            if date_str and len(date_str) >= 4:
                try:
                    candidate.year = int(date_str[:4])
                except ValueError:
                    pass

            # Track number from medium-list
            medium_list = release.get("medium-list", [])
            if medium_list:
                medium = medium_list[0]
                candidate.disc_number = medium.get("position")
                candidate.total_discs = len(medium_list)
                track_list = medium.get("track-list", [])
                if track_list:
                    track_info = track_list[0]
                    try:
                        candidate.track_number = int(track_info.get("number", 0))
                    except (ValueError, TypeError):
                        pass
                    candidate.total_tracks = medium.get("track-count")

            # Cover art URL
            if candidate.musicbrainz_release_id:
                candidate.cover_art_url = self._get_cover_art_url(
                    candidate.musicbrainz_release_id
                )

        logger.debug(
            "MusicBrainz recording: %s - %s (%s)",
            candidate.artist, candidate.title, candidate.album,
        )
        return candidate

    # Lucene special characters that break MusicBrainz phrase queries
    _LUCENE_SPECIAL_RE = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')

    @classmethod
    def _clean_for_search(cls, text: str) -> str:
        """Strip Lucene special characters and normalize whitespace.

        Args:
            text: Raw search term from tags or filename.

        Returns:
            Cleaned string safe for MusicBrainz term queries.
        """
        if not text:
            return ""
        cleaned = cls._LUCENE_SPECIAL_RE.sub(" ", text)
        return " ".join(cleaned.split())

    @staticmethod
    def _search_cache_key(prefix: str, title: str | None, artist: str | None, album: str | None) -> str:
        """Build a deterministic cache key for a search query."""
        raw = f"{title or ''}|{artist or ''}|{album or ''}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"{prefix}:{h}"

    def search_musicbrainz(
        self,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        limit: int = 5,
    ) -> list[MatchCandidate]:
        """Search MusicBrainz for recordings matching the given criteria.

        Uses term-based matching (not exact phrase) so that minor spelling
        differences (e.g. "Amerikas" vs "America's", "2pac" vs "2Pac")
        don't kill the search.

        Args:
            title: Track title to search for.
            artist: Artist name to search for.
            album: Album name to search for.
            limit: Maximum number of results.

        Returns:
            List of MatchCandidate objects from the search results.
        """
        if not any([title, artist]):
            return []

        # --- Cache check ---
        cache_key = self._search_cache_key("mb_search", title, artist, album)
        if self._api_cache is not None:
            cached = self._api_cache.get(cache_key)
            if cached is not None:
                logger.debug("API cache hit: %s", cache_key)
                return self._parse_mb_search_results(cached)

        try:
            # Build keyword arguments -- musicbrainzngs handles query
            # construction; strict=False gives term matching (forgiving)
            search_kwargs: dict = {"limit": limit, "strict": False}
            if title:
                search_kwargs["recording"] = self._clean_for_search(title)
            if artist:
                search_kwargs["artist"] = self._clean_for_search(artist)
            if album:
                search_kwargs["release"] = self._clean_for_search(album)

            def _do_search():
                rate_limiter.wait("musicbrainz", _MB_RATE)
                return musicbrainzngs.search_recordings(**search_kwargs)

            result = _retry(_do_search, "MusicBrainz")
            if result is None:
                return []

            # --- Cache store ---
            if self._api_cache is not None:
                try:
                    self._api_cache.put(cache_key, result)
                except Exception:
                    pass

            return self._parse_mb_search_results(result)

        except musicbrainzngs.ResponseError as e:
            logger.error("MusicBrainz search failed: %s", e)
            return []
        except Exception as e:
            logger.error("Unexpected MusicBrainz search error: %s", e)
            return []

    def _parse_mb_search_results(self, result: dict) -> list[MatchCandidate]:
        """Parse a MusicBrainz search_recordings result into candidates.

        Shared by both the live API path and the cache-hit path.
        """
        candidates = []
        for rec in result.get("recording-list", []):
            candidate = MatchCandidate(
                title=rec.get("title", ""),
                musicbrainz_recording_id=rec.get("id", ""),
                source="musicbrainz",
                source_id=rec.get("id", ""),
            )

            # Artist
            artist_credit = rec.get("artist-credit", [])
            if artist_credit:
                candidate.artist = self._format_artist_credit(artist_credit)

            # Duration
            length_ms = rec.get("length")
            if length_ms:
                candidate.duration = int(length_ms) / 1000.0

            # Release
            releases = rec.get("release-list", [])
            if releases:
                release = releases[0]
                candidate.album = release.get("title", "")
                candidate.musicbrainz_release_id = release.get("id")
                date_str = release.get("date", "")
                if date_str and len(date_str) >= 4:
                    try:
                        candidate.year = int(date_str[:4])
                    except ValueError:
                        pass

            # MB search returns a score (0-100)
            ext_score = rec.get("ext:score")
            if ext_score:
                try:
                    candidate.confidence = float(ext_score)
                except (ValueError, TypeError):
                    pass

            candidates.append(candidate)

        logger.debug("MusicBrainz search returned %d results", len(candidates))
        return candidates

    # --- Discogs ---

    def search_discogs(
        self,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        limit: int = 5,
    ) -> list[MatchCandidate]:
        """Search Discogs for releases matching the given criteria.

        Args:
            title: Track title to search for.
            artist: Artist name to search for.
            album: Album name to search for.
            limit: Maximum number of results.

        Returns:
            List of MatchCandidate objects.
        """
        if not self._discogs_token:
            logger.debug("Discogs token not configured, skipping Discogs search")
            return []

        if not any([title, artist, album]):
            return []

        # --- Cache check ---
        cache_key = self._search_cache_key("discogs_search", title, artist, album)
        if self._api_cache is not None:
            cached = self._api_cache.get(cache_key)
            if cached is not None:
                logger.debug("API cache hit: %s", cache_key)
                return self._parse_discogs_results(cached, title)

        try:
            rate_limiter.wait("discogs", _DISCOGS_RATE)

            # Build search query
            query = " ".join(filter(None, [artist, title, album]))

            response = self._session.get(
                "https://api.discogs.com/database/search",
                params={
                    "q": query,
                    "type": "release",
                    "per_page": limit,
                },
                headers={
                    "Authorization": f"Discogs token={self._discogs_token}",
                },
                timeout=API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()

            # --- Cache store ---
            if self._api_cache is not None:
                try:
                    self._api_cache.put(cache_key, data)
                except Exception:
                    pass

            return self._parse_discogs_results(data, title)

        except requests.RequestException as e:
            logger.error("Discogs search failed: %s", e)
            return []
        except Exception as e:
            logger.error("Unexpected Discogs error: %s", e)
            return []

    def _parse_discogs_results(self, data: dict, title: str | None) -> list[MatchCandidate]:
        """Parse a Discogs search response into candidates.

        Shared by both the live API path and the cache-hit path.
        """
        candidates = []
        for item in data.get("results", []):
            # Discogs title format: "Artist - Album"
            discogs_title = item.get("title", "")
            parts = discogs_title.split(" - ", 1)
            disc_artist = parts[0].strip() if len(parts) > 1 else ""
            disc_album = parts[1].strip() if len(parts) > 1 else discogs_title

            candidate = MatchCandidate(
                title=title or "",  # Discogs search is release-level
                artist=disc_artist,
                album=disc_album,
                source="discogs",
                source_id=str(item.get("id", "")),
            )

            # Year
            year_str = item.get("year")
            if year_str:
                try:
                    candidate.year = int(year_str)
                except (ValueError, TypeError):
                    pass

            # Genre
            genres = item.get("genre", [])
            if genres:
                candidate.genre = genres[0]

            # Cover art
            cover_url = item.get("cover_image")
            if cover_url:
                candidate.cover_art_url = cover_url

            candidates.append(candidate)

        logger.debug("Discogs search returned %d results", len(candidates))
        return candidates

    # --- Cover Art Archive ---

    def fetch_cover_art(self, release_id: str) -> bytes | None:
        """Download front cover art from the Cover Art Archive.

        Results are cached per release_id so that multiple tracks on the
        same album only trigger a single HTTP request.

        Args:
            release_id: MusicBrainz release MBID.

        Returns:
            Raw image bytes, or None if not available.
        """
        if not release_id:
            return None

        # Check cache first (None is a valid cached value meaning "no art")
        cached = self._cover_art_cache.get(release_id, self._NOT_CACHED)
        if cached is not self._NOT_CACHED:
            logger.debug("Cover art cache hit for release %s", release_id)
            return cached  # type: ignore[return-value]

        url = f"https://coverartarchive.org/release/{release_id}/front-500"

        try:
            response = self._session.get(url, timeout=COVER_ART_TIMEOUT_SECONDS, allow_redirects=True)
            if response.status_code == 200:
                logger.debug("Downloaded cover art for release %s", release_id)
                self._cover_art_cache[release_id] = response.content
                return response.content
            elif response.status_code == 404:
                logger.debug("No cover art found for release %s", release_id)
                self._cover_art_cache[release_id] = None
                return None
            else:
                logger.warning(
                    "Cover Art Archive returned %d for release %s",
                    response.status_code, release_id,
                )
                self._cover_art_cache[release_id] = None
                return None
        except requests.RequestException as e:
            logger.error("Cover art download failed: %s", e)
            return None

    # --- Helpers ---

    def _get_cover_art_url(self, release_id: str) -> str | None:
        """Build a Cover Art Archive URL for a release.

        Args:
            release_id: MusicBrainz release MBID.

        Returns:
            URL string, or None.
        """
        if release_id:
            return f"https://coverartarchive.org/release/{release_id}/front-500"
        return None

    @staticmethod
    def _format_artist_credit(artist_credit: list) -> str:
        """Format a MusicBrainz artist-credit list into a single string.

        Args:
            artist_credit: MusicBrainz artist-credit list.

        Returns:
            Formatted artist string (e.g. "Artist A feat. Artist B").
        """
        parts = []
        for credit in artist_credit:
            if isinstance(credit, dict):
                artist = credit.get("artist", {})
                name = credit.get("name") or artist.get("name", "")
                joinphrase = credit.get("joinphrase", "")
                parts.append(name + joinphrase)
            elif isinstance(credit, str):
                parts.append(credit)
        return "".join(parts).strip()

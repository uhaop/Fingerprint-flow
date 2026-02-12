"""Audio fingerprinting via AcoustID/Chromaprint."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import acoustid

from src.models.track import Track
from src.models.match_result import MatchCandidate
from src.utils.logger import get_logger
from src.utils.rate_limiter import rate_limiter
from src.utils.constants import MUSICBRAINZ_RATE_LIMIT, DEFAULT_MAX_CONCURRENT_FINGERPRINTS

logger = get_logger("core.fingerprinter")


class Fingerprinter:
    """Generates audio fingerprints and looks up AcoustID matches.

    Requires:
        - Chromaprint's `fpcalc` binary installed and on PATH.
        - A valid AcoustID API key.
    """

    def __init__(self, api_key: str, api_cache: object | None = None) -> None:
        """Initialize the fingerprinter.

        Args:
            api_key: AcoustID API key.
            api_cache: Optional ``ApiCacheRepository`` for caching AcoustID
                lookup results.
        """
        self._api_key = api_key
        self._api_key_warned = False
        self._api_cache = api_cache

    def fingerprint(self, track: Track) -> Track:
        """Generate a Chromaprint fingerprint for a track.

        Populates track.fingerprint and track.duration (from fpcalc).

        Args:
            track: Track to fingerprint.

        Returns:
            The same Track with fingerprint and duration populated.
        """
        path = track.file_path
        if not path.exists():
            logger.warning("File not found for fingerprinting: %s", path)
            return track

        try:
            duration, fingerprint = acoustid.fingerprint_file(str(path))
            track.fingerprint = fingerprint
            # Use fpcalc duration if we don't already have one from tags
            if track.duration is None:
                track.duration = duration
            logger.debug("Fingerprinted: %s (duration=%.1fs)", path.name, duration)
        except acoustid.FingerprintGenerationError as e:
            logger.error("Fingerprint generation failed for %s: %s", path.name, e)
            track.error_message = f"Fingerprint error: {e}"
        except Exception as e:
            logger.error("Unexpected fingerprint error for %s: %s", path.name, e)
            track.error_message = f"Fingerprint error: {e}"

        return track

    def _acoustid_cache_key(self, fingerprint: str, duration: float) -> str:
        """Build a deterministic cache key for an AcoustID lookup."""
        fp_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
        return f"acoustid:{fp_hash}:{int(duration)}"

    def lookup(self, track: Track) -> list[tuple[str, float, str | None, str | None]]:
        """Look up a fingerprint against the AcoustID database.

        Args:
            track: Track with fingerprint populated.

        Returns:
            List of (acoustid_id, score, recording_id, recording_title) tuples,
            sorted by score descending. Returns empty list on failure.
        """
        if not track.fingerprint or track.duration is None:
            logger.warning("Cannot lookup: missing fingerprint or duration for %s", track.file_path.name)
            return []

        # --- Cache check ---
        cache_key = self._acoustid_cache_key(track.fingerprint, track.duration)
        if self._api_cache is not None:
            cached = self._api_cache.get(cache_key)
            if cached is not None:
                logger.debug("API cache hit: %s", cache_key)
                return [(m[0], m[1], m[2], m[3]) for m in cached]

        try:
            rate_limiter.wait("acoustid", MUSICBRAINZ_RATE_LIMIT)

            results = acoustid.lookup(
                self._api_key,
                track.fingerprint,
                track.duration,
                meta="recordings",
            )

            # Check for API-level errors before parsing
            if isinstance(results, dict) and results.get("status") == "error":
                err_info = results.get("error", {})
                err_msg = err_info.get("message", "unknown error")
                err_code = err_info.get("code", "?")
                if "invalid api key" in err_msg.lower():
                    # Only log this once to avoid spamming
                    if not getattr(self, "_api_key_warned", False):
                        logger.error(
                            "AcoustID API key is INVALID (code %s: %s). "
                            "Get a free key at https://acoustid.org/new-application "
                            "and update acoustid_api_key in config/config.yaml.",
                            err_code, err_msg,
                        )
                        self._api_key_warned = True
                else:
                    logger.error(
                        "AcoustID API error for %s (code %s): %s",
                        track.file_path.name, err_code, err_msg,
                    )
                return []

            matches: list[tuple[str, float, str | None, str | None]] = []

            for score, recording_id, title, artist in acoustid.parse_lookup_result(results):
                matches.append((
                    recording_id or "",
                    score,
                    recording_id,
                    title,
                ))
                logger.debug(
                    "AcoustID match: score=%.2f, recording=%s, title=%s, artist=%s",
                    score, recording_id, title, artist,
                )

            # Sort by score descending
            matches.sort(key=lambda x: x[1], reverse=True)

            # --- Cache store ---
            if self._api_cache is not None:
                try:
                    self._api_cache.put(cache_key, [list(m) for m in matches])
                except Exception:
                    pass  # Cache write failure is non-fatal

            return matches

        except acoustid.WebServiceError as e:
            logger.error("AcoustID lookup failed for %s: %s", track.file_path.name, e)
            return []
        except Exception as e:
            logger.error("AcoustID HTTP request failed for %s: %s", track.file_path.name, e)
            return []

    def fingerprint_and_lookup(self, track: Track) -> tuple[Track, list[tuple[str, float, str | None, str | None]]]:
        """Convenience method: fingerprint a file and then look it up.

        Args:
            track: Track to process.

        Returns:
            Tuple of (updated track, list of AcoustID matches).
        """
        track = self.fingerprint(track)
        matches = self.lookup(track)

        if matches:
            # Store the best AcoustID on the track
            best_id, best_score, recording_id, _ = matches[0]
            track.acoustid = best_id
            if recording_id:
                track.musicbrainz_recording_id = recording_id

        return track, matches

    def fingerprint_batch(
        self,
        tracks: list[Track],
        max_workers: int | None = None,
        progress_callback: Callable[[int, int, Track], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[Track]:
        """Fingerprint multiple tracks in parallel using a thread pool.

        Only runs the local fpcalc binary (CPU/disk-bound) -- does NOT
        perform AcoustID API lookups.  Use ``lookup()`` afterwards for
        the rate-limited API phase.

        Args:
            tracks: Tracks to fingerprint.
            max_workers: Number of parallel workers.  Defaults to
                ``DEFAULT_MAX_CONCURRENT_FINGERPRINTS`` (auto-detected
                from CPU core count).
            progress_callback: Optional ``(completed, total, track)``
                callback invoked after each track finishes.
            cancel_check: Optional callable that returns ``True`` when
                processing should stop (e.g. pause or cancel requested).
                Checked after each completed future; pending futures are
                cancelled when it fires.

        Returns:
            The same list of Track objects with fingerprints populated.
        """
        if max_workers is None:
            max_workers = DEFAULT_MAX_CONCURRENT_FINGERPRINTS

        total = len(tracks)
        if total == 0:
            return tracks

        logger.info(
            "Batch fingerprinting %d tracks with %d workers", total, max_workers,
        )

        completed = 0

        def _do_fingerprint(track: Track) -> Track:
            """Fingerprint a single track (runs inside a worker thread)."""
            return self.fingerprint(track)

        # ThreadPoolExecutor works well here because fpcalc is a subprocess --
        # the GIL is released while waiting for the external process.
        # We manage the pool manually (no `with`) so we can call
        # shutdown(wait=False, cancel_futures=True) for instant teardown
        # when the user pauses/cancels/closes the app.
        pool = ThreadPoolExecutor(max_workers=max_workers)
        interrupted = False
        try:
            future_to_track = {
                pool.submit(_do_fingerprint, t): t for t in tracks
            }
            for future in as_completed(future_to_track):
                completed += 1
                track = future_to_track[future]
                try:
                    future.result()  # Propagate exceptions; track already mutated
                except Exception as e:
                    logger.error(
                        "Batch fingerprint error for %s: %s",
                        track.file_path.name, e,
                    )
                    track.error_message = f"Fingerprint error: {e}"

                if progress_callback:
                    progress_callback(completed, total, track)

                # Check if we should stop (pause or cancel requested)
                if cancel_check is not None and cancel_check():
                    interrupted = True
                    logger.info(
                        "Fingerprinting interrupted at %d/%d, "
                        "shutting down pool immediately",
                        completed, total,
                    )
                    break
        finally:
            if interrupted:
                # Non-blocking shutdown: cancel queued work and don't wait
                # for in-flight fpcalc subprocesses to finish.
                pool.shutdown(wait=False, cancel_futures=True)
            else:
                pool.shutdown(wait=True)

        logger.info("Batch fingerprinting complete: %d/%d succeeded",
                     sum(1 for t in tracks if t.fingerprint), total)
        return tracks

    @staticmethod
    def is_chromaprint_available() -> bool:
        """Check if the Chromaprint fpcalc binary is available.

        Returns:
            True if fpcalc is found and working.
        """
        try:
            # acoustid.fingerprint_file will fail if fpcalc isn't found,
            # but we can check more gracefully
            import shutil
            return shutil.which("fpcalc") is not None
        except Exception:
            return False

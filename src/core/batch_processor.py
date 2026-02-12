"""Batch processor -- orchestrates the full scanning, fingerprinting,
matching, scoring, tagging, and organizing pipeline."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from dataclasses import dataclass, field

from src.models.track import Track
from src.models.match_result import MatchResult, MatchCandidate
from src.models.processing_state import ProcessingState
from src.core.scanner import FileScanner
from src.core.tag_editor import TagEditor
from src.core.fingerprinter import Fingerprinter
from src.core.metadata_fetcher import MetadataFetcher
from src.core.archive_org_fetcher import ArchiveOrgFetcher
from src.core.fuzzy_matcher import FuzzyMatcher
from src.core.confidence_scorer import ConfidenceScorer
from src.core.file_organizer import FileOrganizer
from src.core.dj_screw_handler import DJScrewHandler
from src.core.compilation_detector import CompilationDetector
from src.core.report_writer import ReportWriter
from src.utils.file_utils import smart_title_case, normalize_artist_name
from src.utils.logger import get_logger
from src.utils.constants import (
    COMPILATION_INDICATORS,
    KNOWN_DJS,
    SCREW_ALBUM_KEYWORDS,
    DJ_SCREW_FOLDER_VARIANTS,
    DJ_SCREW_CHAPTER_FORMAT,
    DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST,
    SKIP_FOLDER_NAMES,
    MAX_ACOUSTID_MATCHES,
    ACOUSTID_HIGH_CONFIDENCE,
    ACOUSTID_MEDIUM_CONFIDENCE,
    PAUSE_CHECK_INTERVAL_SECONDS,
    REPORT_TITLE,
)

logger = get_logger("core.batch_processor")


@dataclass
class BatchStats:
    """Statistics for a batch processing run."""

    total: int = 0
    scanned: int = 0
    fingerprinted: int = 0
    auto_matched: int = 0
    needs_review: int = 0
    unmatched: int = 0
    organized: int = 0
    errors: int = 0

    @property
    def processed(self) -> int:
        return self.auto_matched + self.needs_review + self.unmatched + self.errors


@dataclass
class BatchResult:
    """Complete result of a batch processing run."""

    tracks: list[Track] = field(default_factory=list)
    match_results: dict[str, MatchResult] = field(default_factory=dict)
    stats: BatchStats = field(default_factory=BatchStats)


# Callback type: (current_step, total_steps, track, state_message)
ProgressCallback = Callable[[int, int, Track, str], None]


class BatchProcessor:
    """Orchestrates the full music identification and organization pipeline.

    Pipeline steps:
    1. Scan: Discover audio files and read existing tags
    2. Fingerprint: Generate audio fingerprints via Chromaprint
    3. Lookup: Match fingerprints against AcoustID
    4. Fetch metadata: Get full details from MusicBrainz / Discogs
    5. Fuzzy search: For files without fingerprint matches, search by existing tags
    6. Score: Calculate confidence scores for all candidates
    7. Classify: Auto-apply, review, or unmatched
    8. Organize: Move and tag auto-applied files (review files wait for user)
    """

    def __init__(
        self,
        acoustid_api_key: str,
        discogs_token: str | None = None,
        library_path: Path | None = None,
        backup_path: Path | None = None,
        keep_originals: bool = True,
        auto_threshold: float = 90.0,
        review_threshold: float = 70.0,
        progress_callback: ProgressCallback | None = None,
        fpcalc_available: bool = True,
        move_unmatched: bool = False,
        archive_org_enabled: bool = True,
        move_repo: object | None = None,
        dry_run: bool = False,
        max_concurrent_fingerprints: int | None = None,
        track_repo: object | None = None,
        api_cache: object | None = None,
    ) -> None:
        """Initialize the batch processor with all required components.

        Args:
            acoustid_api_key: AcoustID API key for fingerprint lookups.
            discogs_token: Optional Discogs token for additional metadata.
            library_path: Root path for the organized library.
            backup_path: Path for backups (None = auto).
            keep_originals: Whether to back up original files.
            auto_threshold: Confidence threshold for auto-apply.
            review_threshold: Confidence threshold for review vs manual.
            progress_callback: Optional progress callback function.
            fpcalc_available: Whether Chromaprint fpcalc is available on PATH.
            move_unmatched: If True, move unmatched files to _Unmatched folder.
                If False (default), leave them in place and write a report.
            archive_org_enabled: If True, use Internet Archive as a metadata
                source (primary for known collections, fallback otherwise).
            move_repo: Optional MoveHistoryRepository for persisting file move
                history to the database.
            dry_run: If True, run the full identification and scoring pipeline
                but skip all destructive operations (tag writing, file moves,
                backups).  Produces a preview of what *would* happen.
            max_concurrent_fingerprints: Number of parallel fingerprint workers.
                ``None`` uses the auto-detected default (half of CPU cores).
            track_repo: Optional TrackRepository for save-as-you-go persistence
                and resume-on-restart.
            api_cache: Optional ApiCacheRepository for caching API responses
                across runs.
        """
        self._scanner = FileScanner()
        self._tag_editor = TagEditor()
        self._fingerprinter = Fingerprinter(acoustid_api_key, api_cache=api_cache)
        self._metadata_fetcher = MetadataFetcher(discogs_token, api_cache=api_cache)
        self._max_concurrent_fingerprints = max_concurrent_fingerprints
        self._track_repo = track_repo
        self._archive_org = ArchiveOrgFetcher(
            cache_dir=library_path or Path("."),
            enabled=archive_org_enabled,
        )
        self._fuzzy = FuzzyMatcher()
        self._scorer = ConfidenceScorer(auto_threshold, review_threshold)
        self._dry_run = dry_run
        self._organizer = (
            FileOrganizer(
                library_path, backup_path, keep_originals,
                move_repo=move_repo,
                dry_run=dry_run,
            )
            if library_path
            else None
        )
        self._screw_handler = DJScrewHandler(self._archive_org, self._fuzzy)
        self._compilation_detector = CompilationDetector(self._screw_handler)
        self._report_writer = ReportWriter()
        self._progress_callback = progress_callback
        self._fpcalc_available = fpcalc_available
        self._move_unmatched = move_unmatched
        self._paused = False
        self._cancelled = False
        self._current_result: BatchResult | None = None

    @property
    def current_result(self) -> BatchResult | None:
        """The in-flight BatchResult (available during processing for live stats)."""
        return self._current_result

    def process_directory(self, root: Path | str) -> BatchResult:
        """Process all audio files in a directory.

        Args:
            root: Root directory to process.

        Returns:
            BatchResult with all tracks and match results.
        """
        root = Path(root)
        result = BatchResult()
        self._current_result = result

        # Step 1: Scan
        logger.info("Step 1/6: Scanning %s", root)
        tracks = self._scanner.scan(root)
        result.tracks = tracks
        result.stats.total = len(tracks)

        if not tracks:
            logger.info("No audio files found in %s", root)
            return result

        # Process each track through the pipeline
        self._process_tracks(result)

        return result

    def process_files(self, file_paths: list[Path | str]) -> BatchResult:
        """Process a list of specific files.

        Args:
            file_paths: List of file paths to process.

        Returns:
            BatchResult with all tracks and match results.
        """
        result = BatchResult()
        self._current_result = result

        tracks = self._scanner.scan_files(file_paths)
        result.tracks = tracks
        result.stats.total = len(tracks)

        if not tracks:
            logger.info("No valid audio files in the provided list")
            return result

        self._process_tracks(result)
        return result

    def process_prescanned(self, tracks: list[Track]) -> BatchResult:
        """Process a list of already-scanned Track objects (skips the scan step).

        Use this when the caller has already built Track objects (e.g. from a
        pre-scan), to avoid scanning the filesystem twice.

        Args:
            tracks: Pre-scanned Track objects.

        Returns:
            BatchResult with all tracks and match results.
        """
        result = BatchResult()
        self._current_result = result

        result.tracks = tracks
        result.stats.total = len(tracks)

        if not tracks:
            logger.info("No tracks provided to process_prescanned")
            return result

        self._process_tracks(result)
        return result

    def apply_match(self, track: Track, candidate: MatchCandidate) -> Track:
        """Apply a selected match candidate to a track (for user review selections).

        Updates the track's metadata, writes tags, and organizes the file.

        Args:
            track: The track to update.
            candidate: The selected match candidate.

        Returns:
            The updated Track.
        """
        # Update track metadata from candidate
        track.title = candidate.title or track.title
        track.artist = candidate.artist or track.artist
        track.album = candidate.album or track.album
        track.album_artist = candidate.album_artist or track.album_artist
        track.track_number = candidate.track_number or track.track_number
        track.total_tracks = candidate.total_tracks or track.total_tracks
        track.disc_number = candidate.disc_number or track.disc_number
        track.total_discs = candidate.total_discs or track.total_discs
        track.year = candidate.year or track.year
        track.genre = candidate.genre or track.genre
        track.musicbrainz_recording_id = (
            candidate.musicbrainz_recording_id or track.musicbrainz_recording_id
        )
        track.musicbrainz_release_id = (
            candidate.musicbrainz_release_id or track.musicbrainz_release_id
        )
        track.confidence = candidate.confidence

        # Normalize capitalization
        self._normalize_metadata(track, from_api=(candidate.source != ""))

        # Detect compilation
        self._compilation_detector.detect(track)

        if self._dry_run:
            # In dry-run mode, skip all destructive operations but still
            # preview the destination path.
            logger.info("[DRY RUN] Would apply tags: %s - %s", track.artist, track.title)
            if self._organizer:
                track = self._organizer.organize(track)
        else:
            # SAFETY: Back up the original file BEFORE writing any tags so the
            # backup preserves the unmodified metadata.  If matching is wrong,
            # the user can rollback to the true original.
            if self._organizer:
                self._organizer.backup_before_changes(track)

            # Write tags
            if self._tag_editor.write_tags(track):
                logger.info("Applied tags: %s - %s", track.artist, track.title)
            else:
                logger.warning("Failed to write tags for: %s", track.file_path)

            # Download and write cover art if available
            if candidate.cover_art_url and candidate.musicbrainz_release_id:
                art_data = self._metadata_fetcher.fetch_cover_art(
                    candidate.musicbrainz_release_id
                )
                if art_data:
                    self._tag_editor.write_cover_art(track, art_data)
                    track.cover_art_data = art_data

            # Organize file
            if self._organizer:
                track = self._organizer.organize(track)

        track.state = ProcessingState.COMPLETED
        return track

    def pause(self) -> None:
        """Pause the batch processing."""
        self._paused = True
        logger.info("Batch processing paused")

    def resume(self) -> None:
        """Resume the batch processing."""
        self._paused = False
        logger.info("Batch processing resumed")

    def cancel(self) -> None:
        """Cancel the batch processing."""
        self._cancelled = True
        logger.info("Batch processing cancelled")

    # --- Private pipeline ---

    def _process_tracks(self, result: BatchResult) -> None:
        """Run the full pipeline on all tracks in the batch result.

        Processing phases:
        1. **Resume skip** -- if a TrackRepository is available, check for
           tracks already processed in a previous run and skip them.
        2. **Batch fingerprint** -- fingerprint all remaining tracks in
           parallel using a thread pool (CPU/disk only, no API calls).
        3. **Per-track pipeline** -- sequential API lookups, scoring,
           classification, and tagging for each track.
        """
        total = len(result.tracks)

        # --- Phase 0: Resume skip ---
        already_done: set[str] = set()
        if self._track_repo is not None:
            try:
                already_done = self._track_repo.get_processed_paths()
            except Exception as e:
                logger.warning("Could not load resume state: %s", e)

        if already_done:
            skipped = 0
            remaining: list[Track] = []
            for track in result.tracks:
                fp = str(track.file_path)
                if fp in already_done:
                    skipped += 1
                    # Mark as already-done so stats are accurate
                    track.state = ProcessingState.COMPLETED
                else:
                    remaining.append(track)
            if skipped:
                logger.info(
                    "Resuming: skipping %d already-processed tracks (%d remaining)",
                    skipped, len(remaining),
                )
                result.stats.total = len(result.tracks)
            # Only process the remaining tracks
            work_tracks = remaining
        else:
            work_tracks = list(result.tracks)

        # --- Phase 1: Batch fingerprint (parallel, no API calls) ---
        if self._fpcalc_available and work_tracks:
            # Check pause/cancel before starting fingerprinting
            while self._paused and not self._cancelled:
                time.sleep(PAUSE_CHECK_INTERVAL_SECONDS)
            if self._cancelled:
                logger.info("Processing cancelled before fingerprinting")
                return

            fp_tracks = [t for t in work_tracks]  # all tracks get fingerprinted upfront
            logger.info(
                "Phase 1: Batch fingerprinting %d tracks...", len(fp_tracks),
            )

            # Throttle GUI updates during fingerprinting to prevent the
            # main thread from being starved by thousands of cross-thread
            # signals.  Fire at most every 0.25 s or every 1% of total.
            _fp_last_update = [0.0]  # mutable for closure
            _fp_update_pct = max(1, len(fp_tracks) // 100)

            def _on_fp_progress(completed: int, fp_total: int, track: Track) -> None:
                if not self._progress_callback:
                    return
                now = time.monotonic()
                is_milestone = (
                    completed == fp_total              # always report final
                    or completed % _fp_update_pct == 0  # ~1% intervals
                )
                if is_milestone or now - _fp_last_update[0] >= 0.25:
                    _fp_last_update[0] = now
                    self._progress_callback(
                        completed, fp_total, track,
                        f"Fingerprinting ({completed}/{fp_total})...",
                    )

            self._fingerprinter.fingerprint_batch(
                fp_tracks,
                max_workers=self._max_concurrent_fingerprints,
                progress_callback=_on_fp_progress,
                cancel_check=lambda: self._paused or self._cancelled,
            )
            result.stats.fingerprinted = sum(1 for t in fp_tracks if t.fingerprint)
            logger.info(
                "Phase 1 complete: %d/%d fingerprinted",
                result.stats.fingerprinted, len(fp_tracks),
            )

        # --- Phase 2: Per-track pipeline (sequential API calls) ---
        total_work = len(work_tracks)
        for idx, track in enumerate(work_tracks):
            # Check pause/cancel
            while self._paused and not self._cancelled:
                time.sleep(PAUSE_CHECK_INTERVAL_SECONDS)
            if self._cancelled:
                logger.info("Processing cancelled at track %d/%d", idx + 1, total_work)
                break

            step_num = idx + 1
            try:
                self._process_single_track(track, result, step_num, total_work)
            except Exception as e:
                logger.error("Error processing %s: %s", track.file_path.name, e)
                track.state = ProcessingState.ERROR
                track.error_message = str(e)
                result.stats.errors += 1

            # --- Save-as-you-go ---
            if self._track_repo is not None:
                try:
                    self._track_repo.save(track)
                except Exception as e:
                    logger.warning("Failed to save track state: %s", e)

        logger.info(
            "Batch complete: %d total, %d auto-matched, %d review, %d unmatched, %d errors",
            result.stats.total,
            result.stats.auto_matched,
            result.stats.needs_review,
            result.stats.unmatched,
            result.stats.errors,
        )

        # Write unmatched report so the app can pick up where it left off
        if result.stats.unmatched > 0 or result.stats.needs_review > 0:
            if self._organizer:
                self._report_writer.write_unmatched_report(
                    self._organizer.library_path, result.tracks, result.stats,
                )

    def _build_existing_tags_candidate(self, track: Track) -> MatchCandidate | None:
        """Create a MatchCandidate from the track's existing embedded tags.

        This lets the scorer compare API results against what the file already
        has. For well-tagged files (especially compilations/DJ Screw tapes),
        the existing tags are often *better* than API results because the
        APIs only know the original release, not the compilation album.

        Args:
            track: Track with tags already read.

        Returns:
            A MatchCandidate sourced from existing tags, or None if the track
            doesn't have at least title + artist.
        """
        if not track.has_basic_tags:
            return None

        return MatchCandidate(
            title=track.title or "",
            artist=track.artist or "",
            album=track.album or "",
            album_artist=track.album_artist or "",
            track_number=track.track_number,
            total_tracks=track.total_tracks,
            disc_number=track.disc_number,
            total_discs=track.total_discs,
            year=track.year,
            genre=track.genre,
            duration=track.duration,
            musicbrainz_recording_id=track.musicbrainz_recording_id,
            musicbrainz_release_id=track.musicbrainz_release_id,
            cover_art_url=track.cover_art_url,
            source="existing_tags",
        )

    def _process_single_track(
        self,
        track: Track,
        result: BatchResult,
        step_num: int,
        total: int,
    ) -> None:
        """Process a single track through the pipeline.

        For DJ Screw tracks, uses the fast path (archive.org only).
        For all other tracks, uses the standard pipeline (fingerprint,
        MusicBrainz, Discogs, scoring).
        """
        # Read existing tags
        self._emit_progress(step_num, total, track, "Reading tags...")
        track.state = ProcessingState.SCANNING
        self._tag_editor.read_tags(track)
        result.stats.scanned += 1

        # Guess from filename if tags are missing
        if not track.has_basic_tags:
            self._guess_tags_from_filename(track)

        # Snapshot the original tag values BEFORE matching overwrites them.
        # This powers the before/after diff in the Preview Report.
        track.snapshot_original_tags()

        # Detect compilation early so DJ Screw albums get normalized
        self._compilation_detector.detect(track)

        # --- DJ Screw fast path ---
        # Internet Archive has complete data for DJ Screw chapters.
        # Skip fingerprinting, MusicBrainz, Discogs, and scoring entirely.
        if self._screw_handler.is_dj_screw_track(track) and self._archive_org:
            self._process_dj_screw_track_pipeline(track, result, step_num, total)
            return

        # --- Standard pipeline ---
        self._process_single_track_standard(track, result, step_num, total)

    def _process_single_track_standard(
        self,
        track: Track,
        result: BatchResult,
        step_num: int,
        total: int,
    ) -> None:
        """Standard pipeline: AcoustID lookup, MB/Discogs, scoring, apply/review.

        Fingerprinting is assumed to have already been done in the batch
        fingerprint phase.  If it wasn't (e.g. fpcalc not available or track
        was added after the batch phase), the lookup is safely skipped.
        """
        acoustid_matches = []

        # AcoustID lookup (fingerprint was already generated in batch phase)
        if track.fingerprint:
            self._emit_progress(step_num, total, track, "Looking up AcoustID...")
            track.state = ProcessingState.FINGERPRINTING
            acoustid_matches = self._fingerprinter.lookup(track)
            if acoustid_matches:
                best_id, best_score, recording_id, _ = acoustid_matches[0]
                track.acoustid = best_id
                if recording_id:
                    track.musicbrainz_recording_id = recording_id
        else:
            logger.debug("No fingerprint for AcoustID lookup: %s", track.file_path.name)

        # Build match result
        match_result = MatchResult(lookup_source="fingerprint" if acoustid_matches else "fuzzy")

        if acoustid_matches:
            # Fetch full metadata for AcoustID matches.
            # Smart early-exit: when the top score is very high the first match
            # is almost always correct, so we skip unnecessary API calls.
            top_score = acoustid_matches[0][1] if acoustid_matches else 0.0
            if top_score >= ACOUSTID_HIGH_CONFIDENCE:
                fetch_limit = 1
            elif top_score >= ACOUSTID_MEDIUM_CONFIDENCE:
                fetch_limit = 2
            else:
                fetch_limit = MAX_ACOUSTID_MATCHES

            self._emit_progress(step_num, total, track, "Fetching metadata...")
            track.state = ProcessingState.FETCHING_METADATA

            for acid_id, score, recording_id, title in acoustid_matches[:fetch_limit]:
                if recording_id:
                    candidate = self._metadata_fetcher.fetch_recording(recording_id)
                    if candidate:
                        candidate.fingerprint_score = score
                        match_result.candidates.append(candidate)
        else:
            # Fuzzy search using existing tags and/or filename
            self._emit_progress(step_num, total, track, "Searching by tags...")
            track.state = ProcessingState.FETCHING_METADATA

            # Search MusicBrainz (works with title, artist, or both)
            search_title = track.title
            search_artist = track.artist

            if search_title or search_artist:
                # Decide whether to include album in the query.
                search_album = track.album
                if search_album and CompilationDetector.album_looks_like_compilation(search_album):
                    logger.debug(
                        "Album '%s' looks like a compilation/mixtape, "
                        "searching by title + artist only",
                        search_album,
                    )
                    search_album = None

                mb_candidates = self._metadata_fetcher.search_musicbrainz(
                    title=search_title,
                    artist=search_artist,
                    album=search_album,
                )
                if not mb_candidates and track.album and search_album is not None:
                    logger.debug(
                        "No MB results with album '%s', retrying without album",
                        track.album,
                    )
                    mb_candidates = self._metadata_fetcher.search_musicbrainz(
                        title=search_title,
                        artist=search_artist,
                    )
                match_result.candidates.extend(mb_candidates)

                # Also try Discogs (same approach)
                discogs_candidates = self._metadata_fetcher.search_discogs(
                    title=search_title,
                    artist=search_artist,
                    album=search_album,
                )
                if not discogs_candidates and track.album and search_album is not None:
                    logger.debug(
                        "No Discogs results with album '%s', retrying without album",
                        track.album,
                    )
                    discogs_candidates = self._metadata_fetcher.search_discogs(
                        title=search_title,
                        artist=search_artist,
                    )
                match_result.candidates.extend(discogs_candidates)

        # --- Internet Archive fallback ---
        # For non-DJ-Screw tracks, only use archive.org when MB/Discogs returned nothing.
        if not match_result.candidates:
            search_title = track.title
            search_artist = track.artist
            if (search_title or search_artist) and self._archive_org:
                logger.debug(
                    "No MB/Discogs candidates, trying archive.org fallback search "
                    "for '%s' by '%s'",
                    search_title, search_artist,
                )
                ia_fallback = self._archive_org.search_by_text(
                    title=search_title, artist=search_artist,
                )
                match_result.candidates.extend(ia_fallback)

        # Normalize capitalization based on data source
        has_api_candidates = bool(match_result.candidates)
        self._normalize_metadata(track, from_api=has_api_candidates)

        # Build the "existing tags" candidate AFTER compilation detection and
        # normalization so it captures the cleaned-up metadata.
        existing_candidate = self._build_existing_tags_candidate(track)

        # Inject the existing-tags candidate into the match results.
        if existing_candidate:
            match_result.candidates.append(existing_candidate)

        # Score all candidates
        self._emit_progress(step_num, total, track, "Scoring matches...")
        track.state = ProcessingState.SCORING
        match_result = self._scorer.score_match_result(
            track, match_result, result.tracks
        )

        # Boost existing-tags confidence for well-tagged files.
        # Use the scorer's output as a floor (not a full override) so we
        # don't blindly auto-apply files with wrong tags.
        if existing_candidate:
            if track.album:
                existing_candidate.confidence = max(existing_candidate.confidence, 75.0)
                existing_candidate.confidence = min(existing_candidate.confidence, 95.0)
            else:
                existing_candidate.confidence = max(existing_candidate.confidence, 50.0)
                existing_candidate.confidence = min(existing_candidate.confidence, 75.0)
            logger.debug(
                "Existing-tags candidate for '%s': confidence adjusted to %.0f%% "
                "(has_album=%s)",
                track.display_title, existing_candidate.confidence,
                bool(track.album),
            )
            # Re-sort so candidates are in the right order
            match_result.candidates.sort(key=lambda c: c.confidence, reverse=True)
            match_result.best_match_index = 0

        # Store match result keyed by file path
        result.match_results[str(track.file_path)] = match_result

        # Classify and act
        if match_result.has_match:
            best_confidence = match_result.best_confidence
            classification = self._scorer.classify(best_confidence)

            if classification == "auto_apply":
                self._emit_progress(step_num, total, track, "Auto-applying...")
                track.state = ProcessingState.AUTO_MATCHED
                track.confidence = best_confidence
                best = match_result.best_match
                if best:
                    self.apply_match(track, best)
                result.stats.auto_matched += 1
            else:
                # Needs review (top picks or manual)
                track.state = ProcessingState.NEEDS_REVIEW
                track.confidence = best_confidence
                result.stats.needs_review += 1
                self._emit_progress(step_num, total, track, "Needs review")
        else:
            # No match at all
            track.state = ProcessingState.UNMATCHED
            result.stats.unmatched += 1

            if self._move_unmatched and self._organizer:
                # Legacy behavior: move to _Unmatched folder
                self._organizer.organize_unmatched(track)
                self._emit_progress(step_num, total, track, "Unmatched (moved)")
            else:
                # Default: leave in place, will be logged in report
                self._emit_progress(step_num, total, track, "Unmatched (kept in place)")

    @staticmethod
    def _parse_disc_track(prefix: str, track: Track) -> None:
        """Parse a disc-track prefix like '1-04' or '2-12' and set disc/track numbers.

        Only sets disc_number and track_number if they aren't already populated
        (e.g. from embedded tags).

        Args:
            prefix: The numeric prefix string (e.g. "1-04", "2-12").
            track: Track to update.
        """
        m = re.match(r"^(\d+)-(\d+)$", prefix.strip())
        if not m:
            return
        disc = int(m.group(1))
        trk = int(m.group(2))
        if not track.disc_number:
            track.disc_number = disc
        if not track.track_number:
            track.track_number = trk

    def _guess_tags_from_filename(self, track: Track) -> None:
        """Try to extract artist and title from the filename when tags are missing.

        Handles common patterns:
        - "Artist - Title.mp3"
        - "01 Artist - Title.mp3"  (compilation style: track + artist + title)
        - "01 Title.mp3"  (track number + title, artist from parent folder)
        - "01 - Title.mp3"
        - "1-04 title.mp3" (disc-track format, sets disc_number=1, track_number=4)
        - "Artist- Title (Ft. Other).mp3" (dash without space)

        For compilation folders (DJ Screw etc.), also infers album from
        the parent folder name and sets album_artist.

        Args:
            track: Track to update with guessed tags.
        """

        stem = track.file_path.stem  # filename without extension

        # Try "Artist - Title" pattern (including "01 Artist - Title")
        if " - " in stem:
            parts = stem.split(" - ", 1)
            first = parts[0].strip()

            if re.match(r"^\d{1,3}$", first):
                # "01 - Title"
                if not track.track_number:
                    track.track_number = int(first)
                if not track.title:
                    track.title = parts[1].strip()
            elif re.match(r"^\d+-\d+$", first):
                # "1-04 - Title" -> disc 1, track 4
                self._parse_disc_track(first, track)
                if not track.title:
                    track.title = parts[1].strip()
            elif re.match(r"^(\d+-\d+)\s+(.+)$", first):
                # "1-01 Artist Name - Title" (compilation style with disc-track)
                m = re.match(r"^(\d+-\d+)\s+(.+)$", first)
                if m:
                    self._parse_disc_track(m.group(1), track)
                    if not track.artist:
                        track.artist = m.group(2).strip()
                    if not track.title:
                        track.title = parts[1].strip()
            elif re.match(r"^(\d{1,3})\s+(.+)$", first):
                # "01 Artist Name - Title" (compilation style)
                m = re.match(r"^(\d{1,3})\s+(.+)$", first)
                if m:
                    if not track.track_number:
                        track.track_number = int(m.group(1))
                    if not track.artist:
                        track.artist = m.group(2).strip()
                    if not track.title:
                        track.title = parts[1].strip()
            else:
                # "Artist - Title"
                if not track.artist:
                    track.artist = first
                if not track.title:
                    track.title = parts[1].strip()

        elif "- " in stem or " -" in stem:
            # Handle "Artist- Title (Ft. Other).mp3" (DJ Screw style, dash with inconsistent spacing)
            dash_parts = re.split(r"\s*-\s*", stem, maxsplit=1)
            if len(dash_parts) == 2:
                first = dash_parts[0].strip()
                second = dash_parts[1].strip()
                # Strip leading track number from first part
                num_match = re.match(r"^\d{1,3}\s+(.+)$", first)
                if num_match:
                    first = num_match.group(1).strip()
                if first and not track.artist:
                    track.artist = first
                if second and not track.title:
                    track.title = second

        elif re.match(r"^\d{1,3}\s+", stem):
            # "01 Title" or "05 Hellraizer" or "03 2Pac Ft. Dru Down - Something"
            m = re.match(r"^(\d{1,3})\s+(.*)", stem)
            if not track.track_number:
                track.track_number = int(m.group(1))
            content = m.group(2).strip()

            # Check if the content itself has "Artist - Title" within it
            if " - " in content:
                artist_part, title_part = content.split(" - ", 1)
                if not track.artist:
                    track.artist = artist_part.strip()
                if not track.title:
                    track.title = title_part.strip()
            else:
                if not track.title:
                    track.title = content

        elif re.match(r"^\d+-\d+\s+", stem):
            # "1-04 ambitionz az a ridah" -> disc 1, track 4
            m = re.match(r"^(\d+-\d+)\s+(.*)", stem)
            self._parse_disc_track(m.group(1), track)
            content = m.group(2).strip()
            if " - " in content:
                artist_part, title_part = content.split(" - ", 1)
                if not track.artist:
                    track.artist = artist_part.strip()
                if not track.title:
                    track.title = title_part.strip()
            else:
                if not track.title:
                    track.title = content
        else:
            # Just use the whole filename as title
            if not track.title:
                track.title = stem

        # --- Infer album and album_artist from folder structure ---
        parent_name = track.file_path.parent.name
        grandparent_name = track.file_path.parent.parent.name if len(track.file_path.parts) > 3 else ""

        # Check if grandparent or parent looks like a DJ/compilation artist
        _skip_names = SKIP_FOLDER_NAMES
        gp_lower = grandparent_name.lower().replace("_", " ").replace("-", " ").strip()
        parent_lower = parent_name.lower().replace("_", " ").replace("-", " ").strip()

        # Detect DJ Screw and similar compilation structures
        is_dj_folder = False
        dj_artist = None

        for folder_name, folder_lower in [(grandparent_name, gp_lower), (parent_name, parent_lower)]:
            if any(v in folder_lower for v in ("dj screw", "djscrew", "screwed up click", "va dj screw")):
                is_dj_folder = True
                dj_artist = "DJ Screw"
                break
            elif folder_lower.startswith("dj "):
                is_dj_folder = True
                dj_artist = normalize_artist_name(folder_name)
                break

        if is_dj_folder and dj_artist:
            if not track.album_artist:
                track.album_artist = dj_artist
            # Use the immediate parent folder as the album name (e.g. "Chapter 012 - June 27th")
            if not track.album and parent_lower not in _skip_names:
                if parent_lower != gp_lower:
                    # parent is the chapter/album, grandparent is the DJ
                    track.album = parent_name
                elif grandparent_name and gp_lower not in _skip_names:
                    track.album = grandparent_name
        elif not track.artist:
            # Non-compilation: try parent folder as artist
            if parent_lower not in _skip_names:
                track.artist = parent_name

        # Clean up "(Ft. ...)" from title -- keep it, but also strip for search purposes later
        # Remove truncation artifacts (filenames cut off at char limit)
        if track.title and track.title.endswith("."):
            track.title = track.title.rstrip(".")

        logger.debug(
            "Guessed from filename: artist='%s', title='%s', album='%s', "
            "album_artist='%s' (file: %s)",
            track.artist, track.title, track.album, track.album_artist,
            track.file_path.name,
        )

    def _normalize_metadata(self, track: Track, from_api: bool = True) -> None:
        """Normalize capitalization on track metadata.

        For API-sourced data we trust the official capitalization.
        For filename-derived or tag-derived data we apply smart title case.

        Args:
            track: Track to normalize.
            from_api: True if metadata came from an API (MusicBrainz/Discogs).
        """
        if from_api:
            # Trust API capitalization -- only fix known artist name overrides
            if track.artist:
                track.artist = normalize_artist_name(track.artist)
            if track.album_artist:
                track.album_artist = normalize_artist_name(track.album_artist)
        else:
            # Filename/tag-derived data -- apply full smart title case
            if track.title:
                track.title = smart_title_case(track.title)
            if track.artist:
                track.artist = normalize_artist_name(track.artist)
            if track.album:
                track.album = smart_title_case(track.album)
            if track.album_artist:
                track.album_artist = normalize_artist_name(track.album_artist)

        logger.debug(
            "Normalized metadata: artist='%s', title='%s', album='%s'",
            track.artist, track.title, track.album,
        )

    # ------------------------------------------------------------------
    # DJ Screw fast path
    # ------------------------------------------------------------------

    def _process_dj_screw_track_pipeline(
        self,
        track: Track,
        result: BatchResult,
        step_num: int,
        total: int,
    ) -> None:
        """Process a DJ Screw track using Internet Archive as the sole source.

        Delegates to DJScrewHandler for chapter extraction and candidate matching.
        Falls back to the standard pipeline if archive.org returns nothing.
        """
        self._emit_progress(step_num, total, track, "Searching Internet Archive...")
        track.state = ProcessingState.FETCHING_METADATA

        chapter_info = self._screw_handler.extract_screw_chapter_info(track)

        ia_candidates: list[MatchCandidate] = []

        if chapter_info:
            chapter_num, chapter_title = chapter_info
            logger.info(
                "DJ Screw fast path: Chapter %03d - %s",
                chapter_num, chapter_title or "?",
            )
            ia_candidates = self._archive_org.fetch_dj_screw_chapter(
                chapter_num, chapter_title,
            )
        else:
            search_title = track.title
            search_artist = track.artist
            if search_title or search_artist:
                logger.info(
                    "DJ Screw fast path: no chapter found, text search for '%s' by '%s'",
                    search_title, search_artist,
                )
                ia_candidates = self._archive_org.search_by_text(
                    title=search_title, artist=search_artist,
                )

        if not ia_candidates:
            logger.info(
                "DJ Screw fast path: archive.org returned nothing, "
                "falling back to standard pipeline for '%s'",
                track.display_title,
            )
            self._process_single_track_standard(track, result, step_num, total)
            return

        canonical_album = ia_candidates[0].album
        if canonical_album:
            track.album = canonical_album
        track.album_artist = DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST
        track.is_compilation = True

        best_candidate = self._screw_handler.match_track_to_ia_candidates(
            track, ia_candidates,
        )

        if best_candidate:
            self._emit_progress(step_num, total, track, "Applying archive.org match...")
            best_candidate.confidence = 98.0
            self.apply_match(track, best_candidate)
            track.state = ProcessingState.AUTO_MATCHED
            result.stats.auto_matched += 1
            self._emit_progress(
                step_num, total, track,
                f"Matched (archive.org, {best_candidate.confidence:.0f}%)",
            )
        else:
            logger.info(
                "DJ Screw fast path: no track-level match for '%s', "
                "applying album metadata only",
                track.display_title,
            )
            self._normalize_metadata(track, from_api=True)
            self._compilation_detector.detect(track)
            if self._dry_run:
                logger.info(
                    "[DRY RUN] Would write album-only tags: %s", track.file_path.name
                )
                if self._organizer:
                    track = self._organizer.organize(track)
            else:
                # SAFETY: backup before tag changes
                if self._organizer:
                    self._organizer.backup_before_changes(track)
                if self._tag_editor.write_tags(track):
                    logger.info("Wrote tags (album-only): %s", track.file_path.name)
                if self._organizer:
                    track = self._organizer.organize(track)
            track.state = ProcessingState.AUTO_MATCHED
            track.confidence = 80.0
            result.stats.auto_matched += 1
            self._emit_progress(
                step_num, total, track,
                "Applied (album metadata from archive.org)",
            )

    def retry_unmatched(self, library_path: Path) -> BatchResult | None:
        """Re-process previously unmatched files from the saved report.

        Reads the _unmatched_report.json, collects all file paths that still
        exist, and runs them through the pipeline again.

        Args:
            library_path: Root of the organized library.

        Returns:
            BatchResult from the retry run, or None if nothing to retry.
        """
        report = ReportWriter.load_unmatched_report(library_path)
        if not report:
            return None

        # Collect file paths that still exist
        retry_paths = []
        for entry in report.get("unmatched", []):
            path = Path(entry["file_path"])
            if path.exists():
                retry_paths.append(path)
            else:
                logger.debug("Skipping missing file: %s", path)

        for entry in report.get("errors", []):
            path = Path(entry["file_path"])
            if path.exists():
                retry_paths.append(path)
            else:
                logger.debug("Skipping missing file: %s", path)

        if not retry_paths:
            logger.info("No retryable files found (all missing or already processed)")
            return None

        logger.info("Retrying %d previously unmatched files", len(retry_paths))
        return self.process_files(retry_paths)

    def _emit_progress(
        self, current: int, total: int, track: Track, message: str
    ) -> None:
        """Emit a progress update if a callback is registered."""
        if self._progress_callback:
            self._progress_callback(current, total, track, message)
        logger.debug("[%d/%d] %s: %s", current, total, track.file_path.name, message)

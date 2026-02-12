"""File organizer -- safe file move/rename with backup and rollback support."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.models.track import Track
from src.utils.file_utils import (
    enforce_path_length,
    safe_copy,
    safe_move,
    sanitize_filename,
    unique_path,
)
from src.utils.logger import get_logger
from src.utils.constants import (
    DEFAULT_FOLDER_TEMPLATE,
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_SINGLES_FOLDER,
    DEFAULT_UNMATCHED_FOLDER,
)

if TYPE_CHECKING:
    from src.db.repositories import MoveHistoryRepository

logger = get_logger("core.file_organizer")


class FileOrganizer:
    """Organizes audio files into a clean directory structure.

    Standard structure:
        /Library/Artist Name/Album Name (Year)/01 - Track Title.ext

    Compilations (DJ mixes, Various Artists):
        /Library/Album Artist/Album Name (Year)/01 - Track Artist - Track Title.ext

    Singles:
        /Library/Artist Name/Singles/Track Title.ext

    Unmatched:
        /Library/_Unmatched/original_filename.ext
    """

    def __init__(
        self,
        library_path: Path | str,
        backup_path: (Path | str) | None = None,
        keep_originals: bool = True,
        folder_template: str = DEFAULT_FOLDER_TEMPLATE,
        file_template: str = DEFAULT_FILE_TEMPLATE,
        singles_folder: str = DEFAULT_SINGLES_FOLDER,
        unmatched_folder: str = DEFAULT_UNMATCHED_FOLDER,
        move_repo: MoveHistoryRepository | None = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the file organizer.

        Args:
            library_path: Root directory for the organized music library.
            backup_path: Directory for backing up originals. If None, uses
                library_path / '_Backups'.
            keep_originals: If True, copy originals to backup before moving.
            folder_template: Template for folder structure (supports {artist}, {album}, {year}).
            file_template: Template for file naming (supports {track}, {title}).
            singles_folder: Folder name for tracks without an album.
            unmatched_folder: Folder name for unmatched files.
            move_repo: Optional database repository for persisting move history
                across app restarts. If None, history is in-memory only.
            dry_run: If True, simulate all file operations without actually
                moving, copying, or writing any files.  ``organize()`` and
                ``organize_unmatched()`` will still update ``track.file_path``
                to the *would-be* destination so callers can preview results.
        """
        self._library_path = Path(library_path)
        self._backup_path = Path(backup_path) if backup_path else self._library_path / "_Backups"
        self._keep_originals = keep_originals
        self._folder_template = folder_template
        self._file_template = file_template
        self._singles_folder = singles_folder
        self._unmatched_folder = unmatched_folder
        self._move_repo = move_repo
        self._dry_run = dry_run
        # Rollback ledger: list of (original_path, current_path, backup_path) tuples
        self._move_history: list[tuple[Path, Path, Path | None]] = []
        # Pre-backups: tracks that were backed up before tag changes.
        # Maps resolved file path -> backup destination path.
        self._pre_backups: dict[Path, Path] = {}

    def backup_before_changes(self, track: Track) -> Path | None:
        """Create a backup of the file BEFORE any tags or metadata are modified.

        This must be called before ``write_tags()`` so the backup preserves
        the original, unmodified file.  Subsequent calls to ``organize()``
        will reuse this backup instead of creating a new one (which would
        contain the already-overwritten tags).

        In dry-run mode this is a no-op.

        Args:
            track: Track to back up (must have ``file_path`` set).

        Returns:
            Path to the backup file, or None if backups are disabled, the
            backup failed, or dry-run mode is active.
        """
        if self._dry_run:
            return None
        if not self._keep_originals:
            return None
        if not track.file_path.exists():
            return None

        resolved = track.file_path.resolve()
        if resolved in self._pre_backups:
            return self._pre_backups[resolved]

        backup_dest = self._backup_file(track)
        if backup_dest:
            self._pre_backups[resolved] = backup_dest
        return backup_dest

    def organize(self, track: Track) -> Track:
        """Organize a single track into the library structure.

        Backs up the original file (if not already backed up via
        ``backup_before_changes``), then moves it to the correct location
        based on its metadata.

        In **dry-run** mode the destination path is computed and stored on
        ``track.file_path`` so callers can inspect what *would* happen, but
        no files are moved, copied, or deleted.

        Args:
            track: Track with metadata populated.

        Returns:
            The Track with updated file_path (pointing to new location).
        """
        if not self._dry_run and not track.file_path.exists():
            logger.error("Cannot organize: file not found: %s", track.file_path)
            track.error_message = "File not found during organization"
            return track

        original_path = track.file_path

        # Determine destination
        dest = self._build_destination(track)

        # If the file is already at its correct destination, skip entirely.
        # This prevents re-running a scan from creating "(1)" copies.
        if not self._dry_run:
            try:
                if dest.resolve() == track.file_path.resolve():
                    logger.info("Already organized, skipping: %s", track.file_path.name)
                    return track
            except OSError:
                pass

        # --- Dry-run: report the move without touching the filesystem ---
        if self._dry_run:
            logger.info("[DRY RUN] Would organize: %s -> %s", track.file_path.name, dest)
            track.file_path = dest
            return track

        # Reuse a pre-existing backup (created by backup_before_changes),
        # or create one now if none exists yet.
        resolved = track.file_path.resolve()
        backup_dest = self._pre_backups.pop(resolved, None)
        if backup_dest is None and self._keep_originals:
            backup_dest = self._backup_file(track)

        # Check for duplicate: if the exact destination already exists, this is
        # likely a duplicate file being organized to the same slot. Skip it
        # instead of creating a "(1)" copy.
        if dest.exists() and dest != track.file_path:
            logger.warning(
                "Duplicate detected: '%s' would overwrite existing '%s'. "
                "Skipping -- the file already exists in the library.",
                track.file_path.name, dest,
            )
            track.error_message = (
                f"Duplicate: '{dest.name}' already exists in the library. "
                f"Source file left in place."
            )
            return track

        # Ensure unique path for edge cases (shouldn't normally trigger now)
        dest = unique_path(dest)

        try:
            safe_move(track.file_path, dest)
            logger.info("Organized: %s -> %s", track.file_path.name, dest)
            track.file_path = dest
            # Record for rollback (in-memory + database if available)
            self._record_move(original_path, dest, backup_dest)
            # Clean up empty source directories left behind
            self._cleanup_empty_dirs(original_path.parent)
        except (OSError, FileNotFoundError) as e:
            logger.error("Failed to organize %s: %s", track.file_path.name, e)
            track.error_message = f"Organization error: {e}"

        return track

    def organize_unmatched(self, track: Track) -> Track:
        """Move an unmatched track to the _Unmatched folder.

        Preserves the original filename.  In dry-run mode, updates the path
        without touching the filesystem.

        Args:
            track: Unmatched track.

        Returns:
            The Track with updated file_path.
        """
        if not self._dry_run and not track.file_path.exists():
            logger.error("Cannot organize unmatched: file not found: %s", track.file_path)
            return track

        original_path = track.file_path
        dest = self._library_path / self._unmatched_folder / track.file_path.name
        if not self._dry_run:
            dest = unique_path(dest)

        if self._dry_run:
            logger.info("[DRY RUN] Would move to unmatched: %s -> %s", track.file_path.name, dest)
            track.file_path = dest
            return track

        backup_dest = None
        if self._keep_originals:
            backup_dest = self._backup_file(track)

        try:
            safe_move(track.file_path, dest)
            logger.info("Moved to unmatched: %s -> %s", track.file_path.name, dest)
            track.file_path = dest
            # Record for rollback (in-memory + database if available)
            self._record_move(original_path, dest, backup_dest)
            # Clean up empty source directories left behind
            self._cleanup_empty_dirs(original_path.parent)
        except (OSError, FileNotFoundError) as e:
            logger.error("Failed to move unmatched %s: %s", track.file_path.name, e)
            track.error_message = f"Organization error: {e}"

        return track

    def preview_destination(self, track: Track) -> Path:
        """Preview where a track would be organized to (without actually moving it).

        Args:
            track: Track with metadata populated.

        Returns:
            The destination Path.
        """
        return self._build_destination(track)

    def _build_destination(self, track: Track) -> Path:
        """Build the destination path for a track based on its metadata.

        Handles both standard albums and compilations/various-artist releases.
        For multi-disc albums (total_discs > 1 or disc_number >= 2), a "Disc N"
        subfolder is inserted inside the album folder.

        Args:
            track: Track with metadata.

        Returns:
            Full destination path including filename.
        """
        title = sanitize_filename(track.display_title)
        artist = sanitize_filename(track.display_artist)
        album = sanitize_filename(track.display_album)
        year = track.year or "Unknown Year"
        track_num = track.track_number or 0
        disc_num = track.disc_number or 0
        total_discs = track.total_discs or 0
        suffix = track.file_path.suffix

        # Determine if this is a compilation
        is_comp = track.is_compilation
        album_artist = sanitize_filename(track.album_artist) if track.album_artist else None

        # For compilations, the folder uses album_artist (e.g. "DJ Screw" or "Various Artists")
        # and the filename includes the track artist
        if is_comp and album_artist:
            folder_artist = album_artist
        else:
            folder_artist = artist

        # Determine folder path
        if track.album and track.album.lower() not in ("", "unknown album"):
            # Full album track
            try:
                folder = self._folder_template.format(
                    artist=folder_artist,
                    album=album,
                    year=year,
                    disc=disc_num,
                )
            except (KeyError, ValueError) as e:
                logger.warning(
                    "Folder template '%s' failed (%s). "
                    "Using default structure. Check your config.",
                    self._folder_template, e,
                )
                folder = f"{folder_artist}/{album} ({year})"

            # Multi-disc album: add a "Disc N" subfolder when the album has
            # more than one disc, or when the disc number itself is 2+
            # (covers cases where total_discs isn't set but disc_number is).
            is_multi_disc = total_discs > 1 or disc_num >= 2
            if is_multi_disc and disc_num > 0:
                folder = f"{folder}/Disc {disc_num}"
        else:
            # Single / no album
            folder = f"{folder_artist}/{self._singles_folder}"

        # Determine filename
        if is_comp and album_artist and artist != album_artist:
            # Compilation: include track artist in filename
            # "01 - Keep Your Head Up - 2Pac.mp3"
            if track_num > 0:
                filename = f"{track_num:02d} - {title} - {artist}"
            else:
                filename = f"{title} - {artist}"
        elif track_num > 0:
            try:
                filename = self._file_template.format(
                    track=track_num,
                    title=title,
                    disc=disc_num,
                )
            except (KeyError, ValueError) as e:
                logger.warning(
                    "File template '%s' failed (%s). "
                    "Using default naming. Check your config.",
                    self._file_template, e,
                )
                filename = f"{track_num:02d} - {title}"
        else:
            filename = title

        dest = self._library_path / folder / f"{filename}{suffix}"
        return enforce_path_length(dest)

    def _record_move(
        self,
        original_path: Path,
        current_path: Path,
        backup_path: Path | None,
    ) -> None:
        """Record a file move to both in-memory history and the database.

        Args:
            original_path: Where the file was before organization.
            current_path: Where the file is now.
            backup_path: Path to backup copy, if created.
        """
        self._move_history.append((original_path, current_path, backup_path))
        if self._move_repo:
            try:
                self._move_repo.record_move(
                    original_path=str(original_path),
                    current_path=str(current_path),
                    backup_path=str(backup_path) if backup_path else None,
                )
            except Exception as e:
                logger.warning("Failed to persist move to database: %s", e)

    def rollback_last(self) -> bool:
        """Rollback the most recent file organization operation.

        Moves the file from its organized location back to its original path.
        If a backup exists and the original path is occupied, restores from backup.

        Returns:
            True if rollback succeeded, False otherwise.
        """
        if not self._move_history:
            logger.warning("No operations to rollback")
            return False

        original_path, current_path, backup_path = self._move_history.pop()
        return self._do_rollback(original_path, current_path, backup_path)

    def rollback_all(self) -> int:
        """Rollback all file organization operations in reverse order.

        Returns:
            Number of successfully rolled-back operations.
        """
        if not self._move_history:
            logger.info("No operations to rollback")
            return 0

        rolled_back = 0
        # Process in reverse order (LIFO)
        while self._move_history:
            original_path, current_path, backup_path = self._move_history.pop()
            if self._do_rollback(original_path, current_path, backup_path):
                rolled_back += 1

        logger.info("Rolled back %d operations", rolled_back)
        return rolled_back

    def rollback_track(self, track: Track) -> bool:
        """Rollback the organization of a specific track.

        Searches the move history for the track's current path and reverses
        the operation.

        Args:
            track: Track to rollback (uses track.file_path to find the entry).

        Returns:
            True if rollback succeeded, False if track not found in history.
        """
        for i, (original_path, current_path, backup_path) in enumerate(self._move_history):
            if current_path == track.file_path:
                self._move_history.pop(i)
                if self._do_rollback(original_path, current_path, backup_path):
                    track.file_path = original_path
                    return True
                return False

        logger.warning("Track not found in move history: %s", track.file_path)
        return False

    def _do_rollback(
        self,
        original_path: Path,
        current_path: Path,
        backup_path: Path | None,
    ) -> bool:
        """Execute a single rollback operation.

        Strategy:
        1. If the file is at current_path, move it back to original_path.
        2. If the file is not at current_path but a backup exists, restore from backup.
        3. If neither exists, the rollback fails.

        Args:
            original_path: Where the file was before organization.
            current_path: Where the file is now (organized location).
            backup_path: Path to backup copy, if one was made.

        Returns:
            True if rollback succeeded.
        """
        try:
            success = False
            if current_path.exists():
                original_path.parent.mkdir(parents=True, exist_ok=True)
                safe_move(current_path, original_path)
                logger.info("Rolled back: %s -> %s", current_path, original_path)

                # Clean up empty parent directories left behind
                self._cleanup_empty_dirs(current_path.parent)
                success = True
            elif backup_path and backup_path.exists():
                original_path.parent.mkdir(parents=True, exist_ok=True)
                safe_copy(backup_path, original_path)
                logger.info(
                    "Restored from backup: %s -> %s", backup_path, original_path
                )
                success = True
            else:
                logger.error(
                    "Cannot rollback: file not found at %s or backup %s",
                    current_path, backup_path,
                )
                return False

            # Remove the database entry after successful rollback
            if success and self._move_repo:
                try:
                    self._move_repo.remove_by_current_path(str(current_path))
                except Exception as e:
                    logger.warning("Failed to remove move history from DB: %s", e)
            return success
        except (OSError, FileNotFoundError) as e:
            logger.error("Rollback failed: %s", e)
            return False

    # System/hidden junk files that should not prevent a directory from
    # being considered empty.  These are created automatically by Windows
    # and macOS file explorers and have no user value.
    # NOTE: albumart.jpg and folder.jpg are intentionally excluded -- they
    # may be custom cover art placed by the user or by media players and
    # should NOT be silently deleted.
    _JUNK_FILENAMES = frozenset({
        "thumbs.db", "desktop.ini", ".ds_store", ".thumbs",
    })

    def _dir_is_effectively_empty(self, directory: Path) -> bool:
        """Check if a directory contains only system junk files (or nothing).

        Junk files (Thumbs.db, desktop.ini, .DS_Store, etc.) are deleted
        before returning True so ``rmdir()`` can succeed.

        Args:
            directory: Directory to check.

        Returns:
            True if the directory has no meaningful contents.
        """
        junk_found: list[Path] = []
        for child in directory.iterdir():
            if child.name.lower() in self._JUNK_FILENAMES:
                junk_found.append(child)
            else:
                return False  # Has a real file or subdirectory
        # Only junk files remain -- delete them
        for junk in junk_found:
            try:
                junk.unlink()
                logger.debug("Removed junk file: %s", junk)
            except OSError:
                return False
        return True

    def _cleanup_empty_dirs(self, directory: Path, stop_at: Path | None = None) -> None:
        """Remove empty directories, walking up the tree.

        **Safety**: Only directories that are *inside* the library root (or
        inside *stop_at* if provided) are eligible for cleanup.  Directories
        outside the library are never touched -- this prevents the app from
        accidentally deleting a user's source folder tree (e.g.
        ``D:\\Downloads\\``) after all its audio files have been organized.

        Stops when it hits any of these boundaries:
        - *stop_at* (explicit boundary, e.g. the library root)
        - The library root itself
        - A filesystem root (``C:\\``, ``D:\\``, ``/``)
        - A directory that still contains meaningful files or subdirectories

        System junk files (Thumbs.db, desktop.ini, .DS_Store) are cleaned
        up automatically so they don't block folder removal.

        Args:
            directory: Starting directory to check.
            stop_at: Optional boundary directory that should NOT be deleted.
                     Defaults to the library root.
        """
        boundary = (stop_at or self._library_path).resolve()
        try:
            current = directory.resolve()
            library_resolved = self._library_path.resolve()

            # Safety check: refuse to clean up anything outside the library.
            # This prevents deleting the user's source directories.
            try:
                current.relative_to(library_resolved)
            except ValueError:
                logger.debug(
                    "Skipping directory cleanup outside library: %s", current
                )
                return

            while current.exists() and current != boundary:
                # Never delete a filesystem root
                if current == current.parent:
                    break
                # Never go above the library root
                try:
                    current.relative_to(library_resolved)
                except ValueError:
                    break
                if not self._dir_is_effectively_empty(current):
                    break  # Directory has real content
                current.rmdir()
                logger.debug("Removed empty directory: %s", current)
                current = current.parent
        except OSError:
            pass  # Permission issue or race condition

    @property
    def library_path(self) -> Path:
        """The root path of the organized music library."""
        return self._library_path

    @property
    def move_history(self) -> list[tuple[Path, Path, Path | None]]:
        """Get the move history for external inspection (e.g., saving to DB).

        Returns:
            List of (original_path, current_path, backup_path) tuples.
        """
        return list(self._move_history)

    def _backup_file(self, track: Track) -> Path | None:
        """Back up a file before organizing it.

        Args:
            track: Track to back up.

        Returns:
            Path to the backup file, or None on failure.
        """
        try:
            # Preserve relative structure in backup
            backup_dest = self._backup_path / track.file_path.name
            backup_dest = unique_path(backup_dest)
            safe_copy(track.file_path, backup_dest)
            logger.debug("Backed up: %s -> %s", track.file_path.name, backup_dest)
            return backup_dest
        except (OSError, FileNotFoundError) as e:
            logger.warning("Backup failed for %s: %s", track.file_path.name, e)
            return None

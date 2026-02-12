"""File scanner -- discovers and catalogs audio files from a directory."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Generator

from src.models.track import Track
from src.models.processing_state import ProcessingState
from src.utils.file_utils import is_audio_file, get_file_size_mb
from src.utils.logger import get_logger

logger = get_logger("core.scanner")


class FileScanner:
    """Discovers audio files in a directory tree and creates Track objects.

    Usage:
        scanner = FileScanner()
        tracks = scanner.scan("/path/to/music")
    """

    def __init__(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """Initialize the scanner.

        Args:
            progress_callback: Optional callback(current, total, filename)
                called for each file discovered.
        """
        self._progress_callback = progress_callback

    def scan(self, root: Path | str) -> list[Track]:
        """Scan a directory tree and return a list of Track objects.

        Args:
            root: Root directory to scan.

        Returns:
            List of Track objects for all discovered audio files.

        Raises:
            FileNotFoundError: If root directory does not exist.
            NotADirectoryError: If root is not a directory.
        """
        root = Path(root)
        if not root.exists():
            raise FileNotFoundError(f"Directory not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        logger.info("Scanning directory: %s", root)

        # Collect all audio files first for accurate progress tracking
        audio_files = list(self._discover_audio_files(root))
        total = len(audio_files)
        logger.info("Found %d audio files", total)

        tracks: list[Track] = []
        for idx, file_path in enumerate(audio_files, start=1):
            track = self._create_track(file_path)
            tracks.append(track)

            if self._progress_callback:
                self._progress_callback(idx, total, file_path.name)

        logger.info("Scan complete: %d tracks cataloged", len(tracks))
        return tracks

    def scan_files(self, file_paths: list[Path | str]) -> list[Track]:
        """Create Track objects from a list of file and/or directory paths.

        Directories in the list are scanned recursively for audio files.
        Individual files are checked for supported audio extensions.

        Args:
            file_paths: List of file or directory paths to process.

        Returns:
            List of Track objects for all discovered audio files.
        """
        # Resolve all paths -- expand directories into individual audio files
        all_audio_files: list[Path] = []
        for p in file_paths:
            path = Path(p)
            logger.debug("Processing input path: %s (is_dir=%s, is_file=%s)",
                         path, path.is_dir(), path.is_file())
            if path.is_dir():
                # Recursively discover audio files in this directory
                discovered = list(self._discover_audio_files(path))
                logger.info("Found %d audio files in directory: %s", len(discovered), path)
                all_audio_files.extend(discovered)
            elif path.is_file() and is_audio_file(path):
                all_audio_files.append(path)
            else:
                logger.debug("Skipping non-audio path: %s", path)

        total = len(all_audio_files)
        logger.info("Total audio files to process: %d (from %d input paths)", total, len(file_paths))

        tracks: list[Track] = []
        for idx, file_path in enumerate(all_audio_files, start=1):
            track = self._create_track(file_path)
            tracks.append(track)

            if self._progress_callback:
                self._progress_callback(idx, total, file_path.name)

        logger.info("Scanned %d files from input list", len(tracks))
        return tracks

    def count_audio_files(self, root: Path | str) -> int:
        """Quick count of audio files without creating Track objects.

        Args:
            root: Root directory to count in.

        Returns:
            Number of audio files found.
        """
        root = Path(root)
        if not root.exists() or not root.is_dir():
            return 0
        return sum(1 for _ in self._discover_audio_files(root))

    def get_format_breakdown(self, tracks: list[Track]) -> dict[str, int]:
        """Get a breakdown of audio formats in the track list.

        Args:
            tracks: List of Track objects.

        Returns:
            Dictionary mapping format extension to count.
        """
        breakdown: dict[str, int] = {}
        for track in tracks:
            fmt = track.file_format or "unknown"
            breakdown[fmt] = breakdown.get(fmt, 0) + 1
        return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))

    def _discover_audio_files(self, root: Path) -> Generator[Path, None, None]:
        """Recursively discover audio files under a root directory.

        Args:
            root: Directory to search.

        Yields:
            Paths to audio files.
        """
        try:
            for entry in sorted(root.rglob("*")):
                if entry.is_file() and is_audio_file(entry):
                    yield entry
        except PermissionError as e:
            logger.warning("Permission denied during scan: %s", e)

    def _create_track(self, file_path: Path) -> Track:
        """Create a Track object from a file path.

        Args:
            file_path: Path to the audio file.

        Returns:
            A new Track object with basic file info populated.
        """
        return Track(
            file_path=file_path.resolve(),
            file_size_mb=get_file_size_mb(file_path),
            state=ProcessingState.PENDING,
        )

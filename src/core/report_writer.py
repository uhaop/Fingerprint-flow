"""Unmatched / needs-review report generation and loading.

Extracted from BatchProcessor to improve separation of concerns.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from src.models.track import Track
from src.models.processing_state import ProcessingState
from src.utils.logger import get_logger
from src.utils.constants import REPORT_TITLE

logger = get_logger("core.report_writer")


class ReportWriter:
    """Generates and loads JSON/TXT reports for unmatched and review tracks."""

    @staticmethod
    def write_unmatched_report(
        library_root: Path,
        tracks: list[Track],
        stats: object,
    ) -> None:
        """Write a report of unmatched and needs-review tracks.

        Generates two files in the library root:
        - _unmatched_report.json  -- machine-readable, used to resume later
        - _unmatched_report.txt   -- human-readable summary

        Args:
            library_root: Root directory of the organized library.
            tracks: All tracks from the batch run.
            stats: BatchStats object with .total, .auto_matched, etc.
        """
        library_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        unmatched_tracks = [t for t in tracks if t.state == ProcessingState.UNMATCHED]
        review_tracks = [t for t in tracks if t.state == ProcessingState.NEEDS_REVIEW]
        error_tracks = [t for t in tracks if t.state == ProcessingState.ERROR]

        # --- JSON report (machine-readable, for resume) ---
        report_data = {
            "generated_at": timestamp,
            "stats": {
                "total": stats.total,
                "auto_matched": stats.auto_matched,
                "needs_review": stats.needs_review,
                "unmatched": stats.unmatched,
                "errors": stats.errors,
            },
            "unmatched": [
                {
                    "file_path": str(t.file_path),
                    "original_path": str(t.original_path) if t.original_path else None,
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "album_artist": t.album_artist,
                    "is_compilation": t.is_compilation,
                    "error": t.error_message,
                }
                for t in unmatched_tracks
            ],
            "needs_review": [
                {
                    "file_path": str(t.file_path),
                    "original_path": str(t.original_path) if t.original_path else None,
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "album_artist": t.album_artist,
                    "confidence": t.confidence,
                    "is_compilation": t.is_compilation,
                }
                for t in review_tracks
            ],
            "errors": [
                {
                    "file_path": str(t.file_path),
                    "error": t.error_message,
                }
                for t in error_tracks
            ],
        }

        json_path = library_root / "_unmatched_report.json"
        try:
            json_path.write_text(
                json.dumps(report_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Unmatched report (JSON) written to: %s", json_path)
        except Exception as e:
            logger.error("Failed to write JSON report: %s", e)

        # --- Text report (human-readable) ---
        lines = [
            REPORT_TITLE,
            f"Generated: {timestamp}",
            "",
            "=== Summary ===",
            f"  Total processed:  {stats.total}",
            f"  Auto-matched:     {stats.auto_matched}",
            f"  Needs review:     {stats.needs_review}",
            f"  Unmatched:        {stats.unmatched}",
            f"  Errors:           {stats.errors}",
            "",
        ]

        if unmatched_tracks:
            lines.append(f"=== Unmatched Files ({len(unmatched_tracks)}) ===")
            lines.append(
                "  These files could not be identified. They remain in their original location."
            )
            lines.append(
                "  You can re-scan them after adding better tags or try a different search."
            )
            lines.append("")
            for t in unmatched_tracks:
                lines.append(f"  File: {t.file_path}")
                if t.artist or t.title:
                    lines.append(f"    Tags: {t.artist or '?'} - {t.title or '?'}")
                if t.album:
                    lines.append(f"    Album: {t.album}")
                if t.error_message:
                    lines.append(f"    Error: {t.error_message}")
                lines.append("")

        if review_tracks:
            lines.append(f"=== Needs Review ({len(review_tracks)}) ===")
            lines.append(
                "  These files have possible matches but need manual confirmation."
            )
            lines.append("")
            for t in review_tracks:
                lines.append(f"  File: {t.file_path}")
                lines.append(f"    Tags: {t.artist or '?'} - {t.title or '?'}")
                if t.album:
                    lines.append(f"    Album: {t.album}")
                lines.append(f"    Confidence: {t.confidence:.0f}%")
                lines.append("")

        if error_tracks:
            lines.append(f"=== Errors ({len(error_tracks)}) ===")
            lines.append("")
            for t in error_tracks:
                lines.append(f"  File: {t.file_path}")
                lines.append(f"    Error: {t.error_message}")
                lines.append("")

        txt_path = library_root / "_unmatched_report.txt"
        try:
            txt_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Unmatched report (TXT) written to: %s", txt_path)
        except Exception as e:
            logger.error("Failed to write TXT report: %s", e)

    @staticmethod
    def load_unmatched_report(library_path: Path) -> dict | None:
        """Load a previous unmatched report for resume/retry.

        Args:
            library_path: Root of the organized library.

        Returns:
            Parsed report data dict, or None if no report exists.
        """
        json_path = library_path / "_unmatched_report.json"
        if not json_path.exists():
            logger.debug("No unmatched report found at %s", json_path)
            return None

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            logger.info(
                "Loaded unmatched report: %d unmatched, %d review (from %s)",
                len(data.get("unmatched", [])),
                len(data.get("needs_review", [])),
                data.get("generated_at", "?"),
            )
            return data
        except Exception as e:
            logger.error("Failed to load unmatched report: %s", e)
            return None

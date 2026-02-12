# Changelog

All notable changes to Fingerprint Flow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

*No changes yet.*

## [0.1.0] - 2026-02-12

Initial open source release.

### Added
- Project scaffolding and file structure
- Core data models (Track, MatchResult, ProcessingState)
- File scanner for audio file discovery
- Tag reader/writer via mutagen (MP3, FLAC, M4A, OGG, Opus, WMA, AIFF, APE, WavPack)
- Audio fingerprinting via AcoustID/Chromaprint
- Parallel batch fingerprinting with configurable worker count (default: half CPU cores)
- Metadata fetcher (MusicBrainz, Discogs, Cover Art Archive)
- Internet Archive metadata fetcher (primary source for DJ Screw chapters, fallback for other tracks)
- DJ Screw handler for "Diary of the Originator" chapter detection and matching
- Compilation / mixtape / DJ mix detection
- Fuzzy matching for misspelling correction (rapidfuzz)
- Confidence scoring algorithm with weighted factors
- Safe file organizer with backup and rollback support
- Batch processing pipeline (scan -> fingerprint -> match -> score -> organize)
- SQLite database for state tracking, history, API response caching, and rollback
- Resume-on-restart: tracks already processed in a previous run are skipped
- Unmatched report generation (JSON + text) for resume/retry
- GUI: Main window with sidebar navigation and keyboard shortcuts (Ctrl+1-5)
- GUI: Import view with drag-and-drop, folder/file picker, retry unmatched
- GUI: Progress view with real-time stats, pause/resume/cancel
- GUI: Preview view for dry-run results with approve/reject workflow
- GUI: Review view with match candidate cards, confidence badges, and inline manual search
- GUI: Library view with Artist > Album > Track tree browser
- GUI: Settings view for configuration management
- Dark and light themes (Catppuccin Mocha/Latte)
- Smart title case and artist name normalization
- Reusable widget library (ConfidenceBadge, MatchSelector, TrackCard, SearchBar, AlbumArtViewer)
- Theme module with Catppuccin color palette constants
- Architecture Decision Records (ADRs)
- `AppConfig` typed dataclass model (`src/models/config.py`)

### Changed
- Reconciled config.yaml and config.example.yaml to use consistent nested structure
- Moved all magic numbers to named constants in constants.py
- Moved inline imports (time, re, base64) to file-level imports
- Replaced generic Exception catches with specific exception types
- Used specific mutagen/sqlite3/OS exception types throughout
- **BREAKING**: Backups are now created BEFORE tags are modified (was after). This
  ensures rollback restores the truly original file, not one with overwritten tags.
- Replaced incomplete dangerous-path blocklist with depth-based validation. Library
  paths must now be at least 2 levels deep from the filesystem root.
- Removed `albumart.jpg` and `folder.jpg` from the junk-file cleanup list. These
  may be intentional user-placed cover art and are no longer silently deleted.
- Empty directory cleanup now refuses to touch directories outside the library
  root, preventing accidental deletion of user source directories.
- Template formatting errors (folder_template, file_template) now log a warning
  instead of silently falling back to defaults.
- Replaced raw `dict` config pattern with typed `AppConfig` dataclass in main.py.
- Cross-device file moves now verify file size after copy before deleting source.
- Fingerprint batch progress updates are now throttled (~1% intervals or 250ms)
  to prevent GUI freezing on large libraries.

### Added (Open Source)
- MIT LICENSE file (was missing despite pyproject.toml declaring MIT)
- CONTRIBUTING.md with dev setup, coding style, and data safety guidelines
- CODE_OF_CONDUCT.md (Contributor Covenant v2.1)
- SECURITY.md with data safety policy and vulnerability reporting process
- GitHub Actions CI workflow (pytest, ruff, mypy on Python 3.10-3.14, Linux/macOS/Windows)
- GitHub issue templates (bug report with data impact field, feature request)
- GitHub pull request template with data safety checklist
- `[build-system]` section in pyproject.toml (enables `pip install -e .`)
- `project.urls`, `project.classifiers`, `project.keywords` in pyproject.toml
- Dry-run mode (`dry_run=True`) for BatchProcessor and FileOrganizer -- previews
  all changes without modifying any files
- `backup_before_changes()` public method on FileOrganizer for pre-tag backup
- Windows reserved filename protection (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
- Maximum path length enforcement (255 chars) with smart truncation
- Comprehensive tests for `file_utils.py` (53 new tests: safe_move, safe_copy,
  sanitize_filename, unique_path, enforce_path_length, smart_title_case, etc.)
- Safety-focused tests for FileOrganizer (backup-before-changes, no cleanup
  outside library, dry-run mode)
- Data Safety section in README explaining all protection mechanisms
- Troubleshooting section in README
- Badges in README (CI, Python version, License)

### Fixed
- Added python-dotenv to requirements.txt (was optionally imported but not listed)
- Removed unused imports (MatchResult in worker.py, datetime in repositories.py)
- Added missing type hints on __exit__, event handlers
- Replaced placeholder API keys in config.example.yaml with descriptive placeholders
- **CRITICAL**: Backups now contain original unmodified file (was backing up after
  tags were already overwritten)
- **CRITICAL**: Source directories outside the library are no longer deleted during
  empty-directory cleanup
- **CRITICAL**: Cross-device moves now verify integrity before deleting source file
- User album art files (albumart.jpg, folder.jpg) are no longer deleted as "junk"
- Pause/cancel now works during batch fingerprinting phase. Previously, pause/cancel
  was only checked in Phase 2 (per-track API lookups), so fingerprinting of all
  tracks would complete before the pause took effect.
- App no longer hangs on close during fingerprinting. Added `closeEvent` handler
  that cancels the worker and performs non-blocking thread pool shutdown.
- GUI no longer freezes when moving/resizing the window during fingerprinting.
  Progress updates are throttled to prevent flooding the Qt event loop.

[Unreleased]: https://github.com/uhaop/Fingerprint-flow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/uhaop/Fingerprint-flow/releases/tag/v0.1.0

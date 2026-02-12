<p align="center">
  <img src="assets/logo.png" alt="Fingerprint Flow" width="400">
</p>

<h1 align="center">Fingerprint Flow</h1>

<p align="center">
  <strong>Intelligent Music File Organizer</strong><br>
  Automatically identify, tag, and organize your music library using audio fingerprinting and online metadata services.
</p>

<p align="center">
  <a href="https://github.com/uhaop/Fingerprint-flow/actions/workflows/ci.yml"><img src="https://github.com/uhaop/Fingerprint-flow/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
</p>

## Features

- **Audio Fingerprinting**: Identifies songs via AcoustID/Chromaprint -- even with missing or wrong tags
- **Multi-Source Metadata**: Pulls from MusicBrainz, Discogs, Internet Archive, and Cover Art Archive
- **Internet Archive Integration**: Primary source for known collections (e.g. DJ Screw "Diary of the Originator") with text-search fallback for other tracks
- **DJ Screw / Compilation Detection**: Automatically detects DJ mixes, compilations, and the 363-chapter "Diary of the Originator" series with specialized matching
- **Confidence Scoring**: Auto-applies high-confidence matches, flags uncertain ones for review
- **Smart Organization**: Sorts files into `Artist/Album (Year)/01 - Title.ext` structure
- **Fuzzy Matching**: Corrects misspelled tags using fuzzy string matching
- **Parallel Fingerprinting**: Configurable thread pool (default: half your CPU cores) for fast batch fingerprinting
- **API Response Caching**: Caches AcoustID, MusicBrainz, and Discogs responses in SQLite to avoid redundant API calls across runs
- **Dry-Run Mode**: Preview exactly what would change before committing any modifications
- **Pause / Resume / Cancel**: Full control over long-running batch operations, with clean shutdown on app close
- **Resume on Restart**: Tracks already processed are skipped when you re-run the same batch
- **Safe Operations**: Backs up originals before any changes, with full rollback support
- **Modern Desktop UI**: PyQt6 interface with drag-and-drop, progress tracking, manual search, and review queue

## Data Safety

**Your music files are important. Fingerprint Flow is designed to never lose your data.**

- **Backups first**: Original files are backed up *before* tags are modified -- the backup always has your unmodified file
- **Dry-run mode**: Preview every change (tag edits, file moves) before anything happens
- **Full rollback**: Every file move is recorded in a database -- undo individual files or entire batches
- **No overwrites**: Duplicate files are detected and skipped, never silently replaced
- **Integrity checks**: Cross-drive moves verify file size after copying before deleting the source
- **Source protection**: The app never deletes directories outside your configured library path
- **System path blocking**: System directories (`C:\Windows`, `/usr`, etc.) are blocked as library paths

See [SECURITY.md](SECURITY.md) for the full data safety policy.

## Supported Formats

MP3, FLAC, M4A/AAC, OGG Vorbis, OGG Opus, WMA, AIFF, WAV, APE, WavPack

## Prerequisites

### Python 3.10+

### Chromaprint

The `fpcalc` binary is required for audio fingerprinting. Without it, the app falls back to tag-based fuzzy matching (less accurate but still functional).

**Windows:**
```
Download from https://acoustid.org/chromaprint
Extract and place fpcalc.exe in the project directory or add it to your PATH.
```

**macOS:**
```bash
brew install chromaprint
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt install libchromaprint-tools
```

## Installation

```bash
# Clone the repository
git clone https://github.com/uhaop/Fingerprint-flow.git
cd fingerprint-flow

# Create a virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install the package (includes all dependencies)
pip install -e .

# Or install from requirements.txt
pip install -r requirements.txt
```

## Configuration

1. Copy the example config:
   ```bash
   cp config/config.example.yaml config/config.yaml
   ```

2. Get your free API keys and add them to `config/config.yaml`:
   - **AcoustID**: Register at https://acoustid.org/new-application
   - **Discogs** (optional): Generate a token at https://www.discogs.com/settings/developers

   You can also set keys via environment variables in a `.env` file (loaded automatically via python-dotenv).

## Usage

```bash
# Launch the GUI
python -m src.main

# Or use the installed command
fingerprint-flow
```

## How It Works

1. **Import**: Drop a folder or select files to scan
2. **Fingerprint**: Files are fingerprinted in parallel via Chromaprint (configurable worker count)
3. **Identify**: Fingerprints are matched against AcoustID, then metadata is fetched from MusicBrainz and Discogs
4. **DJ Screw fast path**: Known DJ Screw chapters are matched directly against Internet Archive (skips MusicBrainz/Discogs)
5. **Fallback**: Tracks without fingerprint matches are searched by existing tags/filename via fuzzy matching. Internet Archive is used as a fallback when MusicBrainz/Discogs return nothing.
6. **Score**: A confidence score is calculated from multiple factors (fingerprint match, title/artist similarity, duration, album consistency)
7. **Organize**: High-confidence matches (>90%) are auto-applied; uncertain matches go to a review queue with manual search
8. **Output**: Files are renamed and moved into a clean `Artist/Album (Year)/Track` structure

## Project Structure

```
fingerprint-flow/
  src/
    main.py                    # Entry point, config loading
    core/                      # Core processing engine
      batch_processor.py       #   Orchestrator (scan -> fingerprint -> match -> organize)
      scanner.py               #   Audio file discovery
      fingerprinter.py         #   Chromaprint / AcoustID (parallel batch + lookup)
      metadata_fetcher.py      #   MusicBrainz / Discogs API client
      archive_org_fetcher.py   #   Internet Archive metadata source
      confidence_scorer.py     #   Weighted match scoring algorithm
      fuzzy_matcher.py         #   String similarity matching (rapidfuzz)
      tag_editor.py            #   Read/write audio metadata tags (mutagen)
      file_organizer.py        #   File moves with backup and rollback
      dj_screw_handler.py      #   DJ Screw chapter detection and matching
      compilation_detector.py  #   Compilation / mixtape / DJ mix detection
      report_writer.py         #   Unmatched report generation (JSON + text)
    models/                    # Data models (Track, MatchResult, ProcessingState, AppConfig)
    db/                        # SQLite database layer (state, history, API cache)
    gui/                       # PyQt6 desktop interface
      app.py                   #   Main window with sidebar navigation
      worker.py                #   Background threads (processing, review apply, manual search)
      views/                   #   Import, Progress, Preview, Review, Library, Settings
      widgets/                 #   Reusable components (ConfidenceBadge, MatchSelector, etc.)
      styles/                  #   Theme module (Catppuccin Mocha/Latte)
    utils/                     # Constants, file helpers, logging, rate limiter
  config/                      # Configuration files (config.yaml, config.example.yaml)
  tests/                       # Test suite (pytest)
  Docs/                        # Architecture Decision Records, API reference links
```

## Troubleshooting

### "Chromaprint Not Found" warning

The app works without Chromaprint but with reduced accuracy (tag-based matching only). To fix:

1. Download the **pre-built binary** (not source) from https://acoustid.org/chromaprint
2. Extract `fpcalc.exe` (Windows) or `fpcalc` (macOS/Linux)
3. Place it in the project directory, or add the folder containing `fpcalc` to your system `PATH`
4. Restart Fingerprint Flow

### "AcoustID API key not configured"

1. Register a free application at https://acoustid.org/new-application
2. Set `acoustid_api_key` in `config/config.yaml` (or via Settings in the GUI)

### Files not being matched

- Ensure Chromaprint is installed for best results
- Try lowering `auto_apply_threshold` in `config/config.yaml` (default: 90)
- Check `fingerprint_flow.log` for details on why a match was rejected
- Files with very short duration (<10s) or corrupted audio may not fingerprint -- you'll see `fpcalc exited with status 3` in the logs. This is normal for intros, skits, interludes, and instrumentals. These tracks fall back to tag/filename-based matching instead.
- `fpcalc exited with status 2` means the file couldn't be decoded (possibly corrupted or unusual codec). The track still gets matched via tags/filename.

### Window freezing during processing

If the GUI becomes unresponsive during fingerprinting of large libraries, this is due to progress update frequency. The app throttles updates to prevent this, but very large batches (10,000+ files) may still cause brief pauses.

## Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md) before submitting a PR.

See [SECURITY.md](SECURITY.md) for our data safety policy -- all PRs that touch file operations require extra review.

## License

[MIT](LICENSE)

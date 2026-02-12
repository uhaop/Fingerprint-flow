# Lessons Learned

Issues encountered during development and their solutions.

## Format

Each entry follows:
- **Date**: When the issue was found
- **Issue**: What went wrong
- **Root Cause**: Why it happened
- **Fix**: How it was resolved
- **Prevention**: How to avoid it in the future

---

### 2026-02-08: python-dotenv missing from requirements.txt

- **Issue**: `main.py` optionally imports `dotenv` to load `.env` files, but `python-dotenv` was not listed in `requirements.txt`. Users installing from requirements alone would silently skip `.env` loading, meaning API keys wouldn't be loaded unless manually set as environment variables.
- **Root Cause**: The import was wrapped in a try/except (graceful degradation), which masked the missing dependency.
- **Fix**: Added `python-dotenv>=1.0.0` to `requirements.txt`.
- **Prevention**: When adding optional imports, always list the package in requirements.txt. Use extras (`pip install .[optional]`) only if the feature is truly optional for the core workflow.

---

### 2026-02-08: config.yaml and config.example.yaml structure mismatch

- **Issue**: `config.example.yaml` used a well-organized nested YAML structure with comments, while the actual `config.yaml` was a flat key-value dump with no sections or comments. This made it confusing for users copying the example.
- **Root Cause**: `config.yaml` was generated/edited separately from the example and diverged over time.
- **Fix**: Rewrote `config.yaml` to match the nested, commented structure of `config.example.yaml`.
- **Prevention**: Always derive user config from the example file. Consider validating config structure at startup.

---

### 2026-02-08: Magic numbers scattered through codebase

- **Issue**: Hardcoded values like `time.sleep(0.5)`, `acoustid_matches[:5]`, `timeout=10`, `encoding=3`, `type=3`, `sim >= 80.0`, and `setMinimumSize(800, 600)` were used directly instead of named constants.
- **Root Cause**: Values were written inline during initial development and not refactored.
- **Fix**: Created named constants in `constants.py` (`PAUSE_CHECK_INTERVAL_SECONDS`, `MAX_ACOUSTID_MATCHES`, `API_TIMEOUT_SECONDS`, `ID3_ENCODING_UTF8`, `ALBUM_SIMILARITY_THRESHOLD`, `MIN_WINDOW_WIDTH`, etc.) and replaced all inline usages.
- **Prevention**: Always define numeric/string constants in `constants.py` from the start. Code review should flag any literal numbers that aren't immediately obvious (like 0, 1, or True/False).

---

### 2026-02-08: Inline imports inside methods

- **Issue**: `batch_processor.py` imported `time` and `re` inside methods, and `tag_editor.py` imported `base64` inside a method. This violates PEP 8 and makes dependencies harder to track.
- **Root Cause**: Quick-fix additions during development to avoid circular imports (which weren't actually present).
- **Fix**: Moved all imports to the top of each file.
- **Prevention**: Always add imports at the top of the file. Only use inline imports when there's a genuine circular import issue or the import is expensive and rarely needed.

---

### 2026-02-08: No rollback implementation despite infrastructure

- **Issue**: The plan specified rollback capability, and the database had a `history` table and `HistoryRepository.record_change()`, but `FileOrganizer` had no actual rollback method. If a file was misorganized, there was no way to undo it programmatically.
- **Root Cause**: Rollback was planned for a later phase but the infrastructure was built without the implementation.
- **Fix**: Added `rollback_last()`, `rollback_all()`, and `rollback_track()` methods to `FileOrganizer`, plus a `_move_history` ledger that tracks every move operation with original path, current path, and backup path.
- **Prevention**: When building infrastructure (schemas, repositories), also build at least a minimal implementation of the feature that uses it. Don't leave dead infrastructure.

---

### 2026-02-11: Pause button not working during fingerprinting phase

- **Issue**: Clicking "Pause" during batch fingerprinting logged "Batch processing paused" but fingerprinting continued for minutes. Errors kept appearing after the pause was acknowledged. Cancel also had no effect until all fingerprints completed.
- **Root Cause**: The pause/cancel check only existed in Phase 2 (per-track API lookups). Phase 1 (batch fingerprinting) submitted all tracks to a `ThreadPoolExecutor` at once and had zero awareness of the `_paused` or `_cancelled` flags. The `fingerprint_batch()` method accepted no cancellation mechanism.
- **Fix**: Added a `cancel_check` callback parameter to `fingerprint_batch()`. After each completed future, it checks the callback. When triggered, it cancels all pending futures and breaks out of the loop. In `batch_processor.py`, Phase 1 now passes `cancel_check=lambda: self._paused or self._cancelled` and also checks pause/cancel before starting fingerprinting.
- **Prevention**: Any long-running phase in the pipeline must check pause/cancel state. When using thread pools, always provide a cancellation mechanism -- don't assume the caller can wait for all tasks to complete.

---

### 2026-02-11: App hangs on close during fingerprinting

- **Issue**: Closing the app window while fingerprinting was in progress caused the process to hang indefinitely. The user had to force-kill the process. The console showed `threading._shutdown` blocking on `t.join()` and fpcalc errors continued appearing after the window was closed.
- **Root Cause**: Two problems: (1) `MainWindow` had no `closeEvent` handler, so closing the window didn't signal cancel to the worker thread. (2) The `ThreadPoolExecutor` was managed via a `with` statement, whose `__exit__` calls `shutdown(wait=True)` -- blocking until all ~32 in-flight fpcalc subprocesses finished. Python's `atexit` handler also joins all executor threads, causing the hang.
- **Fix**: (1) Added `closeEvent` to `MainWindow` that cancels the worker, waits up to 3 seconds for the thread to finish, then terminates it if needed. Also cleans up review/preview/search threads. (2) Changed `fingerprint_batch()` to manage the pool manually (no `with` statement). On cancellation, it calls `pool.shutdown(wait=False, cancel_futures=True)` for immediate teardown instead of blocking.
- **Prevention**: Always implement `closeEvent` (or equivalent cleanup) on the main window. Any background thread pool must support non-blocking shutdown. Never use `with ThreadPoolExecutor()` for long-running work that may be cancelled -- manage the pool lifecycle explicitly.

---

### 2026-02-11: GUI freezes when moving/resizing window during fingerprinting

- **Issue**: The application window became unresponsive during batch fingerprinting of large libraries (~9,000 files). Moving or resizing the window caused it to freeze or stutter.
- **Root Cause**: The progress callback in `fingerprint_batch()` fired for every single completed track. With 32 workers processing files rapidly, this generated dozens of Qt cross-thread signals per second. Each signal triggered a GUI repaint, starving the main thread's event loop of time to process window management events (drag, resize, paint).
- **Fix**: Throttled the fingerprinting progress callback to fire at most every ~1% of total tracks or every 250ms, whichever comes first. Always fires on the final track. This drops GUI update load from ~9,000 signals to ~100 for the same batch.
- **Prevention**: Progress callbacks from thread pools should always be throttled, especially when the thread pool has many workers. A good rule of thumb: emit at most 100-200 progress updates total, regardless of batch size. Use time-based or percentage-based gating.

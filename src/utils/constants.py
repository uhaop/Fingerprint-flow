"""Named constants for Fingerprint Flow. No magic numbers."""

# --- Application ---
APP_NAME = "Fingerprint Flow"
APP_VERSION = "0.1.0"

# --- Supported Audio Extensions ---
SUPPORTED_EXTENSIONS = frozenset({
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wma",
    ".aiff",
    ".aif",
    ".wav",
    ".ape",
    ".wv",
})

# --- Confidence Thresholds (defaults, overridable in config) ---
DEFAULT_AUTO_APPLY_THRESHOLD = 90
DEFAULT_REVIEW_THRESHOLD = 70

# --- Confidence Scoring Weights ---
WEIGHT_FINGERPRINT = 0.40
WEIGHT_TITLE = 0.20
WEIGHT_ARTIST = 0.20
WEIGHT_DURATION = 0.10
WEIGHT_ALBUM_CONSISTENCY = 0.10

# --- Duration Match Tolerance ---
DURATION_TOLERANCE_SECONDS = 3.0
DURATION_FALLOFF_MAX_SECONDS = 10.0

# --- Album Consistency ---
ALBUM_SIMILARITY_THRESHOLD = 80.0  # Min similarity (0-100) for album match

# --- API Rate Limits (seconds between requests) ---
MUSICBRAINZ_RATE_LIMIT = 1.0
DISCOGS_RATE_LIMIT = 1.0
MIN_API_RATE_INTERVAL = 1.5  # Conservative floor for all API calls (seconds)

# --- API Retry / Timeout ---
API_MAX_RETRIES = 3
API_RETRY_BACKOFF_SECONDS = 3.0  # Base wait between retries (multiplied by attempt)
API_TIMEOUT_SECONDS = 10  # Default HTTP request timeout
COVER_ART_TIMEOUT_SECONDS = 15  # Cover art download timeout

# --- AcoustID ---
MAX_ACOUSTID_MATCHES = 3  # Maximum AcoustID results to fetch metadata for (reduced from 5)
ACOUSTID_HIGH_CONFIDENCE = 0.95  # Score above which only top 1 match is fetched
ACOUSTID_MEDIUM_CONFIDENCE = 0.85  # Score above which only top 2 matches are fetched

# --- Processing ---
PAUSE_CHECK_INTERVAL_SECONDS = 0.5  # Sleep interval when paused
DEFAULT_BATCH_SIZE = 50
# Auto-detect: use half the logical cores, minimum 2, so the GUI and OS stay responsive.
# Users can override via max_concurrent_fingerprints in config.yaml.
import os as _os
DEFAULT_MAX_CONCURRENT_FINGERPRINTS = max(2, (_os.cpu_count() or 4) // 2)

# --- File Organization ---
DEFAULT_FOLDER_TEMPLATE = "{artist}/{album} ({year})"
DEFAULT_FILE_TEMPLATE = "{track:02d} - {title}"
DEFAULT_SINGLES_FOLDER = "Singles"
DEFAULT_UNMATCHED_FOLDER = "_Unmatched"

# --- ID3 Tag Constants ---
ID3_ENCODING_UTF8 = 3
ID3_PICTURE_TYPE_COVER_FRONT = 3

# --- GUI Defaults ---
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 800
MIN_WINDOW_WIDTH = 800
MIN_WINDOW_HEIGHT = 600
DEFAULT_THEME = "dark"

# --- Paths ---
DEFAULT_CONFIG_FILENAME = "config.yaml"
DEFAULT_LOG_FILENAME = "fingerprint_flow.log"
DEFAULT_DB_FILENAME = "fingerprint_flow.db"

# --- MusicBrainz ---
MUSICBRAINZ_APP_NAME = APP_NAME
MUSICBRAINZ_APP_VERSION = APP_VERSION
MUSICBRAINZ_CONTACT = "https://github.com/uhaop/Fingerprint-flow"  # Required by MB API TOS (app URL or email)

# --- Fuzzy Matching ---
FUZZY_MATCH_THRESHOLD = 80  # Minimum score (0-100) for a fuzzy match to be considered valid

# --- Filename Parsing ---
# Folder names to skip when inferring artist/album from path
SKIP_FOLDER_NAMES = frozenset({
    "music", "downloads", "desktop", "_unmatched", "unknown", "",
})

# Known compilation/DJ mix indicators in album or album_artist fields
COMPILATION_INDICATORS = frozenset({
    "various artists", "various", "va", "compilation", "soundtrack",
    "ost", "dj screw", "dj mix", "mixed by",
})

# Known DJ/compiler names that indicate a compilation
KNOWN_DJS = frozenset({
    "dj screw", "dj drama", "dj khaled", "dj clue", "dj kay slay",
    "dj green lantern", "dj whoo kid", "dj envy",
})

# DJ Screw album keywords
SCREW_ALBUM_KEYWORDS = frozenset({
    "diary of the originator", "screwed up click",
    "3 n the mornin", "3 'n the mornin", "3 n da morning",
    "screwin up", "screw tape", "d.o.t.o",
    "gray tape", "grey tape", "screwed and chopped",
    "screwed & chopped", "chopped and screwed", "chopped & screwed",
    "chopped not slopped",
})

# DJ Screw chapter album naming format.
# Follows the Internet Archive naming convention: "Chapter NNN - Title"
# The series has 363+ chapters (official catalog from Screwed Up Records & Tapes).
# Ch. 1-71 were released during DJ Screw's lifetime (1993-2000).
# Ch. 72-363+ are posthumous digitizations of the original "Gray Tapes".
DJ_SCREW_CHAPTER_FORMAT = "Chapter {chapter:03d} - {title}"
DIARY_OF_THE_ORIGINATOR_ALBUM_ARTIST = "DJ Screw"

# DJ Screw folder name variants
DJ_SCREW_FOLDER_VARIANTS = frozenset({
    "dj screw", "djscrew", "dj screw discography",
    "dj screw discography the diary of the originator",
    "screwed up click", "va dj screw",
})

# --- Internet Archive ---
ARCHIVE_ORG_RATE_LIMIT = 1.0  # Seconds between archive.org requests
ARCHIVE_ORG_TIMEOUT_SECONDS = 15  # HTTP request timeout for archive.org
ARCHIVE_ORG_DJ_SCREW_COLLECTION = "dj-screw-discography"
ARCHIVE_ORG_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_ORG_METADATA_URL = "https://archive.org/metadata"
ARCHIVE_ORG_DOWNLOAD_URL = "https://archive.org/download"
ARCHIVE_ORG_CACHE_FILENAME = "archive_org_collection_cache.json"
ARCHIVE_ORG_CACHE_MAX_AGE_DAYS = 30  # Refresh collection index after this many days

# --- Path Safety ---
# Maximum total path length. Windows default is 260; we use 255 to leave
# a small buffer for the drive letter, prefixes, and deduplication suffixes.
MAX_TOTAL_PATH_LENGTH = 255

# --- Report Strings ---
REPORT_TITLE = "Fingerprint Flow -- Unmatched & Review Report"
SECONDS_PER_MINUTE = 60

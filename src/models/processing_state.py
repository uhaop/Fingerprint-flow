"""Processing state model for tracking file progress."""

from enum import Enum


class ProcessingState(Enum):
    """Represents the current processing state of a track."""

    PENDING = "pending"
    SCANNING = "scanning"
    FINGERPRINTING = "fingerprinting"
    FETCHING_METADATA = "fetching_metadata"
    SCORING = "scoring"
    AUTO_MATCHED = "auto_matched"
    NEEDS_REVIEW = "needs_review"
    MANUALLY_MATCHED = "manually_matched"
    UNMATCHED = "unmatched"
    ORGANIZING = "organizing"
    COMPLETED = "completed"
    ERROR = "error"
    SKIPPED = "skipped"

    def is_terminal(self) -> bool:
        """Check if this state represents a final (non-transitional) state."""
        return self in {
            ProcessingState.COMPLETED,
            ProcessingState.ERROR,
            ProcessingState.SKIPPED,
            ProcessingState.UNMATCHED,
        }

    def needs_user_action(self) -> bool:
        """Check if this state requires user intervention."""
        return self in {
            ProcessingState.NEEDS_REVIEW,
            ProcessingState.UNMATCHED,
        }

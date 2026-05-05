"""Session status value object for upload session lifecycle."""

from enum import StrEnum


class SessionStatus(StrEnum):
    """Upload session lifecycle status.

    This enum represents the various states an upload session can transition through
    during its lifecycle. Status transitions follow specific rules to maintain
    business logic integrity.

    Valid state transitions:
        - PENDING → IN_PROGRESS (first chunk received)
        - IN_PROGRESS → COMPLETE (all chunks verified, offset == size)
        - IN_PROGRESS → FAILED (verification error, storage error)
        - IN_PROGRESS → ABORTED (user cancellation)
        - Any state → ABORTED (explicit abort by user or system)

    Attributes:
        PENDING: Session created, no chunks received yet
        IN_PROGRESS: Chunks are being uploaded and verified
        COMPLETE: All chunks verified, file assembled successfully
        FAILED: Error occurred during upload/assembly process
        ABORTED: User-initiated cancellation or system abort
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    ABORTED = "aborted"

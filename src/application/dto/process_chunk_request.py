"""DTO for process chunk use case request."""

import re
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ProcessChunkRequest:
    """Request DTO for process chunk use case.

    Contains all data needed to process a single uploaded chunk including
    the chunk data bytes, offset for validation, and SHA-256 checksum.

    Attributes:
        workspace_id: Workspace UUID for session isolation
        session_id: Upload session UUID
        chunk_data: Raw chunk bytes (typically 5MB, max varies)
        chunk_offset: Client-provided byte offset (must match session offset)
        chunk_checksum: SHA-256 hash of chunk_data (64-char lowercase hex)

    Validation:
        - workspace_id and session_id must be UUIDs
        - chunk_data must be non-empty bytes
        - chunk_offset must be >= 0
        - chunk_checksum must be valid SHA-256 format (validated by ChunkVerifier)
    """

    workspace_id: UUID
    session_id: UUID
    chunk_data: bytes
    chunk_offset: int
    chunk_checksum: str

    def __post_init__(self) -> None:
        """Validate request fields after initialization.

        Raises:
            ValueError: If any validation fails
        """
        # Validate chunk_offset is non-negative
        if self.chunk_offset < 0:
            raise ValueError(f"chunk_offset cannot be negative: {self.chunk_offset}")

        # Validate chunk_data is non-empty (redundant with use case but fail fast)
        if len(self.chunk_data) == 0:
            raise ValueError("chunk_data cannot be empty")

        # Validate chunk_checksum format (64 hex chars for SHA-256)
        if not re.match(r"^[a-f0-9]{64}$", self.chunk_checksum):
            raise ValueError(
                f"chunk_checksum must be 64 lowercase hex characters, "
                f"got: {self.chunk_checksum[:20]}..."
            )

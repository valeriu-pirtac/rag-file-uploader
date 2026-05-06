"""DTO for complete upload response.

This module defines the CompleteUploadResponse data transfer object returned
after successful file assembly and completion.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CompleteUploadResponse:
    """Response DTO for completed upload session.

    Returned after successful orchestration of file assembly, deduplication,
    event publication, and session completion.

    Attributes:
        file_id: Unique file identifier (same as session_id typically)
        s3_path: Full S3 URI where file is stored
        size_bytes: Final file size in bytes

    Usage:
        Returned to API layer which serializes to JSON for HTTP 200 response.
        Client receives file_id and s3_path for tracking and downstream
        processing coordination.

    Examples:
        >>> from uuid import uuid4
        >>> response = CompleteUploadResponse(
        ...     file_id=uuid4(),
        ...     s3_path="s3://bucket/workspace_abc/file_xyz.pdf",
        ...     size_bytes=1048576
        ... )
        >>> print(f"File uploaded: {response.s3_path}")
        >>> print(f"Size: {response.size_bytes} bytes")
    """

    file_id: UUID
    s3_path: str
    size_bytes: int

    def __post_init__(self) -> None:
        """Validate response fields after initialization.

        Raises:
            TypeError: If field types are invalid
            ValueError: If field values are invalid
        """
        if not isinstance(self.file_id, UUID):
            raise TypeError(f"file_id must be UUID, got {type(self.file_id)}")
        if not isinstance(self.s3_path, str):
            raise TypeError(f"s3_path must be str, got {type(self.s3_path)}")
        if not isinstance(self.size_bytes, int):
            raise TypeError(f"size_bytes must be int, got {type(self.size_bytes)}")

        if not self.s3_path:
            raise ValueError("s3_path cannot be empty")
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative, got {self.size_bytes}")

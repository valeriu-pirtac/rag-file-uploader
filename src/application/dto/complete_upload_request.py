"""DTO for complete upload request.

This module defines the CompleteUploadRequest data transfer object used to
initiate file assembly and completion orchestration.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CompleteUploadRequest:
    """Request DTO for completing an upload session.

    Triggered when all chunks have been uploaded and verified. Initiates
    the final orchestration flow: file assembly, deduplication check,
    virus scan (deferred), event publication, and session completion.

    Attributes:
        workspace_id: Workspace owning the upload session (from JWT claims)
        session_id: Upload session identifier (from path parameter)

    Business Rules:
        - workspace_id MUST match session.workspace_id (403 if mismatch)
        - session MUST exist and be IN_PROGRESS (404 if not found)
        - chunk_manifest MUST be complete (all indices 0 to N-1 present)
        - offset MUST equal file size (all bytes uploaded)

    Validation:
        - workspace_id: Valid UUID (enforced by FastAPI)
        - session_id: Valid UUID (enforced by FastAPI)
        - JWT claims validated by RBAC middleware (OWNER role required)

    Examples:
        >>> from uuid import uuid4
        >>> request = CompleteUploadRequest(
        ...     workspace_id=uuid4(),
        ...     session_id=uuid4()
        ... )
        >>> print(request.workspace_id)
        >>> print(request.session_id)
    """

    workspace_id: UUID
    session_id: UUID

    def __post_init__(self) -> None:
        """Validate request fields after initialization.

        Raises:
            TypeError: If workspace_id or session_id are not UUID instances
        """
        if not isinstance(self.workspace_id, UUID):
            raise TypeError(f"workspace_id must be UUID, got {type(self.workspace_id)}")
        if not isinstance(self.session_id, UUID):
            raise TypeError(f"session_id must be UUID, got {type(self.session_id)}")
